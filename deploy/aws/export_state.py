"""Copy Jakenew's state from the EFS volume to S3 (rollback to Windows, or local analysis with cf_report/cf_replay).

Run as a one-off ECS task (the entrypoint runs it in DATA_DIR):
    command: ["export_state.py"]                 core state (journal, outbox, engine state)
    command: ["export_state.py", "--all"]        everything on the volume except locks/markers
Writes s3://<seed bucket>/export/<UTC timestamp>/..., derived from SEED_S3_URI. Download with
    aws s3 sync s3://<bucket>/export/<stamp>/ .
Refuses while a trading session holds the lock, so it never copies a database mid-write.
"""
import fcntl
import os
import sys
from datetime import datetime, timezone

CORE = ('jakenew_campaign_flow.db', 'jakenew_outbox.db', 'jakenew_state.json')
SKIP = ('.jakenew.lock', '.seeded', '.schwab_token_seed.sha256')


def main() -> int:
    import boto3
    seed = os.environ.get('SEED_S3_URI', '')
    if not seed.startswith('s3://'):
        print('SEED_S3_URI is not set', file=sys.stderr)
        return 2
    try:
        lk = open('.jakenew.lock', 'a+')
        fcntl.lockf(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('A trading session is running (lock held); export after it exits.', file=sys.stderr)
        return 75
    bucket = seed[len('s3://'):].split('/', 1)[0]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    if '--all' in sys.argv[1:]:
        files = [os.path.relpath(os.path.join(r, f), '.') for r, _, fs in os.walk('.') for f in fs]
        files = [f for f in files if os.path.basename(f) not in SKIP and not f.endswith('.part')]
    else:
        files = [f for f in CORE if os.path.exists(f)]
    s3 = boto3.client('s3')
    for f in sorted(files):
        key = f"export/{stamp}/{f.replace(os.sep, '/')}"
        s3.upload_file(f, bucket, key)
        print(f'exported {f}')
    print(f'done: s3://{bucket}/export/{stamp}/ ({len(files)} files)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
