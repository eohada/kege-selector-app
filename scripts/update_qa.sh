#!/usr/bin/env bash

# 1. Исправляем 500 ошибку в report_detail.html (неправильный url_for)
sed -i 's/url_for('\''qa_admin.report_action'\''/url_for('\''qa_admin.update_report_status'\''/g' templates/admin/qa/report_detail.html

# 2. Подключаем виджет в base.html
# Добавляем перед закрывающим тегом </body>
if ! grep -q "{% include 'qa/_floating_widget.html' %}" templates/base.html; then
  sed -i 's|</body>|    {% if current_user.is_authenticated and current_user.role in ["admin", "tester", "creator"] %}\n        {% include "qa/_floating_widget.html" %}\n    {% endif %}\n</body>|g' templates/base.html
fi
