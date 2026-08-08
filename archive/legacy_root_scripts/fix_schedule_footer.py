import re

with open('templates/sandbox/schedule.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update Scroll area height
content = content.replace('h-[520px] max-h-[520px] overflow-y-auto', 'flex-1 h-full overflow-y-auto')

# 2. Fix the Header column
content = re.sub(
    r'<div class="col-span-1 text-center py-4 border-r border-slate-200">\s*<p class="text-\[10px\] font-bold text-slate-400 uppercase tracking-widest mb-1">ВТ</p>\s*<h3 class="text-lg font-black text-slate-800">13</h3>\s*</div>',
    '<div class="col-span-1 text-center py-4 border-none">\n                                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">ВТ</p>\n                                <h3 class="text-lg font-black text-slate-800">13</h3>\n                            </div>',
    content
)

content = re.sub(
    r'<!-- Active Day Highlight -->\s*<div class="col-span-1 text-center py-4 border-r border-indigo-200 bg-indigo-50 shadow-inner relative">\s*<div class="absolute top-0 left-0 w-full h-1 bg-indigo-500"></div>\s*<p class="text-\[10px\] font-bold text-indigo-500 uppercase tracking-widest mb-1">СР</p>\s*<h3 class="text-lg font-black text-indigo-700">14</h3>\s*<div class="w-1\.5 h-1\.5 bg-indigo-500 rounded-full mx-auto mt-1"></div>\s*</div>',
    '<!-- Active Day Highlight -->\n                            <div class="col-span-1 text-center py-4 border-x-2 border-indigo-200 bg-indigo-50/30 relative">\n                                <div class="absolute top-0 left-0 w-full h-1 bg-indigo-500"></div>\n                                <div class="absolute -bottom-[2px] left-0 w-full h-[3px] bg-indigo-50/30 z-50"></div> <!-- covers bottom border -->\n                                <p class="text-[10px] font-bold text-indigo-600 uppercase tracking-widest mb-1">СР</p>\n                                <h3 class="text-lg font-black text-indigo-800">14</h3>\n                                <div class="w-1.5 h-1.5 bg-indigo-500 rounded-full mx-auto mt-1"></div>\n                            </div>',
    content
)

# 3. Fix the Body columns for Wednesday (CP 14) 
# First, remove `border-r` from the 2nd cell (Tue)
content = content.replace(
    '<div class="border-r border-slate-200/80 bg-white hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>',
    '<div class="border-none bg-white hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>'
)

# Then, make the 3rd cell (Wed) have border-x-2 and correct bg
content = content.replace(
    '<div class="border-r border-indigo-200 bg-indigo-50/40 hover:bg-indigo-100/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-500 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>',
    '<div class="border-x-2 border-indigo-200 bg-indigo-50/30 hover:bg-indigo-100/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-600 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>'
)

with open('templates/sandbox/schedule.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Grid and footer spaces fixed!")
