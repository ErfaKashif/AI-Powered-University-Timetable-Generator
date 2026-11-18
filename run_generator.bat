@echo off
cd /d "%~dp0"
set PY=python
python --version >nul 2>&1 || set PY=py
%PY% --version >nul 2>&1 || (echo Python is not installed. Install it from python.org and tick "Add python.exe to PATH". & pause & exit /b)
echo Installing required libraries (only slow the first time)...
%PY% -m pip install -r requirements.txt
echo.
%PY% main.py
if exist output\timetable_sem5_7.xlsx start "" output\timetable_sem5_7.xlsx
pause
