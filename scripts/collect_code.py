import os

MAX_PART_SIZE_MB = 50 
ALLOWED_EXTENSIONS = {'.py', '.js', '.html', '.css', '.md', '.json', '.sql', '.ts', '.tsx', '.jsx'}
IGNORE_DIRS = {
    '.git', '__pycache__', 'node_modules', 'venv', '.idea', '.vscode', 
    'dist', 'build', 'coverage', '.next', 'public'
}

def get_file_handler(part_num, base_name="project_context"):
    filename = f"{base_name}_part_{part_num}.txt"
    print(f"--> Создаем новую часть: {filename}")
    return open(filename, 'w', encoding='utf-8')

def collect_project_code_split(root_dir):
    part_num = 1
    current_size = 0
    max_bytes = MAX_PART_SIZE_MB * 1024 * 1024
    
    out = get_file_handler(part_num)

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            if any(file.endswith(ext) for ext in ALLOWED_EXTENSIONS):
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, root_dir)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    header = f"\n{'='*50}\nFILE: {relative_path}\n{'='*50}\n\n"
                    footer = "\n\n"
                    block_size = len(header.encode('utf-8')) + len(content.encode('utf-8')) + len(footer.encode('utf-8'))
                    
                    if current_size + block_size > max_bytes:
                        out.close()
                        part_num += 1
                        out = get_file_handler(part_num)
                        current_size = 0
                    
                    out.write(header)
                    out.write(content)
                    out.write(footer)
                    current_size += block_size
                    
                    print(f"Добавлен: {relative_path}")
                    
                except Exception as e:
                    print(f"Пропущен {relative_path} (ошибка или бинарный файл): {e}")

    out.close()
    print(f"\nГотово! Проект разбит на {part_num} файл(а/ов).")

if __name__ == "__main__":
    collect_project_code_split('.')