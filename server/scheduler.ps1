# Windows Task Scheduler: run every 5 minutes -> retries EBS / GCS queue
Invoke-RestMethod -Method Post -Uri http://localhost:8001/api/v1/jobs/retry | Out-Null
