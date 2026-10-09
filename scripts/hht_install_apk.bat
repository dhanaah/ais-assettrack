@echo off
set "HERE=%~dp0"
rem Install the latest APK from ROOT\dist on the USB-connected HHT (or drag an APK onto this .bat)
call "%HERE%_common.bat"
set APK=%~1
if "%APK%"=="" for /f "delims=" %%f in ('dir /b /o-d "%ROOT%\dist\*.apk" 2^>nul') do if not defined APK set "APK=%ROOT%\dist\%%f"
if "%APK%"=="" ( echo No APK found in dist\. Run hht_build_apk.bat or download from GitHub Actions. & pause & exit /b 1 )
adb devices
adb install -r "%APK%"
pause
