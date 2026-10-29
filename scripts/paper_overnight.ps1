# Launch the ai_trader paper-trading daemon detached, with the overnight configuration.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\paper_overnight.ps1
# Stop:   taskkill /PID (Get-Content data\paper-run.pid) /T /F
param(
    [string]$Repo = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
)

$ErrorActionPreference = "Stop"
Set-Location $Repo
New-Item -ItemType Directory -Force -Path (Join-Path $Repo "data") | Out-Null

# When launched detached (WMI / Task Scheduler) the user PATH may be missing: resolve uv explicitly.
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path $uv)) { $uv = "C:\Users\cee\.local\bin\uv.exe" }

# --- overnight configuration (environment overrides; committed defaults stay conservative) ---
$env:NEWS__RSS_FEEDS = '["https://www.coindesk.com/arc/outboundfeeds/rss/","https://cointelegraph.com/rss","https://decrypt.co/feed","https://www.theblock.co/rss.xml","https://cryptoslate.com/feed/","https://www.newsbtc.com/feed/","https://beincrypto.com/feed/","https://news.bitcoin.com/feed/","https://cryptonews.com/news/feed/","https://www.federalreserve.gov/feeds/press_all.xml","https://www.sec.gov/news/pressreleases.rss","https://feeds.bloomberg.com/crypto/news.rss","https://www.investing.com/rss/news_301.rss","https://u.today/rss"]'
$env:DETECTORS__NEWS_MIN_CONFIDENCE = "0.3"
$env:DETECTORS__LIQUIDATION_NOTIONAL_THRESHOLD_USDT = "10000"
$env:LOG_JSON = "false"
$env:LOG_LEVEL = "INFO"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $Repo "data\paper-run-$stamp.log"
$err = Join-Path $Repo "data\paper-run-$stamp.err.log"
Start-Transcript -Path (Join-Path $Repo "data\launcher-$stamp.log") -Force | Out-Null
"uv=$uv user=$env:USERNAME"

$p = Start-Process -FilePath $uv -ArgumentList "run", "ai-trader", "run", "--mode", "paper" `
    -WorkingDirectory $Repo -RedirectStandardOutput $log -RedirectStandardError $err `
    -WindowStyle Hidden -PassThru

$p.Id | Set-Content (Join-Path $Repo "data\paper-run.pid")
"$stamp" | Set-Content (Join-Path $Repo "data\paper-run.latest")
Write-Output "started pid=$($p.Id) log=$log"
Stop-Transcript | Out-Null
