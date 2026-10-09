@echo off
set "HERE=%~dp0"
rem Build + install debug app on the USB-connected HHT and start Metro (hot reload for development)
call "%HERE%_common.bat"
cd /d "%ROOT%\hht"
adb devices
echo Make sure the HHT shows as "device" above (USB debugging on). Press any key...
pause >nul
call npx expo run:android
