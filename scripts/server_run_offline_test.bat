@echo off
rem Run the server with EBS/GCS integrations switched OFF to rehearse the contingency path (retry queue)
set PALLET_INTEGRATION_MODE=OFF
call "%~dp0server_run.bat"
