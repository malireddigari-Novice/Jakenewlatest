# One-time copy of this machine's Jakenew state to the seed bucket. The first ECS session copies it onto EFS
# (never overwriting files already there) and marks /data/.seeded.
# Run it AFTER the close, with the Windows task finished and disabled, so the state does not change underneath.
#   Required: campaign-flow journal (open positions, e.g. a carried TSLA call), Discord outbox (no re-posted
#             cards), engine state.
#   Optional: -IncludeLedgers  decision / candidate ledgers (research archives, ~190 MB)
#             -IncludeObs      cf_obs observation logs (replay archive, ~2 GB)
# Usage:  .\deploy\aws\scripts\seed_state.ps1 -Region us-east-1 -Bucket <SeedBucketName> [-IncludeLedgers] [-IncludeObs]
param([Parameter(Mandatory = $true)][string]$Region, [Parameter(Mandatory = $true)][string]$Bucket,
      [switch]$IncludeLedgers, [switch]$IncludeObs)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..\..").Path
Set-Location $root

$running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'main\.py' }
if ($running) { throw "Jakenew is still running locally (PID $($running.ProcessId)); seed after it exits." }

$files = @('jakenew_campaign_flow.db', 'jakenew_outbox.db', 'jakenew_state.json')
if ($IncludeLedgers) { $files += @('jakenew_decisions.jsonl', 'jakenew_candidates.jsonl') }
foreach ($f in $files) {
    if (Test-Path $f) {
        aws s3 cp $f "s3://$Bucket/seed/$f" --region $Region --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw "upload of $f failed" }
        Write-Host "seeded $f"
    } else { Write-Warning "$f not found (skipped)" }
}
if ($IncludeObs -and (Test-Path cf_obs)) {
    aws s3 sync cf_obs "s3://$Bucket/seed/cf_obs" --region $Region --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw "upload of cf_obs failed" }
    Write-Host "seeded cf_obs/"
}
