@echo off
set "HERE=%~dp0"
rem Quick health + login check against a running server
call "%HERE%_common.bat"
curl -s http://localhost:%PORT%/api/v1/health
echo.
curl -s -X POST http://localhost:%PORT%/api/v1/auth/login -H "Content-Type: application/json" -d "{\"user_id\":\"admin\",\"password\":\"Admin@123\"}" | findstr /c:"token" >nul && echo LOGIN OK || echo LOGIN FAILED (changed password? server down?)
pause
