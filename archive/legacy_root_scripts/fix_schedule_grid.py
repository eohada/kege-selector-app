import re

with open('templates/sandbox/schedule.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Generate 24 hours rows with correct hover classes
rows_html = ""
for hour in range(24):
    time_str = f"{hour:02d}:00"
    rows_html += f"""
                            <!-- {time_str} Row -->
                            <div class="h-[100px] border-b border-slate-200 w-full flex">
                                <div class="w-16 shrink-0 border-r-2 border-slate-200 bg-white text-right pr-3 pt-2 text-[10px] font-bold text-slate-400 shadow-[2px_0_10px_rgba(0,0,0,0.02)] relative z-20">{time_str}</div>
                                <div class="flex-1 grid grid-cols-7 border-0 bg-transparent">
                                    <div class="border-r border-slate-200/80 bg-[#FAFCFF] hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-slate-200/80 bg-white hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-indigo-200 bg-indigo-50/40 hover:bg-indigo-100/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-500 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-slate-200/80 bg-[#FAFCFF] hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-slate-200/80 bg-white hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-slate-200/80 bg-[#FAFCFF] hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="bg-white hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                </div>
                            </div>"""

# Match spacer header to spacer body
header_pattern = r'<!-- Left Time Column Spacer \(Fixed Width\) -->\s*<div class="w-16 shrink-0 border-r-2 border-slate-200 bg-white"></div>'
content = re.sub(header_pattern, r'<!-- Left Time Column Spacer (Fixed Width) -->\n                        <div class="w-16 shrink-0 border-r-2 border-slate-200 bg-white shadow-[2px_0_10px_rgba(0,0,0,0.02)] relative z-20"></div>', content)

# Correct physical positions based on 100px per hour
# 16:30 -> 16.5 * 100 = 1650px
# 17:33 -> 17.55 * 100 = 1755px
content = content.replace('style="top: 220px;"', 'style="top: 1755px;"') 
content = content.replace('top-[50px]', 'top-[1650px]') 
content = content.replace('top-[180px]', 'top-[1755px]')

# Remove static empty slot marker and its massive container
placeholder_pattern = r'<!-- Fri: Empty Slot Marker -->.*?<!-- Sat -->'
content = re.sub(placeholder_pattern, '<!-- Fri --><div class="relative w-full"></div>\n                                <!-- Sat -->', content, flags=re.DOTALL)

# Inject rows
start_marker = "<!-- Dense Grid Background Lines -->\n                        <div class=\"absolute inset-0\">\n"
end_marker = "\n                        </div>\n\n                        <!-- Physical Events Layer (Tactile Cells) -->"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx != -1 and end_idx != -1:
    before_grid = content[:start_idx + len(start_marker)]
    after_grid = content[end_idx:]
    
    new_content = before_grid + rows_html + after_grid
    
    with open('templates/sandbox/schedule.html', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("SUCCESS: Geometry aligned and physical cells updated.")
else:
    print("ERROR: Could not find grid bounds.")
