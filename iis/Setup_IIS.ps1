<#
AIS AssetTrack - install / update the server on IIS (with SQL Server). Developed by DT

Run as Administrator on the IIS server, from the AssetTrack folder unzipped from AIS_AssetTrack_Server_Portable.zip
(e.g. C:\AssetTrack_IIS - a folder of its own, NOT the folder of the tray server, which keeps running as before):

  powershell -ExecutionPolicy Bypass -File iis\Setup_IIS.ps1 -SqlServer SQLSRV01\PALLET
  powershell -ExecutionPolicy Bypass -File iis\Setup_IIS.ps1 -SqlServer SQLSRV01 -SqlUser pallet_app -SqlPassword "..."

It uses the Python inside this folder (nothing to install), and does only what is missing:
  IIS + HttpPlatformHandler check, SQL Server database + login (-CreateDatabase), web.config, app pool (always running,
  no idle stop), site, folder rights, firewall rule, start and health check.
Running it again after unzipping a new version over the folder = update: settings in web.config are kept
(-Reconfigure writes them again from the parameters).
#>
param(
    [string]$SiteName = "AssetTrack",
    [int]$Port = 80,
    [string]$HostName = "",
    [string]$SqlServer = "",
    [string]$Database = "PalletDB",
    [string]$SqlUser = "",
    [string]$SqlPassword = "",
    [switch]$CreateDatabase,
    [string]$PublicName = "",
    [string]$IntegrationMode = "STUB",
    [switch]$StopDefaultSite,
    [switch]$Reconfigure,
    [switch]$UseSQLite
)
$ErrorActionPreference = "Stop"
function Say($t) { Write-Host "  $t" }
function Step($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host ""; Write-Host "STOPPED: $t" -ForegroundColor Red; exit 1 }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "run this as Administrator (right-click PowerShell > Run as administrator)"
}
$Root = Split-Path -Parent $PSScriptRoot
$Server = Join-Path $Root "server"
$Python = Join-Path $Root "python\python.exe"
$RunPy = Join-Path $Server "run.py"
$WebConfig = Join-Path $Server "web.config"
$Pool = $SiteName
$AppCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
function IISCmd {
    # appcmd with its messages captured (a "not found" from appcmd must not stop the script)
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $out = & $AppCmd @args 2>&1
    $ErrorActionPreference = $old
    return $out
}
Write-Host "AIS AssetTrack - IIS setup (Developed by DT)" -ForegroundColor Green
Say "folder: $Root"
if (-not (Test-Path $Python)) { Fail "python\python.exe not found - unzip AIS_AssetTrack_Server_Portable.zip and run this from its iis folder" }
if (-not (Test-Path $RunPy)) { Fail "server\run.py not found in $Root" }
if (Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path -like "$Root\python\*" -and $_.ProcessName -eq "pythonw" }) {
    Fail "the tray server of THIS folder is running - IIS needs a folder of its own (unzip the portable zip again into e.g. C:\AssetTrack_IIS)"
}

# ---------------------------------------------------------------- 1. IIS
Step "1. IIS"
if (-not (Test-Path $AppCmd)) {
    Say "IIS not installed - installing (Web Server + Management Console)..."
    if (Get-Command Install-WindowsFeature -ErrorAction SilentlyContinue) {
        Install-WindowsFeature Web-Server, Web-Mgmt-Console | Out-Null
    } else {
        Enable-WindowsOptionalFeature -Online -All -NoRestart -FeatureName IIS-WebServerRole, IIS-WebServer, IIS-ManagementConsole | Out-Null
    }
    if (-not (Test-Path $AppCmd)) { Fail "IIS could not be installed - ask IT to add the Web Server (IIS) role" }
}
Say "IIS ok"
$hph = Test-Path (Join-Path $env:windir "System32\inetsrv\httpPlatformHandler.dll")
$ancm = Test-Path (Join-Path $env:ProgramFiles "IIS\Asp.Net Core Module\V2\aspnetcorev2.dll")
if (-not $hph -and -not $ancm) {
    $msi = Get-ChildItem $PSScriptRoot -Filter "httpPlatformHandler*.msi" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($msi) {
        Say "installing $($msi.Name)..."
        $p = Start-Process msiexec.exe -ArgumentList "/i `"$($msi.FullName)`" /qn /norestart" -Wait -PassThru
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { Fail "HttpPlatformHandler install failed (code $($p.ExitCode))" }
        $hph = Test-Path (Join-Path $env:windir "System32\inetsrv\httpPlatformHandler.dll")
    }
}
if (-not $hph -and -not $ancm) {
    Fail ("IIS needs Microsoft's HttpPlatformHandler (or the ASP.NET Core Module) to run AssetTrack.`n" +
          "  Download httpPlatformHandler_amd64.msi from https://www.iis.net/downloads/microsoft/httpplatformhandler,`n" +
          "  put it in this iis folder and run this script again (it installs it).")
}
$Module = if ($hph) { "httpPlatformHandler" } else { "AspNetCoreModuleV2" }
Say "IIS module: $Module"

