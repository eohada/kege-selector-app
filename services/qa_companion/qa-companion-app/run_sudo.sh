#!/usr/bin/env bash

# В NixOS sudo ВСЕГДА вырезает LD_LIBRARY_PATH по соображениям безопасности.
# Поэтому мы передаем переменную в инлайн-виде прямо перед вызовом исполняемого файла
sudo LD_LIBRARY_PATH=$NIX_LD_LIBRARY_PATH .venv/bin/python gui.py
