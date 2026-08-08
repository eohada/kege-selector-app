import re

with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace CSS classes for the nav buttons to apply Claymorphism colors 
content = content.replace('.task-nav-btn.nav-correct {', '.nav-correct {\n        background: var(--color-success) !important;\n        border-color: rgba(0, 0, 0, 0.1) !important;\n        color: var(--color-bg-app) !important;\n        box-shadow: 0 4px 12px rgba(34,211,238,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;')
content = content.replace('.task-nav-btn.nav-incorrect {', '.nav-incorrect {\n        background: var(--color-danger) !important;\n        border-color: rgba(0, 0, 0, 0.1) !important;\n        color: #fff !important;\n        box-shadow: 0 4px 12px rgba(251,113,133,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;')
content = content.replace('.task-nav-btn.nav-returned {', '.nav-returned {\n        background: var(--color-warning) !important;\n        border-color: rgba(0, 0, 0, 0.1) !important;\n        color: #fff !important;\n        box-shadow: 0 4px 12px rgba(249,115,22,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;')
content = content.replace('.task-nav-btn.nav-graded {', '.nav-graded {\n        background: var(--color-primary) !important;\n        border-color: rgba(0, 0, 0, 0.1) !important;\n        color: #fff !important;\n        box-shadow: 0 4px 12px rgba(99,102,241,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;')

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(content)
