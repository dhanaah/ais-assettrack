@echo off
set "HERE=%~dp0"
rem Run the server with EBS/GCS integrations switched OFF to rehearse the contingency path (retry queue)
set PALLET_INTEGRATION_MODE=OFF
call "%HERE%server_run.bat"
