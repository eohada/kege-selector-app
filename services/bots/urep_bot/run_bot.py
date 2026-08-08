#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Заглушка для старых Docker/Procfile-команд.

BooStudy-бот обрабатывается внутри Flask (маршрут POST /webhook/telegram), а не
отдельным процессом polling. Если docker-compose всё ещё запускает этот файл,
контейнер не падает с «file not found», но бот реально работает только через web.

Что сделать на сервере:
  1. Удалить сервис bot_prod / bot из docker-compose.yml (или закомментировать).
  2. Оставить работающим только сервис web (gunicorn) + при необходимости celery.
  3. Убедиться, что у Telegram выставлен webhook на https://ВАШ_ДОМЕН/webhook/telegram

Подробнее: см. DEPLOY_TELEGRAM_WEBHOOK.md в корне репозитория.
"""
from __future__ import annotations

import logging
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main() -> None:
    log.warning(
        "urep_bot/run_bot.py: это заглушка. Реальный бот — webhook в контейнере web. "
        "Удалите сервис bot_prod из docker-compose, чтобы не держать лишний контейнер."
    )
    while True:
        time.sleep(86400)


if __name__ == "__main__":
    main()
