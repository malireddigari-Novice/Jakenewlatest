# Upload the DAG to the existing MWAA environment's DAG folder and set the `jakenew_ecs` Airflow Variable.
# Usage:  .\deploy\aws\scripts\upload_dag.ps1 -Region us-east-1 -Environment <mwaa-env-name> -StackName jakenew
param([Parameter(Mandatory = $true)][string]$Region, [Parameter(Mandatory = $true)][string]$Environment,
      [string]$StackName = 'jakenew')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..\..").Path

$env_ = aws mwaa get-environment --name $Environment --region $Region --output json | ConvertFrom-Json
$bucket = ($env_.Environment.SourceBucketArn -split ':::')[1]
$dagPath = $env_.Environment.DagS3Path.TrimEnd('/')
aws s3 cp (Join-Path $root 'deploy\aws\dags\jakenew_daily_session.py') "s3://$bucket/$dagPath/jakenew_daily_session.py" --region $Region
if ($LASTEXITCODE -ne 0) { throw "DAG upload failed" }
Write-Host "DAG uploaded to s3://$bucket/$dagPath/ (MWAA picks it up within ~1 min; it starts PAUSED unless your env unpauses new DAGs)."

$var = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='AirflowVariableJson'].OutputValue" --output text
# Airflow CLI through the MWAA CLI token endpoint.
$tok = aws mwaa create-cli-token --name $Environment --region $Region --output json | ConvertFrom-Json
$cmd = "variables set jakenew_ecs '$var'"
$resp = Invoke-RestMethod -Method Post -Uri "https://$($tok.WebServerHostname)/aws_mwaa/cli" `
    -Headers @{ Authorization = "Bearer $($tok.CliToken)"; 'Content-Type' = 'text/plain' } -Body $cmd
$out = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($resp.stdout))
$err = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($resp.stderr))
if ($err -and $err -notmatch 'Variable jakenew_ecs') { Write-Warning $err }
Write-Host "Airflow Variable jakenew_ecs set: $var"
Write-Host $out
