from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageOps


def load_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Golden Dashboard comparison artifacts.")
    parser.add_argument("--golden", default="design/references/dashboard/golden-dashboard.png", type=Path)
    parser.add_argument("--current", default="artifacts/visual/dashboard/golden-current-before.png", type=Path)
    parser.add_argument("--output", default="artifacts/visual/dashboard/comparison", type=Path)
    args = parser.parse_args()

    golden = load_rgb(args.golden)
    current_source = load_rgb(args.current)
    current = current_source.resize(golden.size, Image.Resampling.LANCZOS) if current_source.size != golden.size else current_source
    args.output.mkdir(parents=True, exist_ok=True)

    side_by_side = Image.new("RGB", (golden.width * 2, golden.height), "white")
    side_by_side.paste(golden, (0, 0))
    side_by_side.paste(current, (golden.width, 0))
    side_by_side.save(args.output / "side-by-side.png")

    Image.blend(golden, current, 0.5).save(args.output / "overlay-50.png")

    raw_diff = ImageChops.difference(golden, current)
    visible_diff = ImageEnhance.Contrast(ImageOps.autocontrast(raw_diff)).enhance(1.8)
    visible_diff.save(args.output / "diff.png")

    diff_pixels = list(raw_diff.get_flattened_data())
    mean_absolute_diff = sum(sum(pixel) for pixel in diff_pixels) / (len(diff_pixels) * 3)
    print(f"Golden: {golden.size[0]}x{golden.size[1]}")
    print(f"Current: {current_source.size[0]}x{current_source.size[1]} (comparison normalized: {current.size[0]}x{current.size[1]})")
    print(f"Mean absolute RGB diff: {mean_absolute_diff:.2f}")
    for name in ("side-by-side.png", "overlay-50.png", "diff.png"):
        print(f"Created {args.output / name}")


if __name__ == "__main__":
    main()
