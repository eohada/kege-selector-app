const fs = require('fs');
let content = fs.readFileSync('templates/base.html', 'utf8');

// Исправим "сломанный навбар" с черным градиентом
// Проблема в стилях .htmx-indicator, которые зачем-то используют жесткие градиенты. НО, вероятнее всего, проблема в _dock_nav.html
let dockContent = fs.readFileSync('templates/_dock_nav.html', 'utf8');
dockContent = dockContent.replace(/bg-zinc-950/g, 'bg-[var(--color-bg-app)]');
dockContent = dockContent.replace(/text-zinc-100/g, 'text-[var(--color-text-primary)]');
dockContent = dockContent.replace(/dark:bg-slate-900/g, '');
dockContent = dockContent.replace(/border-white\/10/g, 'border-[var(--color-stroke)]');
fs.writeFileSync('templates/_dock_nav.html', dockContent);

