@echo off
rem Remove generated native project + caches (fixes most "weird build" problems). Re-run hht_build_apk.bat after.
call "%~dp0_common.bat"
cd /d "%ROOT%\hht"
rmdir /s /q android 2>nul
rmdir /s /q .expo 2>nul
rmdir /s /q node_modules\.cache 2>nul
echo Cleaned. Next: hht_build_apk.bat (or hht_setup.bat if node_modules was removed)
pause
