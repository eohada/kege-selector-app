import os
import glob

# Update all sandbox templates to have a clickable profile link in the sidebar dock
# The profile item is usually the last <div> in the <nav> block carrying the avatar.

search_pattern = r'templates/sandbox/*.html'
files = glob.glob(search_pattern)

old_profile_block = """            <div class="w-full aspect-square rounded-[1rem] border-2 border-slate-200 overflow-hidden cursor-pointer hover:opacity-80 transition-opacity relative group">
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=QAStudent&backgroundColor=e0f2fe" class="w-full h-full object-cover">
                <div class="absolute top-1 right-1 w-2.5 h-2.5 bg-emerald-500 border-2 border-white rounded-full"></div>
            </div>"""
            
new_profile_block = """            <a href="/sandbox/profile" class="w-full aspect-square rounded-[1rem] border-2 border-slate-200 overflow-hidden cursor-pointer hover:border-indigo-300 transition-colors relative group block">
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=QAStudent&backgroundColor=e0f2fe" class="w-full h-full object-cover">
                <div class="absolute inset-0 bg-indigo-500/10 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                <div class="absolute top-1 right-1 w-2.5 h-2.5 bg-emerald-500 border-2 border-white rounded-full"></div>
            </a>"""

teacher_old = """            <div class="w-full aspect-square rounded-[1rem] border-2 border-slate-200 overflow-hidden cursor-pointer hover:opacity-80 transition-opacity relative group">
                {% if role == 'teacher' %}
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=TeacherAdmin&backgroundColor=fef3c7" class="w-full h-full object-cover">
                <div class="absolute top-1 right-1 w-2.5 h-2.5 bg-amber-500 border-2 border-white rounded-full"></div>
                {% else %}
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=QAStudent&backgroundColor=e0f2fe" class="w-full h-full object-cover">
                <div class="absolute top-1 right-1 w-2.5 h-2.5 bg-emerald-500 border-2 border-white rounded-full"></div>
                {% endif %}
            </div>"""

teacher_new = """            <a href="/sandbox/profile" class="w-full aspect-square rounded-[1rem] border-2 border-slate-200 overflow-hidden cursor-pointer hover:border-indigo-300 transition-colors relative group block">
                {% if role == 'teacher' %}
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=TeacherAdmin&backgroundColor=fef3c7" class="w-full h-full object-cover">
                <div class="absolute top-1 right-1 w-2.5 h-2.5 bg-amber-500 border-2 border-white rounded-full"></div>
                {% else %}
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=QAStudent&backgroundColor=e0f2fe" class="w-full h-full object-cover">
                <div class="absolute top-1 right-1 w-2.5 h-2.5 bg-emerald-500 border-2 border-white rounded-full"></div>
                {% endif %}
                <div class="absolute inset-0 bg-indigo-500/10 opacity-0 group-hover:opacity-100 transition-opacity"></div>
            </a>"""
            
teacher_dashboard_old = """            <div class="w-full aspect-square rounded-[1rem] border-2 border-slate-200 overflow-hidden cursor-pointer hover:opacity-80 transition-opacity relative">
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=TeacherAdmin&backgroundColor=fef3c7" class="w-full h-full object-cover">
                <div class="absolute top-1 right-1 w-2.5 h-2.5 bg-amber-500 border-2 border-white rounded-full"></div>
            </div>"""
            
teacher_dashboard_new = """            <a href="/sandbox/profile" class="w-full aspect-square rounded-[1rem] border-2 border-slate-200 overflow-hidden cursor-pointer hover:border-indigo-300 transition-colors relative block group">
                <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=TeacherAdmin&backgroundColor=fef3c7" class="w-full h-full object-cover">
                <div class="absolute top-1 right-1 w-2.5 h-2.5 bg-amber-500 border-2 border-white rounded-full"></div>
                <div class="absolute inset-0 bg-indigo-500/10 opacity-0 group-hover:opacity-100 transition-opacity"></div>
            </a>"""

for file_path in files:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    modified = False
    if old_profile_block in content:
        content = content.replace(old_profile_block, new_profile_block)
        modified = True
    elif teacher_old in content:
        content = content.replace(teacher_old, teacher_new)
        modified = True
    elif teacher_dashboard_old in content:
        content = content.replace(teacher_dashboard_old, teacher_dashboard_new)
        modified = True
        
    if modified:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated profile link in {file_path}")
