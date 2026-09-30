@echo off
cd /d "%~dp0"

rem pervyi zapusk - sozdaem okruzhenie i stavim zavisimosti
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv || goto :nopython
    .venv\Scripts\python.exe -m pip install --upgrade pip >nul
    echo Installing requirements, it may take a couple of minutes...
    .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :fail
)

start "" .venv\Scripts\pythonw.exe main.py
goto :eof

:nopython
echo Python not found. Install Python 3.11+ from python.org and check "Add to PATH".
pause
goto :eof

:fail
echo Failed to install requirements. If VPN is on - try without it.
echo Delete the .venv folder and run start.bat again.
pause
