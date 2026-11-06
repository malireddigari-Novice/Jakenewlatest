# Jakenew on AWS: MWAA schedules, ECS Fargate runs

This replaces the Windows scheduled task `Jakenew_DailyRun`.

**Schedule.** Same as today: every weekday at **08:10 America/Chicago**, which is 09:10 ET. Daylight saving is
handled automatically.

**What runs where:**
- An existing **MWAA** environment owns the schedule.
- The DAG `jakenew_daily_session` launches the Jakenew image as an **ECS Fargate** task and waits for it to finish.
  It waits in deferred mode, so no Airflow worker is held for the ~7 h session.
- The container runs the unchanged `main.py`. That process exits by itself after the close, or at once on an
  exchange holiday.

```
MWAA (cron 10 8 * * 1-5, America/Chicago)
  └─ EcsRunTaskOperator ─► Fargate task "jakenew"
                              image  : ECR jakenew:latest  (code, no secrets)
                              /data  : EFS (journal, outbox, state, cf_obs, logs) — persists between days
                              secrets: Secrets Manager → env (.env text, Google key, optional Schwab token)
                              logs   : CloudWatch /ecs/jakenew  (also shown in the Airflow task log)
```

| File | Purpose |
|---|---|
| `Dockerfile`, `requirements-aws.txt`, `/.dockerignore` | Python 3.13 image. Secrets, databases and logs are kept out of it. |
| `entrypoint.py` | Runs in the container, in order: EFS working dir, single-copy lock, first-run seed from S3, secrets to files, then `main.py`. |
| `dags/jakenew_daily_session.py` | The MWAA DAG. |
| `cloudformation/jakenew-ecs.yaml` | ECR, ECS cluster and task definition, EFS (backed up), secrets, seed bucket, IAM, and the MWAA role's permission to run the task. |
| `scripts/*.ps1` | Build and push, upload secrets, seed state, upload the DAG and set its Variable. |

## Prerequisites (on the machine you deploy from)
- AWS CLI v2, configured with credentials that can create the stack (`aws configure`).
- Docker Desktop.
- The existing MWAA environment needs:
  - Airflow **2.7 or newer**. The DAG uses deferrable operators, which need the triggerer that MWAA runs.
  - The bundled `apache-airflow-providers-amazon`.
- Note its environment name, its execution role name, and two of its private subnets in different AZs. Those
  subnets already have outbound internet through NAT, which MWAA itself needs.

## One-time deployment
Run these from the repo root in PowerShell. Replace the placeholders.

```powershell
$R = 'us-east-1'                     # the MWAA environment's region

# 1. Infrastructure
aws cloudformation deploy --region $R --stack-name jakenew `
  --template-file deploy/aws/cloudformation/jakenew-ecs.yaml --capabilities CAPABILITY_IAM `
  --parameter-overrides VpcId=vpc-xxxx SubnetA=subnet-aaaa SubnetB=subnet-bbbb `
                        MwaaExecutionRoleName=<mwaa-execution-role-name> AssignPublicIp=DISABLED
aws cloudformation describe-stacks --region $R --stack-name jakenew --query "Stacks[0].Outputs" --output table

# 2. Secrets (.env and the Google service-account key; nothing is printed)
.\deploy\aws\scripts\put_secrets.ps1 -Region $R

# 3. Image
.\deploy\aws\scripts\build_and_push.ps1 -Region $R

