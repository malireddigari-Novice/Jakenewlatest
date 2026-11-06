# Build the Jakenew image from the repo root and push it to ECR as :latest and :<git sha>.
# The ECS task runs :latest, so the next scheduled session picks up the new code (no task-definition change).
# Usage:  .\deploy\aws\scripts\build_and_push.ps1 -Region us-east-1
param([Parameter(Mandatory = $true)][string]$Region)
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path "$PSScriptRoot\..\..\..").Path
Set-Location $root
$dirty = git status --porcelain --untracked-files=no
if ($dirty) { Write-Warning "Uncommitted changes are included in the image; CODE_VERSION will not match a commit." }
$sha = (git rev-parse --short=12 HEAD).Trim()
$account = (aws sts get-caller-identity --query Account --output text).Trim()
$repo = "$account.dkr.ecr.$Region.amazonaws.com/jakenew"

docker build -f deploy/aws/Dockerfile --build-arg CODE_VERSION=$sha -t "jakenew:$sha" .
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }

aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin "$account.dkr.ecr.$Region.amazonaws.com"
if ($LASTEXITCODE -ne 0) { throw "ECR login failed" }

foreach ($tag in @($sha, 'latest')) {
    docker tag "jakenew:$sha" "${repo}:$tag"
    docker push "${repo}:$tag"
    if ($LASTEXITCODE -ne 0) { throw "push of $tag failed" }
}
Write-Host "Pushed ${repo}:$sha and :latest"
