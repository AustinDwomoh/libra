$failed = @()

Get-Content .\requirements.txt | Where-Object { $_ -notmatch '^\s*#' -and $_ -match '\S' } | ForEach-Object {
    $pkg = $_.Trim()
    Write-Host "Installing: $pkg" -ForegroundColor Cyan
    pip install $pkg 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $pkg" -ForegroundColor Red
        $failed += $pkg
    } else {
        Write-Host "OK: $pkg" -ForegroundColor Green
    }
}

Write-Host "`n--- FAILED PACKAGES ---" -ForegroundColor Yellow
$failed | ForEach-Object { Write-Host $_ -ForegroundColor Red }
$failed | Out-File -FilePath failed_packages.txt
Write-Host "`nFailed list saved to failed_packages.txt"