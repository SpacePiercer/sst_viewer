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

if (Test-Port) {
    Write-Output "sst_viewer already running at $url"
} else {
    New-Item -ItemType Directory -Force -Path (Join-Path $viewerDir "cache") | Out-Null
    $log = Join-Path $viewerDir "cache\uvicorn.log"
    $errLog = Join-Path $viewerDir "cache\uvicorn.err.log"
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
}

Start-Process $url
