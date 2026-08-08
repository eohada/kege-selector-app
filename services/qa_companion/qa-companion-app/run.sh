#!/usr/bin/env bash

# Получаем все пути библиотек из текущего шелла (где они правильные)
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH

# Запускаем питон напрямую через бинарник в venv, прокидывая окружение
sudo -E .venv/bin/python gui.py
