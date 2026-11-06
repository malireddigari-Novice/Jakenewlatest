# Copy Jakenew's secrets from this machine into the Secrets Manager entries the stack created.
# Values are read from files and sent straight to AWS; nothing is printed.
#   jakenew/dotenv        <- .env                                  (always)
#   jakenew/google-sa     <- the GOOGLE_SERVICE_ACCOUNT_FILE named in .env (if present)
#   jakenew/schwab-token  <- schwab_token.json                     (only with -Schwab; after schwab_reauth.py)
# Usage:  .\deploy\aws\scripts\put_secrets.ps1 -Region us-east-1 [-Schwab] [-SchwabOnly]
param([Parameter(Mandatory = $true)][string]$Region, [switch]$Schwab, [switch]$SchwabOnly)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..\..").Path

function Put([string]$id, [string]$file) {
    if (-not (Test-Path $file)) { throw "$file not found" }
    aws secretsmanager put-secret-value --region $Region --secret-id $id --secret-string "file://$file" --output text --query VersionId | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "failed to update $id" }
    Write-Host "updated $id from $(Split-Path $file -Leaf)"
}

if (-not $SchwabOnly) {
    $envFile = Join-Path $root '.env'
    Put 'jakenew/dotenv' $envFile
    $sa = (Select-String -Path $envFile -Pattern '^\s*GOOGLE_SERVICE_ACCOUNT_FILE\s*=\s*(\S+)' | Select-Object -First 1)
    if ($sa) {
        $saFile = Join-Path $root $sa.Matches[0].Groups[1].Value
        Put 'jakenew/google-sa' $saFile
    } else {
        Write-Warning "GOOGLE_SERVICE_ACCOUNT_FILE not set in .env; the alerts sheet will be disabled in AWS."
    }
}
if ($Schwab -or $SchwabOnly) {
    Put 'jakenew/schwab-token' (Join-Path $root 'schwab_token.json')
}
