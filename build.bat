@echo off
rem Builds dist\Docket\Docket.exe (a folder you can keep anywhere, e.g. in Documents).
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name Docket --icon assets\docket.ico run.py
echo.
echo Done. Run dist\Docket\Docket.exe
pause
