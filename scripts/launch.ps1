param([switch]$NoBrowser)   # -NoBrowser: start the server, leave the browser alone

$ErrorActionPreference = "Stop"
$viewerDir = Split-Path -Parent $PSScriptRoot   # scripts\ -> sst_viewer\
$py = "C:\Users\Georgii\miniconda3\envs\mfa_env\python.exe"
$port = 8000
$url = "http://localhost:$port"

function Test-Port {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $port)
        $c.Close()
        return $true
    } catch { return $false }
}

# uvicorn runs without --reload, so a server left over from before an edit is
# still serving the old app.py / datasets.py / reports.py. Always replace it
# rather than reusing it -- a launch means a fresh instance.
$old = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($old) {
    $old.OwningProcess | Select-Object -Unique | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
    for ($i = 0; $i -lt 10; $i++) {
        if (-not (Test-Port)) { break }
        Start-Sleep -Seconds 1
    }
    Write-Output "stopped the previous sst_viewer instance"
}

$cacheDir = if ($env:SST_CACHE) { $env:SST_CACHE } else { Join-Path $HOME "sst_cache" }
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
$log = Join-Path $cacheDir "uvicorn.log"
$errLog = Join-Path $cacheDir "uvicorn.err.log"
Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "app:app", "--port", "$port" `
    -WorkingDirectory $viewerDir -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError $errLog

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Port) { $ready = $true; break }
}
if (-not $ready) {
    Write-Output "Server did not come up within 30s -- check $errLog"
    exit 1
}
Write-Output "sst_viewer started at $url"

if (-not $NoBrowser) { Start-Process $url }
