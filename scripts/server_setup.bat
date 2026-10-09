@echo off
rem One-time: create virtual env + install server dependencies (no admin rights needed)
call "%~dp0_common.bat"
cd /d "%ROOT%\server"
if not exist .venv ( echo Creating virtual environment... & %PYTHON% -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
echo.
echo Server setup done. Next: server_run.bat
pause
