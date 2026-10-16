@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0status-local-telegram.ps1" %*
