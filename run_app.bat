@echo off
cd /d "%~dp0"
set PY=python
python --version >nul 2>&1 || set PY=py
%PY% --version >nul 2>&1 || (echo Python is not installed. Install it from python.org and tick "Add python.exe to PATH". & pause & exit /b)
echo Installing required libraries (only slow the first time)...
%PY% -m pip install -r requirements.txt
echo.
echo Starting the Timetable Generator. Your browser will open at http://localhost:8501
echo Keep this window open while using the app. Close it to stop the app.
%PY% -m streamlit run app.py
pause
