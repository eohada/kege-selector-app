import re

with open('templates/sandbox/schedule.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update Calendar Header (Days)
header_pattern = r'<!-- Calendar Header \(Days - Fixed 7 cols strict layout\) -->.*?</div>\s*</div>'

new_header = """<!-- Calendar Header (Days - Fixed 7 cols strict layout) -->
                    <div class="sticky top-0 z-40 flex border-b-2 border-slate-200 bg-[#F4F7FA]">
                        <!-- Left Time Column Spacer (Fixed Width) -->
                        <div class="w-16 shrink-0 border-r-2 border-slate-200 bg-white shadow-[2px_0_10px_rgba(0,0,0,0.02)] relative z-20"></div>
                        
                        <!-- 7 Days Container strictly forcing 1 row -->
                        <div class="flex-1 grid grid-cols-7 w-full">
                            <div class="col-span-1 text-center py-4 border-r border-slate-200">
                                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">ПН</p>
                                <h3 class="text-lg font-black text-slate-800">12</h3>
                            </div>
                            <div class="col-span-1 text-center py-4 border-r border-slate-200">
                                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">ВТ</p>
                                <h3 class="text-lg font-black text-slate-800">13</h3>
                            </div>
                            <!-- Active Day Highlight -->
                            <div class="col-span-1 text-center py-4 border-r border-indigo-200 bg-indigo-50/40 relative border-t-4 border-t-indigo-600">
                                <p class="text-[10px] font-bold text-indigo-500 uppercase tracking-widest mb-1">СР</p>
                                <h3 class="text-lg font-black text-indigo-700">14</h3>
                                <div class="w-1.5 h-1.5 bg-indigo-500 rounded-full mx-auto mt-1"></div>
                            </div>
                            <div class="col-span-1 text-center py-4 border-r border-slate-200 bg-white shadow-[-5px_0_15px_-5px_rgba(0,0,0,0.03)]">
                                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">ЧТ</p>
                                <h3 class="text-lg font-black text-slate-800">15</h3>
                            </div>
                            <div class="col-span-1 text-center py-4 border-r border-slate-200">
                                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">ПТ</p>
                                <h3 class="text-lg font-black text-slate-800">16</h3>
                            </div>
                            <div class="col-span-1 text-center py-4 border-r border-slate-200 bg-rose-50/40 text-rose-900">
                                <p class="text-[10px] font-bold text-rose-400 uppercase tracking-widest mb-1">СБ</p>
                                <h3 class="text-lg font-black text-rose-800">17</h3>
                            </div>
                            <div class="col-span-1 text-center py-4 bg-rose-50/40 text-rose-900">
                                <p class="text-[10px] font-bold text-rose-400 uppercase tracking-widest mb-1">ВС</p>
                                <h3 class="text-lg font-black text-rose-800">18</h3>
                            </div>
                        </div>
                    </div>"""

content = re.sub(header_pattern, new_header, content, flags=re.DOTALL)

# 2. Update Calendar Body Grid
rows_html = ""
for hour in range(24):
    time_str = f"{hour:02d}:00"
    rows_html += f"""
                            <!-- {time_str} Row -->
                            <div class="h-[100px] border-b border-slate-200 w-full flex">
                                <div class="w-16 shrink-0 border-r-2 border-slate-200 bg-white text-right pr-3 pt-2 text-[10px] font-bold text-slate-400 shadow-[2px_0_10px_rgba(0,0,0,0.02)] relative z-20">{time_str}</div>
                                <div class="flex-1 grid grid-cols-7 border-0 bg-transparent">
                                    <div class="border-r border-slate-200 bg-[#FAFCFF] hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-slate-200 bg-white hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-indigo-200 bg-indigo-50/20 hover:bg-indigo-100/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-500 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-slate-200 bg-[#FAFCFF] hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-slate-200 bg-white hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="border-r border-slate-200 bg-[#FAFCFF] hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                    <div class="bg-white hover:bg-indigo-50/60 cursor-pointer transition-colors group relative"><div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><span class="text-indigo-400 font-bold text-xs flex items-center gap-1"><i class="ph-bold ph-plus"></i> Запланировать</span></div></div>
                                </div>
                            </div>"""

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
    print("SUCCESS: Header and Grid aligned with identical borders.")
else:
    print("ERROR: Could not find grid bounds.")
