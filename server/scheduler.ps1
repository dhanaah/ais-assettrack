# Windows Task Scheduler: run every 5 minutes -> retries EBS / GCS queue. Sends the job key the server wrote to job.key.
$k = ""; $f = Join-Path $PSScriptRoot "job.key"; if (Test-Path $f) { $k = (Get-Content $f -Raw).Trim() }
Invoke-RestMethod -Method Post -Uri http://localhost:8001/api/v1/jobs/retry -Headers @{ "X-Job-Key" = $k } | Out-Null
