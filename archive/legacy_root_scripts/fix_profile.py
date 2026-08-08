import re

with open('templates/sandbox/profile.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the monolithic flex-col wrapper and return to a flowing flex-1 relative container
content = content.replace(
    '<main class="flex-1 pb-16 flex flex-col mx-auto w-full lg:w-[calc(100%-7.5rem)] ml-auto relative z-10 pt-4 pr-4">',
    '<main class="flex-1 pb-16 mx-auto w-full lg:w-[calc(100%-7.5rem)] ml-auto relative z-10 pt-4 pr-4">'
)

# Fix the Hero Top Banner to flow naturally under the transparent area
content = content.replace(
    '<div class="w-full h-64 lg:h-72 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 relative shrink-0 rounded-[2.5rem] shadow-sm overflow-hidden mb-6">',
    '<div class="w-full h-64 lg:h-72 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 relative shrink-0 rounded-[2.5rem] shadow-sm overflow-hidden mb-0">'
)

with open('templates/sandbox/profile.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Profile fixed!")
