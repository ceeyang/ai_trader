# Launch the read-only ai_trader web dashboard detached (http://127.0.0.1:8787/ by default).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\dashboard.ps1 [-Port 8787]
# Stop:   taskkill /PID (Get-Content data\dashboard.pid) /T /F
param(
    [string]$Repo = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
    [int]$Port = 8787,
    [string]$BindHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
Set-Location $Repo
New-Item -ItemType Directory -Force -Path (Join-Path $Repo "data") | Out-Null

# When launched detached (WMI / Task Scheduler) the user PATH may be missing: resolve uv explicitly.
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path $uv)) { $uv = "C:\Users\cee\.local\bin\uv.exe" }

$log = Join-Path $Repo "data\dashboard.log"
$err = Join-Path $Repo "data\dashboard.err.log"
"uv=$uv user=$env:USERNAME"

# --no-sync: a running paper daemon holds the venv's ai-trader.exe open; never re-sync under it.
$p = Start-Process -FilePath $uv `
    -ArgumentList "run", "--no-sync", "ai-trader", "dashboard", "--host", $BindHost, "--port", "$Port" `
    -WorkingDirectory $Repo -RedirectStandardOutput $log -RedirectStandardError $err `
    -WindowStyle Hidden -PassThru

$p.Id | Set-Content (Join-Path $Repo "data\dashboard.pid")
Write-Output "started dashboard pid=$($p.Id) url=http://${BindHost}:$Port/ log=$log"
