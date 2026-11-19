# One-Click Deployment Script for news.dylangonzalez.dev / info.dylangonzalez.dev
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$PYTHON = "C:\Users\dylcg\AppData\Local\Python\bin\python.exe"
if (-not (Test-Path $PYTHON)) {
    $PYTHON = "python"
}

$AWS_CLI = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
if (-not (Test-Path $AWS_CLI)) {
    $AWS_CLI = "aws"
}

Write-Host "[1/3] Running News & Intelligence Ingestion Engine..." -ForegroundColor Cyan
& $PYTHON "$PSScriptRoot\collector.py"

Write-Host "`n[2/3] Syncing updated feed & assets to S3 bucket info.dylangonzalez.dev..." -ForegroundColor Cyan
& $AWS_CLI s3 sync "$PSScriptRoot" s3://info.dylangonzalez.dev `
    --delete `
    --exclude ".git/*" `
    --exclude ".github/*" `
    --exclude ".gitignore" `
    --exclude "*.py" `
    --exclude "*.sql" `
    --exclude "*.db*" `
    --exclude "README.md" `
    --exclude "LEGAL.md" `
    --exclude "deploy.ps1" `
    --exclude "setup_windows_task.ps1" `
    --exclude "__pycache__/*"

Write-Host "`n[3/3] Creating CloudFront Cache Invalidation for EW0A0BPO9NQCN..." -ForegroundColor Cyan
& $AWS_CLI cloudfront create-invalidation --distribution-id EW0A0BPO9NQCN --paths "/*"

Write-Host "`n[+] Deployment complete! Fresh feed live at https://news.dylangonzalez.dev" -ForegroundColor Green