# ---------------------------------------------------------------- 2. SQL Server
Step "2. Database"
$DbUrl = ""
$Driver = ""
if ($UseSQLite) {
    Say "SQLite file in server\pallet.db (test installation only - production uses SQL Server)"
} elseif ($SqlServer) {
    foreach ($d in "ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server") {
        if (Test-Path "HKLM:\SOFTWARE\ODBC\ODBCINST.INI\$d") { $Driver = $d; break }
    }
    if (-not $Driver) { Fail "Microsoft 'ODBC Driver 18 for SQL Server' is not installed on this server - install it (Microsoft download), then run again" }
    Say "ODBC driver: $Driver"
    $drv = [uri]::EscapeDataString($Driver).Replace("%20", "+")
    if ($SqlUser) {
        $DbUrl = "mssql+pyodbc://$([uri]::EscapeDataString($SqlUser)):$([uri]::EscapeDataString($SqlPassword))@$SqlServer/$Database" + "?driver=$drv&TrustServerCertificate=yes"
    } else {
        $DbUrl = "mssql+pyodbc://@$SqlServer/$Database" + "?driver=$drv&trusted_connection=yes&TrustServerCertificate=yes"
    }
    if ($CreateDatabase) {
        if (-not $SqlUser -and -not ((IISCmd list apppool /name:$Pool) -match "^APPPOOL ")) {
            IISCmd add apppool /name:$Pool | Out-Null      # the pool's Windows login exists only once the pool exists
            Say "app pool $Pool created (its Windows login is given access to the database)"
        }
        Say "preparing SQL Server (database, settings, login) with your Windows login..."
        $a = @("$Server\sql\sqlserver_setup.py", "--server", $SqlServer, "--database", $Database, "--driver", $Driver)
        if ($SqlUser) { $a += @("--sql-user", $SqlUser, "--sql-password", $SqlPassword) }
        else {
            # Windows login of the app pool: on this server "IIS APPPOOL\<pool>"; seen from another SQL server it is the computer account
            $sqlHost = ($SqlServer -split "[\\,]")[0]
            $local = $sqlHost -in @(".", "localhost", "(local)", "127.0.0.1", $env:COMPUTERNAME)
            $a += @("--app-login", $(if ($local) { "IIS APPPOOL\$Pool" } else { "$env:USERDOMAIN\$env:COMPUTERNAME$" }))
        }
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & $Python @a 2>&1 | ForEach-Object { Say "$_" }
        $rc = $LASTEXITCODE; $ErrorActionPreference = $old
        if ($rc) { Fail "SQL Server preparation failed (see above) - or let the DBA run server\sql\create_db.sql" }
    }
} elseif (-not (Test-Path $WebConfig) -or $Reconfigure) {
    Fail "give -SqlServer <server\instance> (production), or -UseSQLite for a test installation"
}

