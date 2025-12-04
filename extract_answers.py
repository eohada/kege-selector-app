#!/usr/bin/env python3
"""
Скрипт для извлечения ответов из существующих заданий в базе данных.
Открывает каждое задание отдельно и извлекает ответ.
"""

import os
import sys
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import time

# Добавляем корневую директорию в путь
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from app import app, db
from core.db_models import Tasks, moscow_now

# Импорт ObjectDeletedError для разных версий SQLAlchemy
try:
    from sqlalchemy.orm.exc import ObjectDeletedError
except ImportError:
    from sqlalchemy.exc import ObjectDeletedError

SITE_DOMAIN = "https://kompege.ru"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"

def extract_answer_from_page(page, task_url):
    """Извлекает ответ со страницы задания"""
    try:
        page.goto(task_url, wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(3000)  # Увеличиваем ожидание для полной загрузки
        
        answer = ''
        
        # Ждем появления кнопки "показать ответ" (может загружаться динамически)
        try:
            # Пытаемся дождаться появления кнопки
            page.wait_for_selector('button, a', timeout=5000)
        except:
            pass
        
        page.wait_for_timeout(1000)
        
        # Ищем элемент "Показать ответ" - это span с классом link
        button_locator = None
        button_found = False
        
        # Пробуем найти через селекторы (span.link с текстом "Показать ответ")
        button_selectors = [
            'span.link:has-text("Показать ответ")',
            'span.link:has-text("показать ответ")',
            'span:has-text("Показать ответ")',
            'span:has-text("показать ответ")',
            'button:has-text("Показать ответ")',
            'button:has-text("показать ответ")',
            'a:has-text("Показать ответ")',
            'a:has-text("показать ответ")',
            '*:has-text("Показать ответ")',
            '*:has-text("показать ответ")'
        ]
        
        for selector in button_selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() > 0:
                    button_locator = locator
                    button_found = True
                    break
            except:
                continue
        
        # Если не нашли через селекторы, ищем через текст всех элементов (особенно span)
        if not button_found:
            try:
                # Сначала ищем span элементы
                all_spans = page.locator('span').all()
                for el in all_spans:
                    try:
                        text = el.inner_text(timeout=1000).lower().strip()
                        if 'показать' in text and 'ответ' in text:
                            button_locator = el
                            button_found = True
                            break
                    except:
                        continue
                
                # Если не нашли в span, ищем в других элементах
                if not button_found:
                    all_elements = page.locator('button, a, div').all()
                    for el in all_elements:
                        try:
                            text = el.inner_text(timeout=1000).lower().strip()
                            if 'показать' in text and 'ответ' in text:
                                button_locator = el
                                button_found = True
                                break
                        except:
                            continue
            except:
                pass
        
        # Отладочная информация
        if not button_found:
            # Проверяем через JavaScript, есть ли кнопка
            check_result = page.evaluate("""
                () => {
                    const elements = Array.from(document.querySelectorAll('button, a, span, div'));
                    for (const el of elements) {
                        const text = (el.textContent || el.innerText || '').toLowerCase().trim();
                        if (text.includes('показать') && text.includes('ответ')) {
                            return { found: true, text: (el.textContent || el.innerText || '').trim() };
                        }
                    }
                    return { found: false };
                }
            """)
            if check_result.get('found'):
                print(f"  [DEBUG] Кнопка найдена через JS, но не через locator. Текст: {check_result.get('text', '')[:40]}")
            else:
                print(f"  [DEBUG] Кнопка не найдена даже через JS")
        
        if button_found and button_locator:
            try:
                # Прокручиваем к кнопке
                button_locator.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                
                # Нажимаем на кнопку
                button_locator.click(timeout=5000)
                page.wait_for_timeout(2500)  # Увеличиваем ожидание для появления ответа
                
                # Ищем следующий элемент после кнопки
                # Используем более надежный метод - находим кнопку через JS и берем следующий элемент
                answer = page.evaluate("""
                    () => {
                        // Находим элемент "Показать ответ" (обычно это span с классом link)
                        // Сначала ищем span.link
                        const allSpans = Array.from(document.querySelectorAll('span.link, span'));
                        let btn = null;
                        
                        for (const el of allSpans) {
                            const text = (el.textContent || el.innerText || '').toLowerCase().trim();
                            if (text.includes('показать') && text.includes('ответ')) {
                                btn = el;
                                break;
                            }
                        }
                        
                        // Если не нашли в span, ищем в других элементах
                        if (!btn) {
                            const allElements = Array.from(document.querySelectorAll('button, a, div'));
                            for (const el of allElements) {
                                const text = (el.textContent || el.innerText || '').toLowerCase().trim();
                                if (text.includes('показать') && text.includes('ответ')) {
                                    btn = el;
                                    break;
                                }
                            }
                        }
                        
                        if (!btn) return '';
                        
                        // Ищем следующий элемент после кнопки - пробуем разные способы
                        let next = btn.nextElementSibling;
                        
                        // Способ 1: nextElementSibling
                        if (next && next.textContent && next.textContent.trim().length > 0) {
                            const text = next.textContent.trim();
                            const lines = text.split('\\n').filter(l => l.trim());
                            if (lines.length > 0 && lines[0].length > 0) {
                                return lines[0].trim();
                            }
                        }
                        
                        // Способ 2: следующий элемент в родителе
                        const parent = btn.parentElement;
                        if (parent) {
                            const children = Array.from(parent.children);
                            const index = children.indexOf(btn);
                            if (index >= 0 && index < children.length - 1) {
                                next = children[index + 1];
                                if (next && next.textContent) {
                                    const text = next.textContent.trim();
                                    const lines = text.split('\\n').filter(l => l.trim());
                                    if (lines.length > 0 && lines[0].length > 0) {
                                        return lines[0].trim();
                                    }
                                }
                            }
                        }
                        
                        // Способ 3: следующий текстовый узел
                        let node = btn.nextSibling;
                        while (node) {
                            if (node.nodeType === 1) { // Element
                                const text = (node.textContent || node.innerText || '').trim();
                                if (text && text.length > 0) {
                                    const lines = text.split('\\n').filter(l => l.trim());
                                    if (lines.length > 0) {
                                        return lines[0].trim();
                                    }
                                    return text;
                                }
                            } else if (node.nodeType === 3) { // Text node
                                const text = node.textContent.trim();
                                if (text && text.length > 0) {
                                    return text.split('\\n')[0].trim();
                                }
                            }
                            node = node.nextSibling;
                        }
                        
                        return '';
                    }
                """)
                        
            except Exception as e:
                print(f"  [ERROR] Ошибка при клике на кнопку: {e}")
        
        if answer:
            # Очищаем от лишнего текста
            answer = answer.strip()
            # Удаляем "Ответ:" в начале, если есть
            answer = re.sub(r'^[Оо]твет[:\s]*', '', answer, flags=re.IGNORECASE).strip()
            if answer and len(answer) > 0:
                return answer
        
        return ''
        
    except Exception as e:
        print(f"  [ERROR] Ошибка при извлечении ответа: {e}")
        return ''

def main():
    """Основная функция извлечения ответов"""
    print("\n" + "="*60)
    print("ИЗВЛЕЧЕНИЕ ОТВЕТОВ ИЗ ЗАДАНИЙ")
    print("="*60)
    print(f"Время начала: {moscow_now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    with app.app_context():
        # Получаем все задания без ответов или с пустыми ответами
        # Используем order_by для стабильного порядка и получаем только ID
        task_ids = db.session.query(Tasks.task_id).filter(
            (Tasks.answer == None) | (Tasks.answer == '')
        ).order_by(Tasks.task_id).all()
        
        task_ids = [tid[0] for tid in task_ids]
        total_tasks = len(task_ids)
        print(f"Найдено заданий без ответов: {total_tasks}\n")
        
        if total_tasks == 0:
            print("Все задания уже имеют ответы!")
            return
        
        stealth = Stealth()
        with stealth.use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            
            updated_count = 0
            error_count = 0
            skipped_count = 0
            
            for idx, task_id in enumerate(task_ids, 1):
                try:
                    # Перезагружаем задание из базы на каждой итерации
                    task = db.session.get(Tasks, task_id)
                    
                    # Проверяем, что задание существует и еще не имеет ответа
                    if not task:
                        print(f"[{idx}/{total_tasks}] Пропущено: задание {task_id} не найдено в базе")
                        skipped_count += 1
                        continue
                    
                    # Проверяем, не появился ли ответ с момента начала скрипта
                    if task.answer and task.answer.strip():
                        print(f"[{idx}/{total_tasks}] Пропущено: задание {task_id} уже имеет ответ")
                        skipped_count += 1
                        continue
                    
                    if not task.source_url:
                        print(f"[{idx}/{total_tasks}] Пропущено: нет URL для задания {task_id}")
                        skipped_count += 1
                        continue
                    
                    print(f"[{idx}/{total_tasks}] Обработка задания {task_id} (№{task.site_task_id or task_id})...")
                    print(f"  URL: {task.source_url}")
                    
                    answer = extract_answer_from_page(page, task.source_url)
                    
                    if answer:
                        # Перезагружаем задание перед обновлением (на случай изменений)
                        db.session.refresh(task)
                        task.answer = answer
                        task.last_scraped = moscow_now()
                        db.session.commit()
                        updated_count += 1
                        print(f"  [OK] Ответ извлечен: {answer[:50]}...")
                    else:
                        error_count += 1
                        print(f"  [WARN] Ответ не найден")
                    
                    # Задержка между запросами
                    if idx < total_tasks:
                        time.sleep(2)  # 2 секунды между запросами
                        
                except ObjectDeletedError:
                    print(f"[{idx}/{total_tasks}] Пропущено: задание {task_id} было удалено из базы")
                    skipped_count += 1
                    db.session.rollback()
                    continue
                except Exception as e:
                    print(f"[{idx}/{total_tasks}] Ошибка при обработке задания {task_id}: {e}")
                    error_count += 1
                    db.session.rollback()
                    # Продолжаем работу со следующим заданием
                    continue
            
            browser.close()
            
            print("\n" + "="*60)
            print("ИЗВЛЕЧЕНИЕ ЗАВЕРШЕНО")
            print("="*60)
            print(f"Всего заданий в очереди: {total_tasks}")
            print(f"Ответов извлечено: {updated_count}")
            print(f"Пропущено (уже есть ответ/удалено): {skipped_count}")
            print(f"Ошибок: {error_count}")
            print(f"Время окончания: {moscow_now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    import re
    main()

