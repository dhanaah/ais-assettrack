@echo off
set "HERE=%~dp0"
rem Writes what is installed on this PC to check_pc.log (used during setup). Developed by DT
cd /d "%HERE%"
(
echo === AIS AssetTrack PC check %date% %time% ===
echo --- python
where python 2^>^&1
python --version 2^>^&1
echo --- py launcher
py -3 --version 2^>^&1
echo --- node
node --version 2^>^&1
echo --- npm
call npm --version 2^>^&1
echo --- java
java -version 2^>^&1
echo --- adb
adb version 2^>^&1
echo --- git
git --version 2^>^&1
echo --- ANDROID_HOME=%ANDROID_HOME%
echo --- IP
ipconfig | findstr /i "IPv4"
echo === end ===
) > check_pc.log 2>&1
