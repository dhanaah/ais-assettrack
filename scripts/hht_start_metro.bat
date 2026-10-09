@echo off
rem Start Metro bundler only (app already installed): reload JS changes without reinstalling
call "%~dp0_common.bat"
cd /d "%ROOT%\hht"
adb reverse tcp:8081 tcp:8081
call npx expo start --dev-client
