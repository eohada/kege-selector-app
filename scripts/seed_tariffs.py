"""
Скрипт сидирования тарифов BooStudy из данных публичной страницы биллинга.
Заполняет TariffPlan актуальными ценами, условиями и возможностями.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from core.db_models import db, TariffPlan, TariffGroup

PRICING_DEFINITIONS = [
    # ── ЕГЭ ИНФОРМАТИКА ──
    # Solo
    {"exam": "ege", "subject": "inf", "format": "solo", "level": None, "title": "ЕГЭ Информатика: Solo Sprint", "label": "Sprint (1 мес)", "price": 4000, "period_days": 30, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": None, "desc": "Быстрый старт. Только тренажёр."},
    {"exam": "ege", "subject": "inf", "format": "solo", "level": None, "title": "ЕГЭ Информатика: Solo Season Pass", "label": "Season Pass (3 мес)", "price": 11000, "period_days": 90, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": None, "desc": "Идеально для рывка."},
    {"exam": "ege", "subject": "inf", "format": "solo", "level": None, "title": "ЕГЭ Информатика: Solo Career Mode", "label": "Career Mode (4 мес)", "price": 12800, "period_days": 120, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": "ХИТ", "desc": "Мощная подготовка."},
    {"exam": "ege", "subject": "inf", "format": "solo", "level": None, "title": "ЕГЭ Информатика: Solo Lead", "label": "Lead (9 мес)", "price": 25200, "period_days": 270, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": "ВЫГОДНО", "desc": "Весь учебный год."},
    # Mentor
    {"exam": "ege", "subject": "inf", "format": "mentor", "level": None, "title": "ЕГЭ Информатика: Mentor Junior", "label": "Junior (1 мес / 8 ур)", "price": 15200, "period_days": 30, "lessons": 8, "allow_trainer": False, "allow_lessons": True, "badge": None, "desc": "8 уроков по информатике с преподавателем."},
    {"exam": "ege", "subject": "inf", "format": "mentor", "level": None, "title": "ЕГЭ Информатика: Mentor Middle", "label": "Middle (2 мес / 16 ур)", "price": 28800, "period_days": 60, "lessons": 16, "allow_trainer": False, "allow_lessons": True, "badge": None, "desc": "16 уроков по информатике с преподавателем."},
    {"exam": "ege", "subject": "inf", "format": "mentor", "level": None, "title": "ЕГЭ Информатика: Mentor Advanced", "label": "Advanced (3 мес / 24 ур)", "price": 40800, "period_days": 90, "lessons": 24, "allow_trainer": False, "allow_lessons": True, "badge": None, "desc": "24 урока по информатике с преподавателем."},
    {"exam": "ege", "subject": "inf", "format": "mentor", "level": None, "title": "ЕГЭ Информатика: Mentor Senior", "label": "Senior (4 мес / 32 ур)", "price": 51200, "period_days": 120, "lessons": 32, "allow_trainer": False, "allow_lessons": True, "badge": "ХИТ", "desc": "32 урока по информатике с преподавателем."},
    {"exam": "ege", "subject": "inf", "format": "mentor", "level": None, "title": "ЕГЭ Информатика: Mentor Lead", "label": "Lead (9 мес / 72 ур)", "price": 108000, "period_days": 270, "lessons": 72, "allow_trainer": False, "allow_lessons": True, "badge": "ТОП", "desc": "72 урока. Полный годовой курс с репетитором."},
    # God Mode
    {"exam": "ege", "subject": "inf", "format": "godmode", "level": None, "title": "ЕГЭ Информатика: God Mode Junior+", "label": "Junior+ (1 мес / 8 ур)", "price": 17200, "period_days": 30, "lessons": 8, "allow_trainer": True, "allow_lessons": True, "badge": None, "desc": "8 уроков + безлимитный тренажёр КЕГЭ."},
    {"exam": "ege", "subject": "inf", "format": "godmode", "level": None, "title": "ЕГЭ Информатика: God Mode Middle+", "label": "Middle+ (2 мес / 16 ур)", "price": 32000, "period_days": 60, "lessons": 16, "allow_trainer": True, "allow_lessons": True, "badge": None, "desc": "16 уроков + безлимитный тренажёр КЕГЭ."},
    {"exam": "ege", "subject": "inf", "format": "godmode", "level": None, "title": "ЕГЭ Информатика: God Mode Advanced+", "label": "Advanced+ (3 мес / 24 ур)", "price": 46000, "period_days": 90, "lessons": 24, "allow_trainer": True, "allow_lessons": True, "badge": None, "desc": "24 урока + безлимитный тренажёр КЕГЭ."},
    {"exam": "ege", "subject": "inf", "format": "godmode", "level": None, "title": "ЕГЭ Информатика: God Mode Senior+", "label": "Senior+ (4 мес / 32 ур)", "price": 57600, "period_days": 120, "lessons": 32, "allow_trainer": True, "allow_lessons": True, "badge": "ХИТ", "desc": "32 урока + безлимитный тренажёр КЕГЭ."},
    {"exam": "ege", "subject": "inf", "format": "godmode", "level": None, "title": "ЕГЭ Информатика: God Mode Lead+", "label": "Lead+ (9 мес / 72 ур)", "price": 121500, "period_days": 270, "lessons": 72, "allow_trainer": True, "allow_lessons": True, "badge": "ТОП", "desc": "72 урока + полный доступ ко всем функциям платформы."},

    # ── ЕГЭ МАТЕМАТИКА (ПРОФИЛЬ) ──
    # Solo
    {"exam": "ege", "subject": "math", "format": "solo", "level": "prof", "title": "ЕГЭ Математика Профиль: Solo Sprint", "label": "Sprint (1 мес)", "price": 4000, "period_days": 30, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": None, "desc": "Быстрый старт. Только тренажёр."},
    {"exam": "ege", "subject": "math", "format": "solo", "level": "prof", "title": "ЕГЭ Математика Профиль: Solo Season Pass", "label": "Season Pass (3 мес)", "price": 11000, "period_days": 90, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": None, "desc": "Идеально для рывка."},
    {"exam": "ege", "subject": "math", "format": "solo", "level": "prof", "title": "ЕГЭ Математика Профиль: Solo Career Mode", "label": "Career Mode (4 мес)", "price": 12800, "period_days": 120, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": "ХИТ", "desc": "Мощная подготовка."},
    {"exam": "ege", "subject": "math", "format": "solo", "level": "prof", "title": "ЕГЭ Математика Профиль: Solo Lead", "label": "Lead (9 мес)", "price": 25200, "period_days": 270, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": "ВЫГОДНО", "desc": "Весь учебный год."},
    # Mentor
    {"exam": "ege", "subject": "math", "format": "mentor", "level": "prof", "title": "ЕГЭ Математика Профиль: Mentor Junior", "label": "Junior (1 мес / 8 ур)", "price": 16800, "period_days": 30, "lessons": 8, "allow_trainer": False, "allow_lessons": True, "badge": None, "desc": "8 уроков по профильной математике."},
    {"exam": "ege", "subject": "math", "format": "mentor", "level": "prof", "title": "ЕГЭ Математика Профиль: Mentor Middle", "label": "Middle (2 мес / 16 ур)", "price": 32400, "period_days": 60, "lessons": 16, "allow_trainer": False, "allow_lessons": True, "badge": None, "desc": "16 уроков по профильной математике."},
    {"exam": "ege", "subject": "math", "format": "mentor", "level": "prof", "title": "ЕГЭ Математика Профиль: Mentor Advanced", "label": "Advanced (3 мес / 24 ур)", "price": 46800, "period_days": 90, "lessons": 24, "allow_trainer": False, "allow_lessons": True, "badge": None, "desc": "24 урока по профильной математике."},
    {"exam": "ege", "subject": "math", "format": "mentor", "level": "prof", "title": "ЕГЭ Математика Профиль: Mentor Senior", "label": "Senior (4 мес / 32 ур)", "price": 60000, "period_days": 120, "lessons": 32, "allow_trainer": False, "allow_lessons": True, "badge": "ХИТ", "desc": "32 урока по профильной математике."},
    {"exam": "ege", "subject": "math", "format": "mentor", "level": "prof", "title": "ЕГЭ Математика Профиль: Mentor Lead", "label": "Lead (9 мес / 72 ур)", "price": 129600, "period_days": 270, "lessons": 72, "allow_trainer": False, "allow_lessons": True, "badge": "ТОП", "desc": "72 урока по профильной математике."},
    # God Mode
    {"exam": "ege", "subject": "math", "format": "godmode", "level": "prof", "title": "ЕГЭ Математика Профиль: God Mode Junior+", "label": "Junior+ (1 мес / 8 ур)", "price": 19000, "period_days": 30, "lessons": 8, "allow_trainer": True, "allow_lessons": True, "badge": None, "desc": "Уроки + тренажер по профильной математике."},
    {"exam": "ege", "subject": "math", "format": "godmode", "level": "prof", "title": "ЕГЭ Математика Профиль: God Mode Middle+", "label": "Middle+ (2 мес / 16 ур)", "price": 36000, "period_days": 60, "lessons": 16, "allow_trainer": True, "allow_lessons": True, "badge": None, "desc": "Уроки + тренажер по профильной математике."},
    {"exam": "ege", "subject": "math", "format": "godmode", "level": "prof", "title": "ЕГЭ Математика Профиль: God Mode Advanced+", "label": "Advanced+ (3 мес / 24 ур)", "price": 52000, "period_days": 90, "lessons": 24, "allow_trainer": True, "allow_lessons": True, "badge": None, "desc": "Уроки + тренажер по профильной математике."},
    {"exam": "ege", "subject": "math", "format": "godmode", "level": "prof", "title": "ЕГЭ Математика Профиль: God Mode Senior+", "label": "Senior+ (4 мес / 32 ур)", "price": 65600, "period_days": 120, "lessons": 32, "allow_trainer": True, "allow_lessons": True, "badge": "ХИТ", "desc": "Уроки + тренажер по профильной математике."},
    {"exam": "ege", "subject": "math", "format": "godmode", "level": "prof", "title": "ЕГЭ Математика Профиль: God Mode Lead+", "label": "Lead+ (9 мес / 72 ур)", "price": 139500, "period_days": 270, "lessons": 72, "allow_trainer": True, "allow_lessons": True, "badge": "ТОП", "desc": "Уроки + тренажер по профильной математике."},

    # ── ОГЭ (ИНФОРМАТИКА / МАТЕМАТИКА) ──
    # Solo
    {"exam": "oge", "subject": "inf", "format": "solo", "level": None, "title": "ОГЭ Информатика: Solo Sprint", "label": "Sprint (1 мес)", "price": 3000, "period_days": 30, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": None, "desc": "Только тренажёр."},
    {"exam": "oge", "subject": "inf", "format": "solo", "level": None, "title": "ОГЭ Информатика: Solo Season Pass", "label": "Season Pass (3 мес)", "price": 8000, "period_days": 90, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": None, "desc": "Идеально для рывка."},
    {"exam": "oge", "subject": "inf", "format": "solo", "level": None, "title": "ОГЭ Информатика: Solo Career Mode", "label": "Career Mode (4 мес)", "price": 10400, "period_days": 120, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": "ХИТ", "desc": "Мощная подготовка."},
    {"exam": "oge", "subject": "inf", "format": "solo", "level": None, "title": "ОГЭ Информатика: Solo Lead", "label": "Lead (9 мес)", "price": 18000, "period_days": 270, "lessons": 0, "allow_trainer": True, "allow_lessons": False, "badge": "ВЫГОДНО", "desc": "Весь учебный год."},
    # Mentor
    {"exam": "oge", "subject": "inf", "format": "mentor", "level": None, "title": "ОГЭ Информатика: Mentor Junior", "label": "Junior (1 мес / 8 ур)", "price": 12800, "period_days": 30, "lessons": 8, "allow_trainer": False, "allow_lessons": True, "badge": None, "desc": "8 уроков ОГЭ с преподавателем."},
    {"exam": "oge", "subject": "inf", "format": "mentor", "level": None, "title": "ОГЭ Информатика: Mentor Middle", "label": "Middle (2 мес / 16 ур)", "price": 24400, "period_days": 60, "lessons": 16, "allow_trainer": False, "allow_lessons": True, "badge": None, "desc": "16 уроков ОГЭ с преподавателем."},
    {"exam": "oge", "subject": "inf", "format": "mentor", "level": None, "title": "ОГЭ Информатика: Mentor Advanced", "label": "Advanced (3 мес / 24 ур)", "price": 34800, "period_days": 90, "lessons": 24, "allow_trainer": False, "allow_lessons": True, "badge": None, "desc": "24 урока ОГЭ с преподавателем."},
    {"exam": "oge", "subject": "inf", "format": "mentor", "level": None, "title": "ОГЭ Информатика: Mentor Senior", "label": "Senior (4 мес / 32 ур)", "price": 44000, "period_days": 120, "lessons": 32, "allow_trainer": False, "allow_lessons": True, "badge": "ХИТ", "desc": "32 урока ОГЭ с преподавателем."},
    {"exam": "oge", "subject": "inf", "format": "mentor", "level": None, "title": "ОГЭ Информатика: Mentor Lead", "label": "Lead (9 мес / 72 ур)", "price": 93600, "period_days": 270, "lessons": 72, "allow_trainer": False, "allow_lessons": True, "badge": "ТОП", "desc": "72 урока. Полный курс ОГЭ с преподавателем."},
    # God Mode
    {"exam": "oge", "subject": "inf", "format": "godmode", "level": None, "title": "ОГЭ Информатика: God Mode Junior+", "label": "Junior+ (1 мес / 8 ур)", "price": 14300, "period_days": 30, "lessons": 8, "allow_trainer": True, "allow_lessons": True, "badge": None, "desc": "Уроки + Тренажер ОГЭ."},
    {"exam": "oge", "subject": "inf", "format": "godmode", "level": None, "title": "ОГЭ Информатика: God Mode Middle+", "label": "Middle+ (2 мес / 16 ур)", "price": 27000, "period_days": 60, "lessons": 16, "allow_trainer": True, "allow_lessons": True, "badge": None, "desc": "Уроки + Тренажер ОГЭ."},
    {"exam": "oge", "subject": "inf", "format": "godmode", "level": None, "title": "ОГЭ Информатика: God Mode Advanced+", "label": "Advanced+ (3 мес / 24 ур)", "price": 39000, "period_days": 90, "lessons": 24, "allow_trainer": True, "allow_lessons": True, "badge": None, "desc": "Уроки + Тренажер ОГЭ."},
    {"exam": "oge", "subject": "inf", "format": "godmode", "level": None, "title": "ОГЭ Информатика: God Mode Senior+", "label": "Senior+ (4 мес / 32 ур)", "price": 48800, "period_days": 120, "lessons": 32, "allow_trainer": True, "allow_lessons": True, "badge": "ХИТ", "desc": "Уроки + Тренажер ОГЭ."},
    {"exam": "oge", "subject": "inf", "format": "godmode", "level": None, "title": "ОГЭ Информатика: God Mode Lead+", "label": "Lead+ (9 мес / 72 ур)", "price": 103500, "period_days": 270, "lessons": 72, "allow_trainer": True, "allow_lessons": True, "badge": "ТОП", "desc": "Уроки + Тренажер ОГЭ."},
]

def seed_tariffs():
    app = create_app()
    with app.app_context():
        print("Ensuring groups...")
        g_solo = TariffGroup.query.filter_by(title="Solo (Инди-трек)").first()
        if not g_solo:
            g_solo = TariffGroup(title="Solo (Инди-трек)", order_index=1, is_active=True)
            db.session.add(g_solo)

        g_mentor = TariffGroup.query.filter_by(title="Mentor (Классика)").first()
        if not g_mentor:
            g_mentor = TariffGroup(title="Mentor (Классика)", order_index=2, is_active=True)
            db.session.add(g_mentor)

        g_godmode = TariffGroup.query.filter_by(title="God Mode").first()
        if not g_godmode:
            g_godmode = TariffGroup(title="God Mode", order_index=3, is_active=True)
            db.session.add(g_godmode)

        db.session.flush()

        group_map = {
            "solo": g_solo.group_id,
            "mentor": g_mentor.group_id,
            "godmode": g_godmode.group_id,
        }

        created = 0
        updated = 0

        for idx, item in enumerate(PRICING_DEFINITIONS):
            plan = TariffPlan.query.filter_by(
                exam=item["exam"],
                subject=item["subject"],
                format=item["format"],
                level=item.get("level"),
                price_rub=item["price"]
            ).first()

            if not plan:
                # Попробуем найти по title
                plan = TariffPlan.query.filter_by(title=item["title"]).first()

            features = []
            if item["allow_trainer"]:
                features.append("Неограниченный ИИ-тренажёр КЕГЭ")
            if item["lessons"] > 0:
                features.append(f"{item['lessons']} уроков с репетитором")
                features.append("Персональная проверка домашних заданий")
            else:
                features.append("Автоматическая проверка задач")
            features.append("Аналитика прогресса и ELO MMR")
            features.append("База знаний и видеоматериалы")

            price_per_lesson = int(item["price"] / item["lessons"]) if item["lessons"] > 0 else None

            if not plan:
                plan = TariffPlan(
                    title=item["title"],
                    description=item["desc"],
                    group_id=group_map.get(item["format"]),
                    order_index=idx,
                    price_rub=item["price"],
                    price_per_lesson_rub=price_per_lesson,
                    period_days=item["period_days"],
                    lessons_count=item["lessons"],
                    allow_lessons=item["allow_lessons"],
                    allow_trainer=item["allow_trainer"],
                    allow_referral=True,
                    allow_promocode=True,
                    exam=item["exam"],
                    subject=item["subject"],
                    format=item["format"],
                    level=item.get("level"),
                    badge=item.get("badge"),
                    features=features,
                    is_active=True
                )
                db.session.add(plan)
                created += 1
            else:
                plan.title = item["title"]
                plan.description = item["desc"]
                plan.group_id = group_map.get(item["format"])
                plan.order_index = idx
                plan.price_rub = item["price"]
                plan.price_per_lesson_rub = price_per_lesson
                plan.period_days = item["period_days"]
                plan.lessons_count = item["lessons"]
                plan.allow_lessons = item["allow_lessons"]
                plan.allow_trainer = item["allow_trainer"]
                plan.allow_referral = True
                plan.allow_promocode = True
                plan.exam = item["exam"]
                plan.subject = item["subject"]
                plan.format = item["format"]
                plan.level = item.get("level")
                plan.badge = item.get("badge")
                plan.features = features
                plan.is_active = True
                updated += 1

        db.session.commit()
        print(f"Tariff seeding complete: {created} created, {updated} updated.")

if __name__ == '__main__':
    seed_tariffs()
