@echo off
set "HERE=%~dp0"
rem Start Metro bundler only (app already installed): reload JS changes without reinstalling
call "%HERE%_common.bat"
cd /d "%ROOT%\hht"
adb reverse tcp:8081 tcp:8081
call npx expo start --dev-client
