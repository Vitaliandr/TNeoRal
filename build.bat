@echo off
cd /d "%~dp0"

rem sborka TNeoRal.exe, rezultat v dist\
if not exist .venv (
    echo Run start.bat first - it creates .venv
    pause
    goto :eof
)

.venv\Scripts\python.exe -m pip install -q pyinstaller

.venv\Scripts\python.exe -m PyInstaller main.py ^
    --name TNeoRal ^
    --onefile --windowed --noconfirm --clean ^
    --icon assets\icon.ico ^
    --add-data "tneoral\ui\theme.qss;tneoral\ui" ^
    --add-data ".venv\Lib\site-packages\PySide6\translations\qtbase_ru.qm;translations" ^
    --collect-data t_tech ^
    --hidden-import keyring.backends.Windows ^
    --hidden-import win32ctypes.core ^
    --exclude-module pytest ^
    --exclude-module tkinter

if errorlevel 1 (
    echo Build failed
    pause
    goto :eof
)
echo Done: dist\TNeoRal.exe
