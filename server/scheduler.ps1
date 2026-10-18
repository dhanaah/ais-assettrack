# AIS AssetTrack - optional 5-minute job call (EBS / GCS retry queue, reminders) for Windows Task Scheduler. Developed by DT
# Not needed for the tray server (it runs the job itself) or for IIS set up by iis\Setup_IIS.ps1 (PALLET_RETRY_JOB=1).
#   powershell -File scheduler.ps1                          -> tray / console server on this PC (port 8001)
#   powershell -File scheduler.ps1 -Url http://localhost    -> IIS site on port 80
param([string]$Url = "http://localhost:8001")
$k = ""; $f = Join-Path $PSScriptRoot "job.key"; if (Test-Path $f) { $k = (Get-Content $f -Raw).Trim() }
Invoke-RestMethod -Method Post -Uri "$Url/api/v1/jobs/retry" -Headers @{ "X-Job-Key" = $k } | Out-Null
