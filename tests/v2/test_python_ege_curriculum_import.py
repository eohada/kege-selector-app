from app import db
from app.models import Course, LessonRoomTemplate, TaskSolution, Tasks
from app.utils.python_ege_curriculum_import import (
    COURSE_SLUG,
    curriculum_metadata,
    import_curriculum_archive,
    load_curriculum_package,
)


def test_full_python_curriculum_import_is_complete_and_idempotent(app):
    package = load_curriculum_package()
    assert len(package['lessons']) == 60
    assert len(package['tasks']) == 540
    assert len(package['solutions']) >= 100

    with app.app_context():
        first = import_curriculum_archive(None, db)
        assert first['tasks_created'] == 540
        assert first['templates_created'] == 60

        course = Course.query.filter_by(slug=COURSE_SLUG).one()
        assert Tasks.query.filter_by(course_id=course.id, is_active=True).count() == 540
        assert LessonRoomTemplate.query.filter_by(visibility='shared', is_active=True).count() == 60
        assert TaskSolution.query.count() == 540
        assert Tasks.query.filter_by(course_id=course.id, answer=None).count() == 360

        second = import_curriculum_archive(None, db)
        assert second['tasks_created'] == 0
        assert second['tasks_updated'] == 540
        assert second['templates_created'] == 0
        assert second['templates_updated'] == 60
        assert Tasks.query.filter_by(course_id=course.id, is_active=True).count() == 540


def test_full_python_curriculum_metadata_makes_topics_searchable():
    metadata = curriculum_metadata()
    assert len(metadata) == 540
    assert any(value['module'] for value in metadata.values())
    assert any(value['type'] == 'Написание программы' for value in metadata.values())
