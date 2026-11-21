@echo off
rem Runs Docket straight from the Python files (installs PySide6 the first time).
cd /d "%~dp0"
python -c "import PySide6" 2>nul || python -m pip install -r requirements.txt
start "" pythonw run.py
