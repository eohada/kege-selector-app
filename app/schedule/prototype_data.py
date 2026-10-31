"""
BooStudy — Student Schedule: Experience Rebirth (Phase 0)
Isolated Synthetic Data Provider for Design Prototypes
Supports 5 realistic testing scenarios:
1. Standard Week (2 lessons, 1 homework, 1 material, tutor note)
2. Single Lesson Week (1 lesson on Tuesday, rest free — tests column balance & voids)
3. Multi-Event Day (2 lessons with different tutors + homework deadline + practice)
4. Empty Week (0 lessons — vacation / catch-up week with Boo Mascot)
5. Long Titles & Stress (German compound words, long topics, hyphens test)
"""
from datetime import datetime, timedelta

def get_prototype_data(scenario: str = 'standard', week_offset: int = 0, selected_day_index: int = None) -> dict:
    scenario = (scenario or 'standard').lower()

    # Base dates around a reference Monday
    ref_monday = datetime(2026, 10, 26) + timedelta(weeks=week_offset)
    days_data = []

    day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    short_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    # Common teacher personas (for realistic UX testing)
    teacher_informatics = {
        'name': 'Виктор Сергеевич',
        'full_name': 'Виктор Сергеевич Белов',
        'role': 'Тьютор по информатике',
        'avatar': '/static/images/schedule/mock_teacher_avatar.png',
        'subject': 'Информатика ЕГЭ',
        'rating': '4.98',
        'tag': 'Эксперт ЕГЭ'
    }
    teacher_math = {
        'name': 'Елена Дмитриевна',
        'full_name': 'Елена Дмитриевна Орлова',
        'role': 'Тьютор по профильной математике',
        'avatar': '/static/images/default-avatar.svg',
        'subject': 'Математика Профиль',
        'rating': '4.95',
        'tag': 'Старший методист'
    }

    # Generate 7 days skeleton
    for idx in range(7):
        cur_date = ref_monday + timedelta(days=idx)
        days_data.append({
            'day_index': idx,
            'day_name': day_names[idx],
            'short_name': short_names[idx],
            'date': f"{cur_date.day} {['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек'][cur_date.month - 1]}",
            'full_date': cur_date.strftime('%Y-%m-%d'),
            'is_today': (idx == 1 and week_offset == 0), # Вторник 27 окт — условное "сегодня"
            'is_completed': (idx < 1 and week_offset == 0),
            'events_count': 0,
            'events': [],
            'main_event': None
        })

    # SCENARIOS SETUP
    if scenario == 'standard':
        default_selected = 1 if selected_day_index is None else selected_day_index
        # Пн (0): завершенный урок
        days_data[0]['events'] = [{
            'id': 'ev_mon_1',
            'type': 'lesson',
            'status': 'conducted',
            'badge': 'Проведено',
            'subject': 'Информатика ЕГЭ',
            'title': 'Основы графов и матриц смежности • Задание 1',
            'time_str': '16:00 – 17:30',
            'duration': 90,
            'teacher': teacher_informatics,
            'room_url': '#',
            'action_label': 'Конспект урока',
            'secondary_url': '#',
            'secondary_label': 'Запись видео',
            'materials': [{'title': 'Конспект урока и разбор графов.pdf', 'size': '2.1 MB', 'type': 'pdf'}],
            'notes': 'Ученик уверенно строит таблицы соответствия, но стоит закрепить симметричные графы.'
        }]
        # Вт (1) - Сегодня: предстоящий урок
        days_data[1]['events'] = [{
            'id': 'ev_tue_1',
            'type': 'lesson',
            'status': 'planned',
            'is_urgent': True,
            'badge': 'Сегодня в 18:00',
            'subject': 'Информатика ЕГЭ',
            'title': 'Динамическое программирование • Задание 27',
            'time_str': '18:00 – 19:30',
            'duration': 90,
            'countdown_text': 'Через 2 ч 45 мин',
            'teacher': teacher_informatics,
            'room_url': '/lessons/room/demo',
            'action_label': 'Войти в урок →',
            'secondary_url': '/theory',
            'secondary_label': 'Теория к теме',
            'materials': [
                {'title': 'Шаблон кода Python (27_template.py)', 'size': '12 KB', 'type': 'code'},
                {'title': 'Справочник алгоритмов ЕГЭ.pdf', 'size': '1.8 MB', 'type': 'pdf'}
            ],
            'notes': 'Повтори срезы списков и алгоритм поиска максимума на суффиксе перед уроком.'
        }, {
            'id': 'ev_tue_hw',
            'type': 'homework',
            'status': 'pending',
            'badge': 'Дедлайн 23:59',
            'subject': 'Информатика ЕГЭ',
            'title': 'Домашняя работа: 10 задач по теории графов',
            'time_str': 'до 23:59',
            'action_label': 'Сдать работу →',
            'action_url': '/assignments/demo',
            'homework_desc': 'Решить оставшиеся 4 задачи из подборки. Проверить ответы через автотестер.'
        }]
        # Чт (3): дедлайн ДЗ
        days_data[3]['events'] = [{
            'id': 'ev_thu_hw',
            'type': 'homework',
            'status': 'pending',
            'badge': 'Дедлайн через 2 дня',
            'subject': 'Информатика ЕГЭ',
            'title': 'Контрольное тестирование: Динамика и делимость',
            'time_str': 'до 20:00',
            'action_label': 'Открыть тест →',
            'action_url': '/assignments/demo_test'
        }]
        # Пт (4): урок
        days_data[4]['events'] = [{
            'id': 'ev_fri_1',
            'type': 'lesson',
            'status': 'planned',
            'badge': 'Пятница в 17:00',
            'subject': 'Информатика ЕГЭ',
            'title': 'Теория игр с одной и двумя кучами камней • Задания 19–21',
            'time_str': '17:00 – 18:30',
            'duration': 90,
            'teacher': teacher_informatics,
            'room_url': '/lessons/room/demo',
            'action_label': 'Войти в урок →',
            'secondary_url': '/theory',
            'secondary_label': 'Таблицы исходов'
        }]

    elif scenario == 'single_lesson':
        default_selected = 1 if selected_day_index is None else selected_day_index
        # Только 1 урок во всей неделе — вторник
        days_data[1]['events'] = [{
            'id': 'ev_tue_single',
            'type': 'lesson',
            'status': 'planned',
            'is_urgent': True,
            'badge': 'Единственный урок недели',
            'subject': 'Математика Профиль',
            'title': 'Планиметрия: окружности и вписанные четырёхугольники',
            'time_str': '17:00 – 18:30',
            'duration': 90,
            'countdown_text': 'Сегодня в 17:00',
            'teacher': teacher_math,
            'room_url': '/lessons/room/demo_math',
            'action_label': 'Войти в урок →',
            'secondary_url': '/theory',
            'secondary_label': 'Формулы планиметрии',
            'materials': [{'title': 'Теоремы о касательных и секущих.pdf', 'size': '3.4 MB', 'type': 'pdf'}],
            'notes': 'Приготовь циркуль и чистую тетрадь в клетку.'
        }]

    elif scenario == 'multi_event':
        default_selected = 1 if selected_day_index is None else selected_day_index
        # Плотный день во вторник: 2 урока разных учителей + дедлайн + пробник
        days_data[1]['events'] = [
            {
                'id': 'ev_tue_multi_1',
                'type': 'lesson',
                'status': 'planned',
                'badge': 'Урок 1 • 15:00',
                'subject': 'Математика Профиль',
                'title': 'Тригонометрические уравнения с отбором корней • Задание 13',
                'time_str': '15:00 – 16:30',
                'duration': 90,
                'countdown_text': 'Через 1 ч 15 мин',
                'teacher': teacher_math,
                'room_url': '/lessons/room/demo_math',
                'action_label': 'Войти в урок →',
                'secondary_url': '/theory',
                'secondary_label': 'Тригонометрический круг',
                'materials': [{'title': 'Шпаргалка: отбор корней на окружности.pdf', 'size': '1.2 MB', 'type': 'pdf'}],
                'notes': 'Разберём 5 реальных прототипов ЕГЭ 2026 года.'
            },
            {
                'id': 'ev_tue_multi_2',
                'type': 'lesson',
                'status': 'planned',
                'badge': 'Урок 2 • 17:00',
                'subject': 'Информатика ЕГЭ',
                'title': 'Электронные таблицы и поиск экстремумов • Задание 9',
                'time_str': '17:00 – 18:30',
                'duration': 90,
                'teacher': teacher_informatics,
                'room_url': '/lessons/room/demo_info',
                'action_label': 'Войти в урок →',
                'secondary_url': '/theory',
                'secondary_label': 'Функции Excel/Calc',
                'materials': [{'title': 'Набор файлов CSV и XLSX к уроку.zip', 'size': '4.8 MB', 'type': 'code'}],
                'notes': 'Убедись, что на компьютере открывается LibreOffice Calc или Excel.'
            },
            {
                'id': 'ev_tue_multi_hw',
                'type': 'homework',
                'status': 'pending',
                'badge': 'Срочный дедлайн',
                'subject': 'Информатика ЕГЭ',
                'title': 'ДЗ: Компьютерная проверка гипотез в задаче 24',
                'time_str': 'до 21:00',
                'action_label': 'Сдать работу →',
                'action_url': '/assignments/hw_24',
                'homework_desc': 'Написать скрипт на Python для поиска максимальной длины подстроки.'
            },
            {
                'id': 'ev_tue_multi_quiz',
                'type': 'practice',
                'status': 'pending',
                'badge': 'Экспресс-тренинг',
                'subject': 'BooStudy Тренажёр',
                'title': 'Мини-тест по теории вероятностей (10 минут)',
                'time_str': 'в удобное время',
                'action_label': 'Пройти тест →',
                'action_url': '/trainer/quiz'
            }
        ]
        # Четверг: ещё один урок
        days_data[3]['events'] = [{
            'id': 'ev_thu_multi_3',
            'type': 'lesson',
            'status': 'planned',
            'badge': '16:00',
            'subject': 'Информатика ЕГЭ',
            'title': 'Рекурсивные функции и мемоизация • Задание 16',
            'time_str': '16:00 – 17:30',
            'duration': 90,
            'teacher': teacher_informatics,
            'room_url': '/lessons/room/demo_info',
            'action_label': 'Войти в урок →'
        }]

    elif scenario == 'empty_week':
        default_selected = 1 if selected_day_index is None else selected_day_index
        # Все 7 дней абсолютно свободны (каникулы)
        for d in days_data:
            d['events'] = []

    elif scenario == 'long_titles':
        default_selected = 1 if selected_day_index is None else selected_day_index
        # Стресс-тест длинных строк, переносов, сложных названий
        days_data[1]['events'] = [
            {
                'id': 'ev_tue_long_1',
                'type': 'lesson',
                'status': 'planned',
                'is_urgent': True,
                'badge': 'Спецкурс углублённой подготовки к олимпиадам и ЕГЭ',
                'subject': 'Высокопроизводительные алгоритмы и структуры данных на языке программирования Python',
                'title': 'Сложные графовые модели с динамической верификацией циклов отрицательного веса и алгоритм Беллмана-Форда-Мура-Дейкстры с оптимизацией Фибоначчиевой кучи',
                'time_str': '17:00 – 19:15',
                'duration': 135,
                'countdown_text': 'Через 1 ч 40 мин',
                'teacher': {
                    'name': 'Константин-Александр Владиславович',
                    'full_name': 'Константин-Александр Владиславович Преображенский-Стародубцев',
                    'role': 'Главный научный консультант и ведущий методист направления олимпиадной информатики',
                    'avatar': '/static/images/schedule/mock_teacher_avatar.png',
                    'subject': 'Информатика и олимпиадное программирование',
                    'rating': '5.00',
                    'tag': 'Победитель всероса'
                },
                'room_url': '/lessons/room/stress',
                'action_label': 'Подключиться к интерактивной видеоконференции высокого разрешения →',
                'secondary_url': '/theory/stress',
                'secondary_label': 'Открыть фундаментальный научно-теоретический справочник',
                'materials': [
                    {'title': 'Donaudampfschifffahrtselektrizitätenhauptbetriebswerkbauunterbeamtengesellschaft_Manual_v4.2.1.pdf', 'size': '18.4 MB', 'type': 'pdf'},
                    {'title': 'Очень_длинное_название_исходного_файла_программы_для_проверки_асимптотики_вычислений_без_пробелов_в_названии_2026.py', 'size': '45 KB', 'type': 'code'}
                ],
                'notes': 'Необходимо_внимательно_изучить_каждую_деталь_исходного_кода_перед_началом_онлайн_занятия_без_пропусков_и_невнимательности.'
            },
            {
                'id': 'ev_tue_long_hw',
                'type': 'homework',
                'status': 'pending',
                'badge': 'Обязательное практическое контрольное домашнее задание',
                'subject': 'Алгоритмы оптимизации',
                'title': 'Самостоятельная_исследовательская_работа_по_построению_оптимального_маршрута_на_ориентированном_мультиграфе_с_ограничениями',
                'time_str': 'строго до 23:59:59',
                'action_label': 'Отправить выполненную работу на автоматизированную проверку кода →',
                'action_url': '/assignments/stress',
                'homework_desc': 'Написать программу с доказанной временной сложностью O(V*log(E)) и минимальным потреблением оперативной памяти.'
            }
        ]

    # Calculate events counts and main event
    for d in days_data:
        d['events_count'] = len(d['events'])
        d['main_event'] = d['events'][0] if d['events'] else None

    # Global weekly stats calculation
    total_conducted = sum(1 for d in days_data for e in d['events'] if e.get('status') == 'conducted')
    total_planned = sum(1 for d in days_data for e in d['events'] if e.get('type') == 'lesson' and e.get('status') == 'planned')
    total_hw = sum(1 for d in days_data for e in d['events'] if e.get('type') == 'homework' and e.get('status') != 'completed')
    total_lessons = total_conducted + total_planned
    percent = int((total_conducted / total_lessons * 100)) if total_lessons > 0 else 0

    # Collect all materials across week
    all_materials = []
    seen_mat = set()
    for d in days_data:
        for ev in d['events']:
            for m in ev.get('materials', []):
                if m['title'] not in seen_mat:
                    seen_mat.add(m['title'])
                    all_materials.append(m)

    # General tutor notes
    notes_general = ""
    if scenario == 'standard':
        notes_general = "Виктор Сергеевич: «Отличный прогресс в первой части КЕГЭ. На этой неделе делаем упор на динамику №27. Не забывай про тесты эффективности!»"
    elif scenario == 'multi_event':
        notes_general = "Елена Дмитриевна: «Сегодня плотный день с двумя предметами. Сделай 30-минутный перерыв между математикой и информатикой, чтобы не перегружать внимание.»"
    elif scenario == 'single_lesson':
        notes_general = "Елена Дмитриевна: «На этой неделе один планиметрический урок — удели максимум времени разбору чертежей и теореме о вписанном угле.»"
    elif scenario == 'empty_week':
        notes_general = "Маскот Бу: «На этой неделе нет запланированных уроков. Самое время набраться сил, повторить сложные формулы или порешать задачи в тренажёре!»"
    elif scenario == 'long_titles':
        notes_general = "Преподавательский состав: «Внимание к деталям в формулировках — ключ к максимальным баллам на экзамене.»"

    # Current active day
    sel_day_idx = max(0, min(6, default_selected))
    selected_day = days_data[sel_day_idx]

    # Next immediate lesson across the whole week (for Command Center hero)
    next_lesson = None
    for d in days_data:
        for ev in d['events']:
            if ev.get('type') == 'lesson' and ev.get('status') == 'planned':
                next_lesson = dict(ev)
                next_lesson['day_name'] = d['day_name']
                next_lesson['date'] = d['date']
                break
        if next_lesson:
            break

    # All upcoming deadlines queue (for Command Center and Personal Space)
    deadlines_queue = []
    for d in days_data:
        for ev in d['events']:
            if ev.get('type') == 'homework':
                item = dict(ev)
                item['day_name'] = d['day_name']
                item['date'] = d['date']
                deadlines_queue.append(item)

    return {
        'scenario': scenario,
        'scenario_title': {
            'standard': 'Стандартная неделя (2 урока, 1 ДЗ, 1 материал)',
            'single_lesson': 'Один урок на неделе (проверка баланса колонок)',
            'multi_event': 'Насыщенный день (2 урока разных тьюторов + ДЗ)',
            'empty_week': 'Пустая неделя / Каникулы (маскот Бу и отдых)',
            'long_titles': 'Длинные заголовки и сложные термины (стресс-тест)'
        }.get(scenario, scenario),
        'week_offset': week_offset,
        'week_label': f"{days_data[0]['date']} – {days_data[6]['date']} 2026",
        'default_selected_day_index': sel_day_idx,
        'selected_day': selected_day,
        'next_lesson': next_lesson,
        'deadlines_queue': deadlines_queue,
        'weekdays': days_data,
        'stats': {
            'conducted': total_conducted,
            'planned': total_planned,
            'homework': total_hw,
            'conducted_and_planned': total_lessons,
            'percent': percent,
            'streak_days': 5
        },
        'useful_materials': all_materials,
        'student_notes_general': notes_general,
        'student_name': 'София',
        'is_mock_preview': True
    }