# ---------------------------------------------------------------- 3. web.config (kept on update)
Step "3. Settings (server\web.config)"
if ((Test-Path $WebConfig) -and -not $Reconfigure) {
    Say "web.config exists - your settings are kept (use -Reconfigure to write them again)"
} else {
    if (Test-Path $WebConfig) { Copy-Item $WebConfig "$WebConfig.$(Get-Date -Format yyyyMMdd-HHmmss).bak" }
    $logs = Join-Path $Server "logs"; New-Item -ItemType Directory -Force $logs | Out-Null
    function X($s) { [Security.SecurityElement]::Escape($s) }
    $envs = [ordered]@{
        "PALLET_INTEGRATION_MODE" = $IntegrationMode
        "PALLET_RETRY_JOB"        = "1"
        "PALLET_SERVER_PORTS"     = "$Port"
        "PYTHONUNBUFFERED"        = "1"
    }
    if ($DbUrl) { $envs["PALLET_DB_URL"] = $DbUrl }
    if ($PublicName) { $envs["PUBLIC_NAME"] = $PublicName }
    $ev = ($envs.GetEnumerator() | ForEach-Object { "        <environmentVariable name=`"$($_.Key)`" value=`"$(X $_.Value)`" />" }) -join "`r`n"
    $proc = X $Python; $arg = X "`"$RunPy`""; $log = X (Join-Path $logs "iis_stdout")
    if ($Module -eq "httpPlatformHandler") {
        $body = @"
    <handlers>
      <add name="httpPlatformHandler" path="*" verb="*" modules="httpPlatformHandler" resourceType="Unspecified" />
    </handlers>
    <httpPlatform processPath="$proc" arguments="$arg" startupTimeLimit="120" startupRetryCount="3"
                  stdoutLogEnabled="true" stdoutLogFile="$log" requestTimeout="00:05:00" forwardWindowsAuthToken="false">
      <environmentVariables>
$ev
      </environmentVariables>
    </httpPlatform>
"@
    } else {
        $body = @"
    <handlers>
      <add name="aspNetCore" path="*" verb="*" modules="AspNetCoreModuleV2" resourceType="Unspecified" />
    </handlers>
    <aspNetCore processPath="$proc" arguments="$arg" hostingModel="outofprocess" startupTimeLimit="120"
                stdoutLogEnabled="true" stdoutLogFile="$log" requestTimeout="00:05:00">
      <environmentVariables>
$ev
      </environmentVariables>
    </aspNetCore>
"@
    }
    $xml = @"
<?xml version="1.0" encoding="utf-8"?>
<!-- AIS AssetTrack on IIS - written by iis\Setup_IIS.ps1 on $(Get-Date -Format "dd-MMM-yyyy HH:mm"). Developed by DT
     IIS starts the server (python run.py) and passes requests to it. This file is NOT in the zip, so updates keep it.
     Settings: PALLET_DB_URL (SQL Server), PALLET_INTEGRATION_MODE (STUB until EBS / GCS are live, then LIVE),
     PALLET_RETRY_JOB=1 (5-minute EBS / GCS / reminder job inside the server - no Task Scheduler needed). -->
<configuration>
  <system.webServer>
$body
    <security><requestFiltering><requestLimits maxAllowedContentLength="52428800" /></requestFiltering></security>
  </system.webServer>
</configuration>
"@
    Set-Content -Path $WebConfig -Value $xml -Encoding UTF8
    Say "web.config written"
}

# ---------------------------------------------------------------- 4. app pool + site
Step "4. IIS app pool and site '$SiteName'"
IISCmd unlock config -section:system.webServer/handlers | Out-Null
if ($Module -eq "httpPlatformHandler") { IISCmd unlock config -section:system.webServer/httpPlatform | Out-Null }
$poolExists = [bool]((IISCmd list apppool /name:$Pool) -match "^APPPOOL ")
if (-not $poolExists) { IISCmd add apppool /name:$Pool | Out-Null; Say "app pool created" }
IISCmd set apppool /apppool.name:$Pool /managedRuntimeVersion:"" /startMode:AlwaysRunning /processModel.idleTimeout:00:00:00 `
    /recycling.periodicRestart.time:00:00:00 /processModel.maxProcesses:1 /processModel.identityType:ApplicationPoolIdentity | Out-Null
Say "app pool: no .NET, always running, never idle-stopped, one process"
if ($StopDefaultSite -and ((IISCmd list site /name:"Default Web Site") -match "^SITE ")) {
    IISCmd stop site /site.name:"Default Web Site" | Out-Null
    IISCmd set site /site.name:"Default Web Site" /serverAutoStart:false | Out-Null
    Say "Default Web Site stopped"
}
$binding = "http/*:${Port}:$HostName"
$siteExists = [bool]((IISCmd list site /name:$SiteName) -match "^SITE ")
if (-not $siteExists) {
    $clash = IISCmd list site | Where-Object { $_ -match "http/\*:${Port}:$([regex]::Escape($HostName))[,)]" -and $_ -match "state:Started" }
    if ($clash) { Fail "port $Port is already used by: $clash`n  Use -Port 8080, a -HostName, or -StopDefaultSite" }
    if ($HostName) { $binding += ",http/*:${Port}:localhost" }      # also answers on this server as localhost (first admin sign-in, checks)
    IISCmd add site /name:$SiteName /bindings:$binding /physicalPath:$Server | Out-Null
    Say "site created: $binding"
} else {
    IISCmd set vdir "$SiteName/" /physicalPath:$Server | Out-Null
    Say "site exists - path checked"
}
IISCmd set app "$SiteName/" /applicationPool:$Pool /preloadEnabled:true | Out-Null

# ---------------------------------------------------------------- 5. rights, firewall
Step "5. Folder rights and firewall"
icacls $Server /grant "IIS AppPool\${Pool}:(OI)(CI)M" /T /C /Q | Out-Null
icacls (Join-Path $Root "python") /grant "IIS AppPool\${Pool}:(OI)(CI)RX" /T /C /Q | Out-Null
Say "app pool may change server\ (secret.key, logs, documents) and read python\"
if (-not (Get-NetFirewallRule -DisplayName "AIS AssetTrack IIS $Port" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "AIS AssetTrack IIS $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
    Say "firewall: port $Port open (inbound)"
}

# ---------------------------------------------------------------- 6. start + check
Step "6. Start and check"
IISCmd recycle apppool /apppool.name:$Pool | Out-Null
IISCmd start apppool /apppool.name:$Pool | Out-Null
IISCmd start site /site.name:$SiteName | Out-Null
$url = "http://localhost:$Port"
$ok = $false; $h = $null
for ($i = 0; $i -lt 45 -and -not $ok; $i++) {
    Start-Sleep -Seconds 4
    try {
        $h = Invoke-RestMethod -Uri "$url/api/v1/health" -UseBasicParsing -TimeoutSec 20
        $ok = $h.db -eq "ok"
    } catch { }
}
if (-not $ok) {
    Write-Host ""
    Write-Host "The site did not answer as expected. Last lines of the server log:" -ForegroundColor Yellow
    Get-ChildItem (Join-Path $Server "logs") -Filter "iis_stdout*" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1 |
        ForEach-Object { Get-Content $_.FullName -Tail 25 }
    if ($h) { Write-Host "health: $($h | ConvertTo-Json -Compress)" }
    Fail "check the log above (database login, ODBC driver, folder rights)"
}
Write-Host ""
$dbKind = if ((Get-Content $WebConfig -Raw) -match "mssql\+pyodbc") { "SQL Server" } else { "SQLite (test)" }
Write-Host "READY - AIS AssetTrack $($h.version) on IIS, database: $dbKind" -ForegroundColor Green
$name = if ($HostName) { $HostName } elseif ($PublicName) { $PublicName } else { $env:COMPUTERNAME }
$p = if ($Port -eq 80) { "" } else { ":$Port" }
Say "Web:        http://$name$p   (first sign-in admin / Admin@123 here on this server: http://localhost$p)"
Say "HHT setup:  http://$name$p/hht-setup   (scan the QR on each HHT: Setup > 1. Server)"
Say "Existing data from the tray server: iis\Migrate_SQLite_to_SQLServer.ps1"
Say "Keep server\secret.key and server\web.config in your backups."
