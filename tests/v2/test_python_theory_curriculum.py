import pytest
from app.models import User, Student, Course, TheoryGroup, TheoryBlock, StudentTheoryState, db
from tests.v2.conftest import login_as
from scripts.seed_comprehensive_python_theory import MODULES_DEF, ALL_33_TOPICS


def test_python_comprehensive_curriculum_integrity(app, client):
    with app.app_context():
        # Ensure a course exists for the test and is active
        course = Course.query.filter_by(slug="ege-informatics").first()
        if not course:
            course = Course(title="ЕГЭ Информатика", slug="ege-informatics", is_active=True)
            db.session.add(course)
            db.session.commit()
        else:
            course.is_active = True
            db.session.commit()

        # Seed the 8 groups and 33 blocks into this test course
        for g_pos, m in enumerate(MODULES_DEF, start=1):
            group = TheoryGroup.query.filter_by(course_id=course.id, name=m["name"]).first()
            if not group:
                group = TheoryGroup(
                    course_id=course.id,
                    name=m["name"],
                    description=m["description"],
                    position=g_pos,
                )
                db.session.add(group)
                db.session.flush()

            for b_pos, (tn, info) in enumerate(sorted(m["topics"].items()), start=1):
                block = TheoryBlock.query.filter_by(course_id=course.id, task_number=tn).first()
                if not block:
                    block = TheoryBlock(
                        course_id=course.id,
                        group_id=group.id,
                        task_number=tn,
                        title=info["title"],
                        read_minutes=info["read_minutes"],
                        content=info["content"].strip(),
                        position=b_pos,
                    )
                    db.session.add(block)
                else:
                    block.group_id = group.id
                    block.title = info["title"]
                    block.read_minutes = info["read_minutes"]
                    block.content = info["content"].strip()
                    block.position = b_pos
        db.session.commit()

        # Check groups
        groups = TheoryGroup.query.filter(
            TheoryGroup.course_id == course.id,
            TheoryGroup.name.ilike("Программирование:%")
        ).order_by(TheoryGroup.position).all()

        assert len(groups) == 7, f"Expected 7 programming groups, found {len(groups)}"

        # Check all 30 blocks
        blocks = TheoryBlock.query.filter(
            TheoryBlock.course_id == course.id,
            TheoryBlock.task_number.between(101, 130)
        ).order_by(TheoryBlock.task_number).all()

        assert len(blocks) == 30, f"Expected 30 programming blocks, found {len(blocks)}"

        # Check 5 mandatory sections in every block content
        for b in blocks:
            content = b.content or ""
            assert "## Зачем это нужно в ЕГЭ" in content, f"Missing 'Зачем в ЕГЭ' in task {b.task_number}"
            assert "## Синтаксис и" in content, f"Missing 'Синтаксис' in task {b.task_number}"
            assert "## Примеры кода" in content, f"Missing 'Примеры кода' in task {b.task_number}"
            assert "## Ловушки и частые ошибки" in content, f"Missing 'Ловушки' in task {b.task_number}"
            assert "## Микро-проверки" in content, f"Missing 'Микро-проверки' in task {b.task_number}"
            assert "[CHECKPOINT" in content, f"Missing checkpoints in task {b.task_number}"

        # Create test user to verify theory catalogue access
        user = User(username="theory_tester_student", role="student")
        user.set_password("pass123")
        db.session.add(user)
        db.session.commit()

        student = Student(user_id=user.id, name="Theory Student")
        db.session.add(student)
        db.session.commit()

        user_id = user.id
        course_id = course.id
        first_block_id = blocks[0].id
        block_ids = [b.id for b in blocks[:6]]

    login_as(client, user_id=user_id, role="student")

    # 1. Catalogue loads with 7 groups
    cat_resp = client.get(f"/theory?course_id={course_id}")
    assert cat_resp.status_code == 200
    cat_html = cat_resp.get_data(as_text=True)
    assert "Программирование: Основы и типы данных" in cat_html
    assert "Программирование: Функции и подпрограммы" in cat_html

    # 2. View article for task 101 via /theory/topic/<id>
    article_resp = client.get(f"/theory/topic/{first_block_id}?course_id={course_id}")
    assert article_resp.status_code == 200
    article_html = article_resp.get_data(as_text=True)
    assert "Что такое программа и синтаксис Python" in article_html
    assert "Модель памяти" in article_html

    # 3. Check copy button has proper padding and whitespace-nowrap
    assert "theory-copy-btn" in article_html
    assert "px-3.5 py-1.5" in article_html
    assert "whitespace-nowrap" in article_html

    # 4. Check bottom navigation has inline-block truncate and overflow prevention
    assert "inline-block truncate max-w-[180px]" in article_html
    assert "overflow-hidden" in article_html

    # 5. Check aside is self-stretch and personal note/Boo advice are pinned
    assert "self-stretch" in article_html
    assert "theory-pinned-sidebar" in article_html
    assert "overflow-x-clip" in article_html
    assert "Личная заметка" in article_html
    assert "Совет от Бу" in article_html
    assert "\\text{" not in article_html
    assert "Шпаргалка (PDF)" in article_html

    # Test PDF generation for this topic
    pdf_resp = client.get(f"/theory/topic/{block_ids[0]}/pdf?course_id={course_id}")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers.get("Content-Type") == "application/pdf"
    assert pdf_resp.data.startswith(b"%PDF")


    # 6. Check checkpoint option positions are distributed (not all top-right / index 1)
    # Check across multiple topic pages
    correct_positions = []
    from bs4 import BeautifulSoup
    for b_id in block_ids:
        resp = client.get(f"/theory/topic/{b_id}?course_id={course_id}")
        soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
        for card in soup.find_all(class_="theory-checkpoint"):
            cp_key = card.get("data-checkpoint-key")
            buttons = card.find_all("button", attrs={"data-action": "checkpoint-choice"})
            if not buttons:
                continue
            # Find which button has the correct answer by calling checkpoint api
            for idx, btn in enumerate(buttons):
                ans = btn.get("data-answer")
                res = client.post(
                    "/theory/api/checkpoint",
                    json={"block_id": b_id, "checkpoint_key": cp_key, "answer": ans},
                )
                if res.status_code == 200 and res.get_json().get("correct"):
                    correct_positions.append(idx)
                    break

    assert len(correct_positions) >= 4, f"Found only {len(correct_positions)} checkpoints"
    # Ensure options are distributed across multiple indices (not all 1 or all 0)
    unique_indices = set(correct_positions)
    assert len(unique_indices) > 1, f"Options not randomized, all at index {unique_indices}"
