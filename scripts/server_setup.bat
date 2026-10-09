@echo off
set "HERE=%~dp0"
rem One-time: install server libraries for the current user (no admin rights, no virtual env). Log: server_setup.log
call "%HERE%_common.bat"
cd /d "%ROOT%\server"
set "LOG=%HERE%server_setup.log"
echo === server setup %date% %time% === > "%LOG%"
%PYTHON% --version >> "%LOG%" 2>&1
if errorlevel 1 ( echo Python not found. Install Python 3.11+ from the Company Portal or python.org ^(tick "Add to PATH"^). & echo RESULT=NO_PYTHON >> "%LOG%" & pause & exit /b 1 )
echo Installing libraries, please wait 1-3 minutes...
%PYTHON% -m pip install --user -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 ( echo SETUP FAILED - see %LOG% & echo RESULT=FAILED >> "%LOG%" & pause & exit /b 1 )
%PYTHON% -c "import fastapi, uvicorn, sqlalchemy, jwt, bcrypt, openpyxl, segno" >> "%LOG%" 2>&1
if errorlevel 1 ( echo SETUP CHECK FAILED - see %LOG% & echo RESULT=CHECK_FAILED >> "%LOG%" & pause & exit /b 1 )
echo ok> "%ROOT%\server\.setup_ok"
echo RESULT=OK >> "%LOG%"
echo Server setup done.
