from pathlib import Path

from app import db
from app.models import Course, TaskSolution, TaskTemplate, Tasks, TemplateTask
from app.utils.python_ege_curriculum_import import COURSE_SLUG, import_curriculum_archive
from app.utils.python_ege_templates_import import import_templates_file, load_templates_package


def test_template_library_imports_150_drafts_with_ordered_cards(app, tmp_path):
    package = load_templates_package()
    assert len(package['templates']) == 150
    assert len(package['tasks']) == 555

    with app.app_context():
        import_curriculum_archive(None, db)
        result = import_templates_file(None, db, attachment_root=tmp_path / 'task_attachments')
        assert result['tasks_updated'] == 540
        assert result['tasks_created'] == 15
        assert result['templates_created'] == 150

        course = Course.query.filter_by(slug=COURSE_SLUG).one()
        assert Tasks.query.filter_by(course_id=course.id, is_active=True).count() == 555
        assert TaskTemplate.query.filter_by(course_id=course.id, is_draft=True, is_active=True).count() == 150

        first = TaskTemplate.query.filter_by(external_key='TPL-PY-START-DZ').one()
        ordered = TemplateTask.query.filter_by(template_id=first.template_id).order_by(TemplateTask.order).all()
        assert len(ordered) == 15
        assert [item.order for item in ordered] == list(range(1, 16))
        assert len(first.sections_json['sections']) == 3
        assert first.is_featured is True
        assert first.estimated_time == 40
        first_task = ordered[0].task
        assert first_task.answer is None
        assert TaskSolution.query.filter_by(task_id=first_task.task_id).one().solution_text
        assert first.attachments_json[0]['name'] == 'Python_osnovy_domashnyaya_rabota.pdf'
        assert (tmp_path / 'task_attachments' / str(first_task.task_id) / 'Python_osnovy_domashnyaya_rabota.pdf').is_file()

        repeated = import_templates_file(None, db, attachment_root=tmp_path / 'task_attachments')
        assert repeated['tasks_created'] == 0
        assert repeated['tasks_updated'] == 555
        assert repeated['templates_created'] == 0
        assert repeated['templates_updated'] == 150
        assert TaskTemplate.query.filter_by(course_id=course.id, is_draft=True).count() == 150


def test_template_package_uses_the_provided_pdf_without_modification():
    package = Path(__file__).parents[2] / 'data' / 'task_attachments' / 'Python_osnovy_domashnyaya_rabota.pdf'
    source = Path(r'E:\Downloads\Python_osnovy_domashnyaya_rabota.pdf')
    assert package.read_bytes() == source.read_bytes()
