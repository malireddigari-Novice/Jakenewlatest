"""Container entrypoint for one Jakenew trading session on ECS Fargate (launched daily by the MWAA DAG).

Steps, in order:
  1. Work in DATA_DIR (the EFS mount): every relative state path in config (campaign-flow journal, Discord outbox,
     engine state, ledgers, cf_obs, Schwab token, logs) lands on persistent storage and survives between days.
  2. Take an exclusive lock on DATA_DIR/.jakenew.lock. A second copy (an Airflow retry racing a task that is still
     running) exits at once with code 75 instead of trading the same paper account twice.
  3. First run only: copy the seed state uploaded by seed_state.ps1 from SEED_S3_URI into DATA_DIR (existing
     files are never overwritten), then mark DATA_DIR/.seeded.
  4. Materialize secrets injected by ECS from Secrets Manager:
       JAKENEW_DOTENV     full .env text      -> SECRETS_DIR/jakenew.env  (DOTENV_PATH; real env vars still win)
       GOOGLE_SA_JSON     service-account key -> SECRETS_DIR/google_sa.json (GOOGLE_SERVICE_ACCOUNT_FILE)
       SCHWAB_TOKEN_JSON  optional token      -> DATA_DIR/<SCHWAB_TOKEN_FILE>, only when the uploaded value
                          changed since the last seed (schwab-py refreshes the file in place between uploads)
  5. Run main.py in-process, with SIGTERM (ECS stop) mapped to KeyboardInterrupt so the session exits cleanly.

One-off tools: `entrypoint.py <script.py> [args]` runs another repo script the same way against the state volume
(e.g. a one-off ECS task with command ["cf_report.py", "2026-11-06"]). Only main.py takes the lock and seeds.

Exit codes: main.py's own (0 = session complete / not a trading day, 1 = startup failure), 75 = lock held.
"""
import fcntl
import hashlib
import json
import logging
import os
import runpy
import signal
import sys

APP_DIR = os.environ.get('APP_DIR', '/app')        # where the image puts the code (main.py, config.py, ...)
DATA_DIR = os.environ.get('DATA_DIR', '/data')
SECRETS_DIR = os.environ.get('SECRETS_DIR', '/tmp')     # container-local, never the state volume
log = logging.getLogger('entrypoint')


def _write_private(path: str, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(text)


def _lock():
    fh = open(os.path.join(DATA_DIR, '.jakenew.lock'), 'a+')
    try:
        fcntl.lockf(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("Another Jakenew session holds %s/.jakenew.lock — refusing to start a second copy.", DATA_DIR)
        sys.exit(75)
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} task={os.environ.get('ECS_CONTAINER_METADATA_URI_V4', '-')}\n")
    fh.flush()
    return fh                                   # keep the handle open for the life of the process


def _seed() -> None:
    uri = os.environ.get('SEED_S3_URI', '').strip()
    marker = os.path.join(DATA_DIR, '.seeded')
    if not uri or os.path.exists(marker):
        return
    import boto3
    bucket, _, prefix = uri[len('s3://'):].partition('/')
    s3 = boto3.client('s3')
    n = 0
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents') or []:
            rel = obj['Key'][len(prefix):].lstrip('/')
            if not rel or rel.endswith('/'):
                continue
            dest = os.path.join(DATA_DIR, rel)
            if os.path.exists(dest):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            s3.download_file(bucket, obj['Key'], dest + '.part')
            os.replace(dest + '.part', dest)
            n += 1
    with open(marker, 'w') as fh:
        fh.write(json.dumps({'source': uri, 'files': n}))
    log.info("Seeded %d file(s) from %s", n, uri)


def _secrets() -> None:
    dotenv = os.environ.pop('JAKENEW_DOTENV', '')
    if dotenv.strip():
        path = os.path.join(SECRETS_DIR, 'jakenew.env')
        _write_private(path, dotenv)
        os.environ['DOTENV_PATH'] = path
    else:
        log.warning("JAKENEW_DOTENV is empty — running on code defaults plus task environment only.")
    sa = os.environ.pop('GOOGLE_SA_JSON', '')
    if sa.strip().startswith('{'):
        path = os.path.join(SECRETS_DIR, 'google_sa.json')
        _write_private(path, sa)
        os.environ['GOOGLE_SERVICE_ACCOUNT_FILE'] = path
    tok = os.environ.pop('SCHWAB_TOKEN_JSON', '')
    if tok.strip().startswith('{'):
        name = os.environ.get('SCHWAB_TOKEN_FILE', 'schwab_token.json')
        seen = os.path.join(DATA_DIR, '.schwab_token_seed.sha256')
        digest = hashlib.sha256(tok.encode()).hexdigest()
        if not os.path.exists(seen) or open(seen).read().strip() != digest:
            _write_private(os.path.join(DATA_DIR, name), tok)
            with open(seen, 'w') as fh:
                fh.write(digest)
            log.info("Schwab token installed from Secrets Manager (new upload).")


def _sigterm(signum, frame):
    raise KeyboardInterrupt


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-7s %(name)s: %(message)s')
    os.makedirs(DATA_DIR, exist_ok=True)
    os.chdir(DATA_DIR)
    script, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ('main.py', [])
    if os.path.basename(script) != script or not script.endswith('.py')             or not os.path.exists(os.path.join(APP_DIR, script)):
        log.error("Unknown script %r (expected a .py file in %s)", script, APP_DIR)
        sys.exit(2)
    if script == 'main.py':
        lock = _lock()                          # noqa: F841  (held until exit)
        _seed()
    _secrets()
    signal.signal(signal.SIGTERM, _sigterm)
    sys.path.insert(0, APP_DIR)
    sys.argv = [os.path.join(APP_DIR, script)] + args
    logging.getLogger().handlers.clear()        # main.py configures logging itself
    runpy.run_path(sys.argv[0], run_name='__main__')


if __name__ == '__main__':
    main()
