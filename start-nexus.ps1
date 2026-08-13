$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverDir = Join-Path $projectRoot "server"
$venvPython = Join-Path $serverDir ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python).Source }
$npm = (Get-Command npm.cmd -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source

Write-Host "NEXUS // checking local dependencies" -ForegroundColor Yellow
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "node_modules"))) {
    Write-Host "Installing frontend dependencies..."
    & $npm install
}

$backendOut = Join-Path $env:TEMP "nexus-backend.stdout.log"
$backendErr = Join-Path $env:TEMP "nexus-backend.stderr.log"
$backend = Start-Process -FilePath $python `
    -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000") `
    -WorkingDirectory $serverDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru

try {
    Write-Host "Backend started (PID $($backend.Id)). Opening frontend at http://127.0.0.1:3000" -ForegroundColor Green
    # Invoke npm.cmd explicitly: invoking the PowerShell npm wrapper can misparse
    # forwarded Vite arguments in some Windows shells (for example as "pm").
    & $npm run dev -- --host 127.0.0.1 --port 3000
}
finally {
    if (-not $backend.HasExited) {
        Stop-Process -Id $backend.Id
    }
    Write-Host "NEXUS stopped. Backend logs: $backendOut / $backendErr"
}