# 4. DAG + Airflow Variable `jakenew_ecs`
.\deploy\aws\scripts\upload_dag.ps1 -Region $R -Environment <mwaa-env-name>
```

## Cutover from Windows (after the close, one evening)
Only **one** runner may be live. Two runners would each send orders to the same Alpaca paper account and post
duplicate cards to Discord.

1. Make sure today's Windows session has exited ("Jakenew stopped." in `jakenew.log`).
2. Disable the Windows task. Run this from an **elevated** PowerShell:
   `Disable-ScheduledTask -TaskName Jakenew_DailyRun`.
3. Seed the state, so open positions, the Discord dedupe and engine state carry over:
   `.\deploy\aws\scripts\seed_state.ps1 -Region $R -Bucket <SeedBucketName>`.
   Add `-IncludeLedgers` and/or `-IncludeObs` to also copy the research ledgers and the 2 GB replay archive.
4. Smoke test: in Airflow, **unpause** `jakenew_daily_session` and **trigger it manually now** (after hours).
   The task should:
   - copy the seed
   - start the engine
   - log `Session complete for <date>` or `<date> is not a trading day`
   - exit 0, which shows as green in Airflow

   This proves image, network, EFS, secrets and IAM work without placing any orders. Check the CloudWatch log
   for `Seeded N file(s)` and `Jakenew ready — LIVE execution`.
5. Leave the DAG unpaused. The next weekday 08:10 CT run is the first live session.

**Rollback:**
1. Pause the DAG.
2. Re-enable the Windows task.
3. Bring the state back first if AWS sessions have run since the cutover:
   - Run a one-off task with command `["export_state.py"]` (see below).
   - Download it with `aws s3 sync s3://<SeedBucketName>/export/<stamp>/ .` while the Windows task is still
     disabled.

## Day-to-day
- **Deploy new code:** commit, then run `build_and_push.ps1`. The next session pulls `:latest`; the previous image
  stays tagged `:<git sha>`. Like the Windows run, a session never changes code mid-day.
- **Logs:** CloudWatch log group `/ecs/jakenew`, and the same lines in the Airflow task log.
  `/data/jakenew.log` on EFS keeps the full file as before.
- **Reports and replays against the live state:** run a one-off task. The entrypoint runs any repo script
  instead of `main.py`, without the lock or seed:
  ```powershell
  aws ecs run-task --region $R --cluster jakenew --launch-type FARGATE --task-definition jakenew `
    --network-configuration "awsvpcConfiguration={subnets=[subnet-aaaa,subnet-bbbb],securityGroups=[sg-task],assignPublicIp=DISABLED}" `
    --overrides '{"containerOverrides":[{"name":"jakenew","command":["cf_report.py","2026-11-06"]}]}'
  ```
- **Pull the live journal down for local analysis:** run the same kind of one-off task with
  `["export_state.py"]`, or `["export_state.py","--all"]` to include `cf_obs` and the logs. Then sync
  `s3://<SeedBucketName>/export/<stamp>/`. The export refuses to run while a session holds the lock.
- **Changing a strategy flag:** edit `.env` locally, then run `put_secrets.ps1`. The next session uses it.
- **Schwab (optional):** it is off today; there is no token. To turn it on:
  1. Run `python schwab_reauth.py` locally. It needs a browser and expires about weekly.
  2. Run `put_secrets.ps1 -Region $R -SchwabOnly`.

  The container installs a newly uploaded token once. Between uploads, schwab-py refreshes the token in place
  on EFS.
- **Retries and safety:**
  - A crashed session is relaunched up to twice, 3 minutes apart. Campaign flow rebuilds the day from its
    observation log on EFS.
  - Two things stop a retry from running beside a live task: `reattach=True`, and the EFS lock (exit code 75).
  - `catchup=False`: a missed day is never replayed late.
- **Holidays and early closes:** handled by `main.py`, unchanged.

## Cost (indicative, us-east-1)
| Item | Basis | Per month |
|---|---|---|
| Fargate, 1 vCPU / 2 GB | ~7 h × ~21 sessions | ≈ $7 |
| EFS + backups | ~1–3 GB | ≈ $1 |
| Secrets Manager | 3 secrets | ≈ $1.20 |
| CloudWatch Logs | ~60 MB/day ingested | ≈ $1 |
| ECR | ~20 images | < $1 |

The MWAA environment is existing, so it adds no new cost. If the subnets reach the internet through NAT,
the data processed there adds a little.
