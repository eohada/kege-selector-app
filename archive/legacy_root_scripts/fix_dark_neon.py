import re

with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Убираем радиоактивное свечение у кнопок тасок в 사이дбаре и основной контенте
# Для primary
content = content.replace("!shadow-[0_4px_12px_rgba(79,70,229,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)]", "!shadow-[0_4px_12px_rgba(79,70,229,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-2px_0_rgba(0,0,0,0.3)]")
content = content.replace("active:!shadow-[inset_0_4px_8px_rgba(79,70,229,0.3)]", "active:!shadow-[inset_0_4px_8px_rgba(79,70,229,0.3)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]")

# Для success
content = content.replace("!shadow-[0_4px_12px_rgba(34,211,238,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)]", "!shadow-[0_4px_12px_rgba(34,211,238,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-2px_0_rgba(0,0,0,0.3)]")
content = content.replace("active:!shadow-[inset_0_4px_8px_rgba(34,197,94,0.4)]", "active:!shadow-[inset_0_4px_8px_rgba(34,197,94,0.4)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]")
content = content.replace("active:!shadow-[inset_0_4px_8px_rgba(34,197,94,0.3)]", "active:!shadow-[inset_0_4px_8px_rgba(34,197,94,0.3)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]")

# Для danger
content = content.replace("!shadow-[0_4px_12px_rgba(251,113,133,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)]", "!shadow-[0_4px_12px_rgba(251,113,133,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-2px_0_rgba(0,0,0,0.3)]")
content = content.replace("active:!shadow-[inset_0_4px_8px_rgba(239,68,68,0.3)]", "active:!shadow-[inset_0_4px_8px_rgba(239,68,68,0.3)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]")

# Для warning
content = content.replace("!shadow-[0_4px_12px_rgba(245,158,11,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)]", "!shadow-[0_4px_12px_rgba(245,158,11,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-2px_0_rgba(0,0,0,0.3)]")
content = content.replace("active:!shadow-[inset_0_4px_8px_rgba(245,158,11,0.3)]", "active:!shadow-[inset_0_4px_8px_rgba(245,158,11,0.3)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]")

# Убираем "грязь" (текстовую тень или странную обводку) вокруг главного заголовка "Введение в Claymorphism", если она есть (в нашем случае ее давал сам цвет текста, можно добавить drop-shadow-none для темной темы на всякий случай)
content = content.replace("text-4xl md:text-5xl font-black mb-6 leading-tight text-[var(--color-text-primary)]", "text-4xl md:text-5xl font-black mb-6 leading-tight text-[var(--color-text-primary)] dark:drop-shadow-none")

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(content)
