@echo off
set "HERE=%~dp0"
rem One-time: create virtual env + install server dependencies (no admin rights needed). Log: server_setup.log
call "%HERE%_common.bat"
cd /d "%ROOT%\server"
set LOG=%HERE%server_setup.log
echo === server setup %date% %time% === > "%LOG%"
if not exist .venv ( echo Creating virtual environment... & %PYTHON% -m venv .venv >> "%LOG%" 2>&1 )
call .venv\Scripts\activate.bat
echo Installing libraries, please wait 1-3 minutes...
python -m pip install --upgrade pip >> "%LOG%" 2>&1
pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 ( echo SETUP FAILED - see server_setup.log & echo RESULT=FAILED >> "%LOG%" ) else ( echo Server setup done. Next: server_run.bat & echo RESULT=OK >> "%LOG%" )
timeout /t 5
