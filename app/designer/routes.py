import json
import os
import re
import time
from xml.etree import ElementTree as ET
from typing import Optional

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.auth.rbac_utils import check_access
from app.designer import designer_bp

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "ico"}
ALLOWED_ICON_EXTENSIONS = {"svg"}

SLOTS_MANIFEST_REL = os.path.join("assets", "asset-slots.json")
SPRITE_REL = os.path.join("icons", "sprite.svg")
SPRITE_BASE_REL = os.path.join("icons", "sprite.base.svg")
ICON_OVERRIDES_REL = os.path.join("icons", "svg")


def _ext(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower().strip()


def _normalize_key_to_id(key: str) -> str:
    key = (key or "").strip()
    key = key.replace("\\", "-").replace("/", "-").replace(".", "-")
    key = re.sub(r"[^a-zA-Z0-9_-]+", "-", key)
    key = re.sub(r"-{2,}", "-", key).strip("-")
    return key


def _static_filename_from_target_path(target_path: str) -> Optional[str]:
    if not target_path:
        return None
    p = target_path.replace("\\", "/").strip()
    if p.startswith("static/"):
        return p[len("static/") :]
    # Allow already-relative paths.
    if p.startswith("/"):
        p = p[1:]
    return p


def _load_slots_manifest(static_folder: str) -> list[dict]:
    manifest_path = os.path.join(static_folder, SLOTS_MANIFEST_REL)
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        slots = data.get("slots", [])
        if isinstance(slots, list):
            return [s for s in slots if isinstance(s, dict) and s.get("key")]
        return []
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _parse_sprite_symbol_ids(sprite_path: str) -> set[str]:
    if not os.path.exists(sprite_path):
        return set()
    try:
        tree = ET.parse(sprite_path)
        root = tree.getroot()
        ids: set[str] = set()
        for sym in root.findall(f".//{{{SVG_NS}}}symbol"):
            sym_id = sym.get("id")
            if sym_id:
                ids.add(sym_id)
        return ids
    except Exception:
        return set()


def _ensure_sprite_base(static_folder: str) -> None:
    sprite_path = os.path.join(static_folder, SPRITE_REL)
    base_path = os.path.join(static_folder, SPRITE_BASE_REL)
    os.makedirs(os.path.dirname(sprite_path), exist_ok=True)
    if not os.path.exists(base_path) and os.path.exists(sprite_path):
        try:
            with open(sprite_path, "rb") as src, open(base_path, "wb") as dst:
                dst.write(src.read())
        except Exception:
            return
    if not os.path.exists(sprite_path) and os.path.exists(base_path):
        try:
            with open(base_path, "rb") as src, open(sprite_path, "wb") as dst:
                dst.write(src.read())
        except Exception:
            return


def _svg_file_to_symbol(svg_path: str, symbol_id: str) -> ET.Element | None:
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
        view_box = root.get("viewBox") or "0 0 24 24"

        sym = ET.Element(f"{{{SVG_NS}}}symbol", {"id": symbol_id, "viewBox": view_box})

        for child in list(root):
            # Skip metadata-heavy nodes that shouldn't be duplicated in sprite.
            tag = child.tag.lower()
            if tag.endswith("defs") or tag.endswith("metadata") or tag.endswith("title") or tag.endswith("desc"):
                continue
            sym.append(child)
        return sym
    except Exception:
        return None


def _rebuild_sprite(static_folder: str) -> None:
    _ensure_sprite_base(static_folder)
    base_path = os.path.join(static_folder, SPRITE_BASE_REL)
    sprite_path = os.path.join(static_folder, SPRITE_REL)
    overrides_dir = os.path.join(static_folder, ICON_OVERRIDES_REL)
    os.makedirs(overrides_dir, exist_ok=True)

    # Parse base symbols.
    base_symbols: list[ET.Element] = []
    base_map: dict[str, ET.Element] = {}
    try:
        base_tree = ET.parse(base_path)
        base_root = base_tree.getroot()
        for sym in base_root.findall(f".//{{{SVG_NS}}}symbol"):
            sym_id = sym.get("id")
            if sym_id:
                base_symbols.append(sym)
                base_map[sym_id] = sym
    except Exception:
        base_symbols = []
        base_map = {}

    # Apply overrides from icons/svg/*.svg
    override_symbols: dict[str, ET.Element] = {}
    for filename in os.listdir(overrides_dir):
        if _ext(filename) != "svg":
            continue
        symbol_id = os.path.splitext(filename)[0]
        full_path = os.path.join(overrides_dir, filename)
        sym = _svg_file_to_symbol(full_path, symbol_id)
        if sym is not None:
            override_symbols[symbol_id] = sym

    # Build output sprite.
    out_root = ET.Element(f"{{{SVG_NS}}}svg", {"xmlns": SVG_NS, "style": "display:none"})
    out_defs = ET.SubElement(out_root, f"{{{SVG_NS}}}defs")

    used: set[str] = set()
    for sym in base_symbols:
        sym_id = sym.get("id") or ""
        if sym_id in override_symbols:
            out_defs.append(override_symbols[sym_id])
            used.add(sym_id)
        elif sym_id:
            out_defs.append(sym)
            used.add(sym_id)

    # Add new override-only symbols not present in base.
    for sym_id in sorted(override_symbols.keys()):
        if sym_id in used:
            continue
        out_defs.append(override_symbols[sym_id])

    try:
        ET.ElementTree(out_root).write(sprite_path, encoding="utf-8", xml_declaration=True)
    except Exception:
        return

@designer_bp.route('/designer/assets')
@login_required
@check_access('assets.manage')
def assets_manager():
    """Галерея ассетов для дизайнера"""
    static_folder = current_app.static_folder
    assets: list[dict] = []

    _ensure_sprite_base(static_folder)
    # If sprite is missing but base exists, recreate it.
    sprite_path = os.path.join(static_folder, SPRITE_REL)
    base_path = os.path.join(static_folder, SPRITE_BASE_REL)
    if (not os.path.exists(sprite_path)) and os.path.exists(base_path):
        _rebuild_sprite(static_folder)

    slots = _load_slots_manifest(static_folder)
    sprite_symbol_ids = _parse_sprite_symbol_ids(sprite_path)

    slot_cards: list[dict] = []
    for slot in slots:
        key = str(slot.get("key", "")).strip()
        slot_type = str(slot.get("type", "icon")).strip().lower()
        context = str(slot.get("context", "")).strip().lower()
        safe_id = _normalize_key_to_id(key)

        card = {
            "key": key,
            "id": safe_id,
            "type": slot_type,
            "context": context,
            "recommendedSize": slot.get("recommendedSize") or "",
            "usedIn": slot.get("usedIn") or [],
        }

        if slot_type == "icon":
            override_path = os.path.join(ICON_OVERRIDES_REL, f"{safe_id}.svg").replace("\\", "/")
            card["present"] = safe_id in sprite_symbol_ids
            card["overridePath"] = override_path
            card["previewKind"] = "sprite"
        else:
            target_path = slot.get("targetPath") or ""
            static_filename = _static_filename_from_target_path(str(target_path))
            card["targetPath"] = target_path
            if static_filename:
                full_path = os.path.join(static_folder, static_filename)
                card["present"] = os.path.exists(full_path)
                card["url"] = url_for("static", filename=static_filename) + f"?v={int(time.time())}"
            else:
                card["present"] = False
                card["url"] = None

        slot_cards.append(card)

    target_dirs = ["icons", "images", "img", "assets", "documents"]
    for subdir in target_dirs:
        full_path = os.path.join(static_folder, subdir)
        if not os.path.exists(full_path):
            continue
        for filename in os.listdir(full_path):
            ext = _ext(filename)
            if ext in (ALLOWED_IMAGE_EXTENSIONS | ALLOWED_ICON_EXTENSIONS):
                assets.append(
                    {
                        "folder": subdir,
                        "filename": filename,
                        "path": f"{subdir}/{filename}",
                        "url": url_for("static", filename=f"{subdir}/{filename}") + f"?v={int(time.time())}",
                    }
                )

    assets.sort(key=lambda a: (a["folder"], a["filename"]))
    slot_cards.sort(key=lambda s: (s.get("type", ""), s.get("context", ""), s.get("key", "")))

    return render_template("designer_assets.html", assets=assets, slots=slot_cards)

@designer_bp.route('/designer/assets/replace', methods=['POST'])
@login_required
@check_access('assets.manage')
def replace_asset():
    """Замена существующего файла"""
    if 'file' not in request.files:
        flash('Файл не выбран', 'error')
        return redirect(url_for('designer.assets_manager'))
        
    file = request.files['file']
    target_folder = request.form.get('folder')
    target_filename = request.form.get('filename')
    
    if file.filename == '':
        flash('Файл не выбран', 'error')
        return redirect(url_for('designer.assets_manager'))
        
    if file and target_folder and target_filename:
        if '..' in target_folder or '..' in target_filename:
            flash('Недопустимый путь', 'error')
            return redirect(url_for('designer.assets_manager'))
            
        full_path = os.path.join(current_app.static_folder, target_folder, target_filename)
        
        if not os.path.exists(full_path):
            flash('Целевой файл не найден', 'error')
            return redirect(url_for('designer.assets_manager'))
            
        try:
            file.save(full_path)
            flash(f'Файл {target_filename} успешно обновлен!', 'success')
        except Exception as e:
            flash(f'Ошибка при сохранении: {e}', 'error')
            
    return redirect(url_for('designer.assets_manager'))


@designer_bp.route("/designer/assets/upload", methods=["POST"])
@login_required
@check_access("assets.manage")
def upload_asset():
    """Загрузка/замена файла по слоту из манифеста ассетов."""
    static_folder = current_app.static_folder
    slots = _load_slots_manifest(static_folder)
    slot_by_key = {str(s.get("key")): s for s in slots if s.get("key")}

    slot_key = (request.form.get("slot_key") or "").strip()
    if not slot_key or slot_key not in slot_by_key:
        flash("Слот не найден в манифесте ассетов", "error")
        return redirect(url_for("designer.assets_manager"))

    slot = slot_by_key[slot_key]
    slot_type = str(slot.get("type", "icon")).strip().lower()

    if "file" not in request.files:
        flash("Файл не выбран", "error")
        return redirect(url_for("designer.assets_manager"))

    file = request.files["file"]
    if not file or file.filename == "":
        flash("Файл не выбран", "error")
        return redirect(url_for("designer.assets_manager"))

    ext = _ext(file.filename)

    if slot_type == "icon":
        if ext not in ALLOWED_ICON_EXTENSIONS:
            flash("Для иконок принимаются только SVG файлы", "error")
            return redirect(url_for("designer.assets_manager"))

        safe_id = _normalize_key_to_id(slot_key)
        overrides_dir = os.path.join(static_folder, ICON_OVERRIDES_REL)
        os.makedirs(overrides_dir, exist_ok=True)
        dest_path = os.path.join(overrides_dir, f"{safe_id}.svg")

        try:
            file.save(dest_path)
            _rebuild_sprite(static_folder)
            flash(f"Иконка для слота {slot_key} обновлена", "success")
        except Exception as e:
            flash(f"Ошибка при сохранении SVG: {e}", "error")
        return redirect(url_for("designer.assets_manager"))

    # image
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        flash("Недопустимый формат изображения", "error")
        return redirect(url_for("designer.assets_manager"))

    target_path = str(slot.get("targetPath") or "").strip()
    static_filename = _static_filename_from_target_path(target_path)
    if not static_filename:
        flash("У слота не задан targetPath (куда сохранять файл)", "error")
        return redirect(url_for("designer.assets_manager"))

    if ".." in static_filename.replace("\\", "/").split("/"):
        flash("Недопустимый путь", "error")
        return redirect(url_for("designer.assets_manager"))

    dest_path = os.path.join(static_folder, static_filename)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    try:
        file.save(dest_path)
        flash(f"Файл для слота {slot_key} обновлён", "success")
    except Exception as e:
        flash(f"Ошибка при сохранении файла: {e}", "error")

    return redirect(url_for("designer.assets_manager"))
