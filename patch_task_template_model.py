with open('core/db_models.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = """    is_active = db.Column(db.Boolean, default=True)

    template_tasks = db.relationship('TemplateTask', back_populates='template', lazy=True, cascade='all, delete-orphan')"""

replacement = """    is_active = db.Column(db.Boolean, default=True)
    estimated_time = db.Column(db.Integer, default=45, nullable=True)  # Время выполнения в минутах
    course_id = db.Column(db.Integer, nullable=True)

    template_tasks = db.relationship('TemplateTask', back_populates='template', lazy=True, cascade='all, delete-orphan')

    @property
    def id(self):
        return self.template_id

    @property
    def title(self):
        return self.name

    @title.setter
    def title(self, val):
        self.name = val

    @property
    def teacher_id(self):
        return self.created_by

    @teacher_id.setter
    def teacher_id(self, val):
        self.created_by = val

    @property
    def tasks_count(self):
        return len(self.template_tasks) if self.template_tasks else 0"""

if 'estimated_time = db.Column(' not in content:
    content = content.replace(target, replacement)
    # Add alias
    if 'AssignmentTemplate = TaskTemplate' not in content:
        content += "\n\nAssignmentTemplate = TaskTemplate\n"
    with open('core/db_models.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Patched TaskTemplate in core/db_models.py!")
else:
    print("TaskTemplate already updated.")
