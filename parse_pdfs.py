import os
import glob
import re
import fitz  # PyMuPDF
from app import create_app
from core.db_models import TheoryBlock, db

app = create_app()

def extract_task_number_from_text(text):
    # Try to find "№ 10." or similar
    match = re.search(r'№\s*(\d+)', text)
    if match:
        return int(match.group(1))
    return None

def parse_pdfs():
    with app.app_context():
        pdf_dir = r'e:\projects\kege_selector_app_current\static\uploads\pdfs'
        pdfs = glob.glob(os.path.join(pdf_dir, '*.pdf'))
        
        updated_count = 0
        
        for pdf_path in pdfs:
            try:
                doc = fitz.open(pdf_path)
                full_text = []
                for page in doc:
                    full_text.append(page.get_text())
                
                content = "\n".join(full_text)
                
                # Determine task number from filename or content
                task_number = None
                
                # Check filename: timeline_1_lesson_10_...
                file_match = re.search(r'lesson_(\d+)_', os.path.basename(pdf_path))
                if file_match:
                    task_number = int(file_match.group(1))
                else:
                    task_number = extract_task_number_from_text(content)
                
                if task_number is not None:
                    # Find theory block
                    block = TheoryBlock.query.filter_by(task_number=task_number).first()
                    if block:
                        block.content = content
                        updated_count += 1
                        print(f"Updated Task {task_number} with PDF {os.path.basename(pdf_path)}")
                    else:
                        print(f"Block for Task {task_number} not found.")
                else:
                    print(f"Could not determine task number for {os.path.basename(pdf_path)}")
            except Exception as e:
                print(f"Error parsing {pdf_path}: {e}")
                
        db.session.commit()
        print(f"Total blocks updated: {updated_count}")

if __name__ == '__main__':
    parse_pdfs()
