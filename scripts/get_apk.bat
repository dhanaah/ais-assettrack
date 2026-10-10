@echo off
rem Downloads the latest AIS AssetTrack HHT app (APK) from the GitHub release - permanent link, no expiring URL.
rem Uses Windows networking (same company proxy as the browser). Saves to dist\ and server\apk\ (HHT update prompt).
rem Developed by DT
set "HERE=%~dp0"
cd /d "%HERE%"
set "URL=https://github.com/dhanaah/ais-assettrack/releases/latest/download/AIS_AssetTrack_HHT.apk"
set "PAGE=https://github.com/dhanaah/ais-assettrack/releases/latest"
if not exist "..\dist" mkdir "..\dist"
echo Downloading the latest HHT app ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "$p=[Net.WebRequest]::GetSystemWebProxy(); $p.Credentials=[Net.CredentialCache]::DefaultNetworkCredentials; [Net.WebRequest]::DefaultWebProxy=$p;" ^
  "$r=Invoke-WebRequest -UseBasicParsing -Uri '%PAGE%' -MaximumRedirection 0 -ErrorAction SilentlyContinue; $tag=($r.Headers.Location -split '/')[-1];" ^
  "$v=$tag -replace '^hht-v',''; if(-not $v){$v='latest'}; $out='..\dist\AIS_AssetTrack_HHT_v'+$v+'.apk';" ^
  "Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile $out; Set-Content -Path 'apk_last.txt' -Value $out; Write-Host ('Saved ' + $out)" 2> "%HERE%get_apk.log"
if errorlevel 1 (
  echo.
  echo DOWNLOAD FAILED - details in scripts\get_apk.log
  echo Opening the download page in your browser instead - click AIS_AssetTrack_HHT.apk there.
  start "" "%PAGE%"
  pause
  exit /b 1
)
if not exist "..\server\apk" mkdir "..\server\apk"
set /p LAST=<apk_last.txt
del apk_last.txt
copy /y "%LAST%" "..\server\apk\" >nul 2>nul
echo APK also placed in server\apk - the HHTs now see "update available" and can download it from the server.
start "" explorer "%HERE%..\dist"
