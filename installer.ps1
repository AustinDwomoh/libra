$failed = @()
Write-Host "Installing dependencies..." -ForegroundColor Cyan
Write-Host "Make sure it's in a virtual environment" -ForegroundColor Red
Read-Host "Press Enter to continue once your venv is active (Ctrl+C to cancel)"

if (-not $env:VIRTUAL_ENV) {
    Write-Host "No virtual environment detected. Create one first: `python -m venv $NameYouWant`. Or activate an existing one. ./venv(orwhatsoever)/Scripts/Activate" -ForegroundColor Red
    exit 1
}
Get-Content .\requirements.txt | Where-Object { $_ -notmatch '^\s*#' -and $_ -match '\S' } | ForEach-Object {
    $pkg = $_.Trim()
    Write-Host "Installing: $pkg" -ForegroundColor Cyan
    pip install $pkg 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $pkg" -ForegroundColor Red
        $failed += $pkg
    }
    else {
        Write-Host "OK: $pkg" -ForegroundColor Green
    }
}

Write-Host "`n--- FAILED PACKAGES ---" -ForegroundColor Yellow
$failed | ForEach-Object { Write-Host $_ -ForegroundColor Red }
$failed | Out-File -FilePath failed_packages.txt
Write-Host "`nFailed list saved to failed_packages.txt"

Write-Host "`n--- MANUAL INSTALLS ---" -ForegroundColor Cyan

Write-Host "Installing: asyncpg" -ForegroundColor Cyan
pip install asyncpg 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: asyncpg" -ForegroundColor Red; $failed += "asyncpg" } else { Write-Host "OK: asyncpg" -ForegroundColor Green }

Write-Host "Installing: pgvector" -ForegroundColor Cyan
pip install pgvector 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: pgvector" -ForegroundColor Red; $failed += "pgvector" } else { Write-Host "OK: pgvector" -ForegroundColor Green }

Write-Host "Installing: playwright" -ForegroundColor Cyan
pip install playwright 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: playwright" -ForegroundColor Red
    $failed += "playwright"
}
else {
    Write-Host "OK: playwright" -ForegroundColor Green
    playwright install 2>&1 | Out-Null
    playwright install-deps 2>&1 | Out-Null
}
Write-Host "Installing: ollama" -ForegroundColor Cyan
if ($IsMacOS) {
    Write-Host "Installing: ollama (macOS)" -ForegroundColor Cyan
    Invoke-WebRequest -fsSL https://ollama.com/install.sh | sh
    pip install ollama 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: ollama (python package)" -ForegroundColor Red
        $failed += "ollama"
    }
    else {
        Write-Host "OK: ollama (python package)" -ForegroundColor Green
        ollama pull qwen2.5:3b-instruct
    }
}
elseif ($IsWindows) {
    Invoke-RestMethod https://ollama.com/install.ps1 | Invoke-Expression    
    pip install ollama 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: ollama (python package)" -ForegroundColor Red
        $failed += "ollama"
    }
    else {
        Write-Host "OK: ollama (python package)" -ForegroundColor Green
        ollama pull qwen2.5:3b-instruct
    }
}
else {
    Write-Host "Unsupported OS for this ollama install step" -ForegroundColor Red
}