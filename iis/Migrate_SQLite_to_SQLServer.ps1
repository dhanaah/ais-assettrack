<#
AIS AssetTrack - copy the data of the tray / portable server (SQLite) into the SQL Server of the IIS installation.
One time, before HHTs move to the IIS server. Developed by DT

Run as Administrator on the IIS server, after iis\Setup_IIS.ps1:
  powershell -ExecutionPolicy Bypass -File iis\Migrate_SQLite_to_SQLServer.ps1 -SQLiteFile "\\TRAYPC\E$\AssetTrack\server\pallet.db"

- Stop the tray server first (or copy pallet.db while it is stopped), so the copy is complete.
- The SQL Server database must be new: a database that already holds plants / pallets / pick lists is never overwritten.
- secret.key (and job.key) next to pallet.db are copied too, so every printed QR and HHT sign-in stays valid.
- The tray server itself is not changed: it keeps its SQLite file and can be started again if ever needed.
#>
param(
    [Parameter(Mandatory = $true)][string]$SQLiteFile,
    [string]$SiteName = "AssetTrack"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Server = Join-Path $Root "server"
$Python = Join-Path $Root "python\python.exe"
$WebConfig = Join-Path $Server "web.config"
$AppCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
if (-not (Test-Path $SQLiteFile)) { Write-Host "SQLite file not found: $SQLiteFile" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $WebConfig)) { Write-Host "Run iis\Setup_IIS.ps1 first (server\web.config missing)" -ForegroundColor Red; exit 1 }
[xml]$wc = Get-Content $WebConfig -Raw
$db = ($wc.SelectNodes("//environmentVariable") | Where-Object { $_.name -eq "PALLET_DB_URL" } | Select-Object -First 1).value
if (-not $db -or $db -notmatch "^mssql") { Write-Host "web.config has no SQL Server PALLET_DB_URL - nothing to migrate to" -ForegroundColor Red; exit 1 }

# a private copy: the source file is only read
$tmp = Join-Path $env:TEMP ("assettrack_migrate_" + (Get-Date -Format yyyyMMddHHmmss) + ".db")
Copy-Item $SQLiteFile $tmp
foreach ($x in "-wal", "-shm") {       # recent changes may still sit in the write-ahead file next to pallet.db
    if (Test-Path "$SQLiteFile$x") { Copy-Item "$SQLiteFile$x" "$tmp$x" }
}
foreach ($k in "secret.key", "job.key") {
    $src = Join-Path (Split-Path $SQLiteFile) $k
    if (Test-Path $src) { Copy-Item $src (Join-Path (Split-Path $tmp) $k) -Force }
}
Write-Host "Stopping the IIS site while copying..."
$old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $AppCmd stop site /site.name:$SiteName 2>&1 | Out-Null
& $AppCmd stop apppool /apppool.name:$SiteName 2>&1 | Out-Null
Start-Sleep -Seconds 3
$env:PALLET_DB_URL = $db
& $Python (Join-Path $Server "sql\migrate_sqlite_to_mssql.py") $tmp $Server
$rc = $LASTEXITCODE
Remove-Item $tmp, "$tmp-wal", "$tmp-shm", (Join-Path (Split-Path $tmp) "secret.key"), (Join-Path (Split-Path $tmp) "job.key") -ErrorAction SilentlyContinue
& $AppCmd start apppool /apppool.name:$SiteName 2>&1 | Out-Null
& $AppCmd start site /site.name:$SiteName 2>&1 | Out-Null
$ErrorActionPreference = $old
if ($rc) { Write-Host "Migration stopped - nothing was overwritten. See the message above." -ForegroundColor Red; exit 1 }
Write-Host "Data copied, IIS site started again. Check: http://localhost/api/v1/health and sign in with your usual users." -ForegroundColor Green
