import os
import re
import glob

def migrate_templates():
    template_dir = r"d:\VSCode\kege_selector_app\templates"
    
    replacements = [
        (r"\bbg-white(?![/a-zA-Z0-9-])", "bg-surface"),
        (r"\bbg-slate-50(?![/a-zA-Z0-9-])", "bg-surface-alt"),
        (r"\bbg-slate-100(?![/a-zA-Z0-9-])", "bg-surface-alt"),
        (r"\btext-slate-900(?![/a-zA-Z0-9-])", "text-primary"),
        (r"\btext-slate-800(?![/a-zA-Z0-9-])", "text-primary"),
        (r"\btext-slate-700(?![/a-zA-Z0-9-])", "text-secondary"),
        (r"\btext-slate-600(?![/a-zA-Z0-9-])", "text-muted"),
        (r"\btext-slate-500(?![/a-zA-Z0-9-])", "text-muted"),
        (r"\btext-slate-400(?![/a-zA-Z0-9-])", "text-muted"),
        (r"\border-slate-200(?![/a-zA-Z0-9-])", "border-stroke"),
        (r"\border-slate-300(?![/a-zA-Z0-9-])", "border-stroke-strong"),
        (r"\bshadow-sm\b", "shadow-sm dark:shadow-none"),
    ]
    
    compiled_replacements = [(re.compile(p), r) for p, r in replacements]
    changed_files = 0
    
    for filepath in glob.glob(os.path.join(template_dir, "**/*.html"), recursive=True):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                
            original_content = content
            for pattern, replacement in compiled_replacements:
                content = pattern.sub(replacement, content)
                
            if original_content != content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                changed_files += 1
                print(f"Updated: {filepath}")
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            
    print(f"Migration completed. Changed {changed_files} files.")

if __name__ == "__main__":
    migrate_templates()
