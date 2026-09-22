@echo off
chcp 65001 > nul
title FunPay AutoSteam Bot

echo ============================================================
echo   Запуск FunPay AutoSteam Bot
echo ============================================================

:: 1. Проверка наличия Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [-] ОШИБКА: Python не найден в системе!
        echo     1. Скачайте Python с официального сайта: https://www.python.org/downloads/
        echo     2. При установке ОБЯЗАТЕЛЬНО поставьте галочку:
        echo        "Add python.exe to PATH"
        echo.
        pause
        exit /b 1
    )
    set PY_CMD=py
) else (
    set PY_CMD=python
)

:: 2. Проверка и установка зависимостей
echo [*] Проверка и установка необходимых библиотек...
if exist "requirements.txt" (
    %PY_CMD% -m pip install -r requirements.txt --quiet
) else if exist "Funpay AutoSteam\requirements.txt" (
    %PY_CMD% -m pip install -r "Funpay AutoSteam\requirements.txt" --quiet
)

:: 3. Запуск бота
echo [*] Запуск бота...
echo.
if exist "bot_funpay.py" (
    %PY_CMD% bot_funpay.py
) else if exist "Funpay AutoSteam\bot_funpay.py" (
    %PY_CMD% "Funpay AutoSteam\bot_funpay.py"
) else (
    echo [-] ОШИБКА: Файл bot_funpay.py не найден!
)

echo.
echo ============================================================
echo   Работа программы завершена.
echo ============================================================
pause
