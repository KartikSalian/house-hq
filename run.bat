@echo off
REM House HQ - one-click run for Windows
cd /d "%~dp0"
echo Installing dependencies...
python -m pip install -r requirements.txt
echo.
echo Starting House HQ...
echo Open http://localhost:5000 in your browser
echo Press Ctrl+C to stop.
echo.
python app.py
pause
