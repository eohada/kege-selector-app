from tests.v2.test_course_adaptive_program_v2 import login_as


def test_teacher_guidebook_has_role_specific_sections_and_links(client, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')
    page = client.get('/guidebook')
    assert page.status_code == 200
    assert 'Гайдбук преподавателя'.encode('utf-8') in page.data
    assert 'Курсы и маршрут'.encode('utf-8') in page.data
    detail = client.get('/guidebook/teacher/courses')
    assert detail.status_code == 200
    assert 'Настройте навыки'.encode('utf-8') in detail.data
    assert 'Контрольный список'.encode('utf-8') in detail.data
    assert 'Если что-то не получилось'.encode('utf-8') in detail.data
    assert 'Как устроена система'.encode('utf-8') in detail.data
    assert 'Курс как маршрут'.encode('utf-8') in detail.data
    assert 'Из чего состоит модуль'.encode('utf-8') in detail.data
    assert 'LearningItem'.encode('utf-8') in detail.data
    assert 'Полный жизненный цикл'.encode('utf-8') in detail.data
    assert 'Состояния и переходы'.encode('utf-8') in detail.data
    assert 'Права ролей'.encode('utf-8') in detail.data
    assert 'Что сохраняется'.encode('utf-8') in detail.data
    assert 'Контрольные сценарии'.encode('utf-8') in detail.data
    assert 'LessonOutcome'.encode('utf-8') in detail.data
    assert detail.data.count(b'type="checkbox"') >= 5
    assert b'/students' in detail.data


def test_student_guidebook_uses_student_shell_and_hides_teacher_content(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')
    page = client.get('/guidebook')
    assert page.status_code == 200
    assert 'Гайдбук ученика'.encode('utf-8') in page.data
    assert 'Задания и отправка'.encode('utf-8') in page.data
    assert 'Ученики и отношения'.encode('utf-8') not in page.data
    detail = client.get('/guidebook/student/lesson-room')
    assert detail.status_code == 200
    assert 'Комната урока'.encode('utf-8') in detail.data
    assert 'Перед началом'.encode('utf-8') in detail.data
    assert 'Ожидаемый результат'.encode('utf-8') in detail.data
    assert 'Комната как единое рабочее пространство'.encode('utf-8') in detail.data
    assert 'Realtime'.encode('utf-8') in detail.data
    assert 'Состояния и переходы'.encode('utf-8') in detail.data
    assert 'Что сохраняется'.encode('utf-8') in detail.data


def test_guidebook_rejects_unknown_audience_or_section(client, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')
    assert client.get('/guidebook/unknown/start').status_code == 404
    assert client.get('/guidebook/teacher/missing').status_code == 404
