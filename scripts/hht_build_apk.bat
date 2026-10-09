@echo off
rem Build a release APK locally (JDK 17 + Android SDK + ANDROID_HOME required). Output copied to ROOT\dist
call "%~dp0_common.bat"
cd /d "%ROOT%\hht"
if "%ANDROID_HOME%"=="" if "%ANDROID_SDK_ROOT%"=="" ( echo ANDROID_HOME is not set. Install Android Studio / SDK and set ANDROID_HOME. & pause & exit /b 1 )
if not exist android ( echo Generating native project... & call npx expo prebuild -p android --no-install )
cd android
call gradlew.bat assembleRelease
if errorlevel 1 ( echo BUILD FAILED & pause & exit /b 1 )
for /f "tokens=2 delims=:, " %%v in ('findstr /c:"\"version\"" ..\app.json') do set VER=%%~v
if not exist "%ROOT%\dist" mkdir "%ROOT%\dist"
copy /y app\build\outputs\apk\release\app-release.apk "%ROOT%\dist\AIS_AssetTrack_HHT_v%VER%.apk"
echo.
echo APK: %ROOT%\dist\AIS_AssetTrack_HHT_v%VER%.apk
pause
