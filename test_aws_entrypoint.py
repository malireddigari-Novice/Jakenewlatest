"""deploy/aws/entrypoint.py on SYNTHETIC data, no AWS: secrets, first-run seed, Schwab token, single-copy lock, and the
hand-off to main.py (cwd on the state volume, DOTENV_PATH honoured by config). Runs on Windows too: fcntl and
boto3 are replaced by stand-ins.

Run: python test_aws_entrypoint.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types

FAILS = []
HERE = os.path.dirname(os.path.abspath(__file__))


def check(cond, msg):
    print(f"  {'ok ' if cond else 'FAIL'} {msg}")
    if not cond:
        FAILS.append(msg)


# fcntl stand-in: a second lock on the same path fails, like lockf on a held EFS/NFS lock.
held = set()
fake_fcntl = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4)


def _lockf(fh, flags):
    if fh.name in held:
        raise OSError('locked')
    held.add(fh.name)


fake_fcntl.lockf = _lockf
sys.modules.setdefault('fcntl', fake_fcntl)
if sys.modules['fcntl'] is not fake_fcntl:          # real Linux fcntl: still use the stand-in for determinism
    sys.modules['fcntl'] = fake_fcntl


SECRETS = tempfile.mkdtemp(prefix='ep_secrets_')


def load(data_dir, app_dir):
    os.environ['DATA_DIR'], os.environ['APP_DIR'], os.environ['SECRETS_DIR'] = data_dir, app_dir, SECRETS
    spec = importlib.util.spec_from_file_location('entrypoint_t', os.path.join(HERE, 'deploy', 'aws', 'entrypoint.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


print('── secrets ──')
d = tempfile.mkdtemp(prefix='ep_data_')
ep = load(d, HERE)
os.environ.update({'JAKENEW_DOTENV': 'FOO_FROM_DOTENV=1\n', 'GOOGLE_SA_JSON': '{"type": "service_account"}',
                   'SCHWAB_TOKEN_JSON': '{"token": 1}'})
os.environ.pop('GOOGLE_SERVICE_ACCOUNT_FILE', None)
ep._secrets()
check(os.environ['DOTENV_PATH'] == os.path.join(SECRETS, 'jakenew.env')
      and open(os.environ['DOTENV_PATH']).read() == 'FOO_FROM_DOTENV=1\n', '.env text written and DOTENV_PATH set')
check(os.environ['GOOGLE_SERVICE_ACCOUNT_FILE'] == os.path.join(SECRETS, 'google_sa.json')
      and json.load(open(os.environ['GOOGLE_SERVICE_ACCOUNT_FILE']))['type'] == 'service_account',
      'Google key written and GOOGLE_SERVICE_ACCOUNT_FILE points at it')
check(not any(k in os.environ for k in ('JAKENEW_DOTENV', 'GOOGLE_SA_JSON', 'SCHWAB_TOKEN_JSON')),
      'raw secret env vars are removed before main.py runs')
tok = os.path.join(d, 'schwab_token.json')
check(json.load(open(tok)) == {'token': 1}, 'first Schwab upload installed on the state volume')
open(tok, 'w').write('{"token": "refreshed-in-place"}')
os.environ['SCHWAB_TOKEN_JSON'] = '{"token": 1}'
ep._secrets()
check(json.load(open(tok)) == {'token': 'refreshed-in-place'}, 'same upload again: the refreshed token is kept')
os.environ['SCHWAB_TOKEN_JSON'] = '{"token": 2}'
ep._secrets()
check(json.load(open(tok)) == {'token': 2}, 'a new upload (after schwab_reauth.py) replaces it')
os.environ['SCHWAB_TOKEN_JSON'] = 'none'
os.environ['GOOGLE_SA_JSON'] = 'none'
os.environ['GOOGLE_SERVICE_ACCOUNT_FILE'] = 'unchanged'
ep._secrets()
check(json.load(open(tok)) == {'token': 2} and os.environ['GOOGLE_SERVICE_ACCOUNT_FILE'] == 'unchanged',
      "'none' placeholders change nothing")

print('── first-run seed ──')
objs = {'seed/jakenew_campaign_flow.db': b'journal', 'seed/jakenew_state.json': b'{"from": "seed"}',
        'seed/cf_obs/2026-11-05.jsonl': b'{}\n', 'seed/': b''}
got = []


class S3:
    def get_paginator(self, name):
        return types.SimpleNamespace(paginate=lambda Bucket, Prefix: [
            {'Contents': [{'Key': k} for k in objs if k.startswith(Prefix)]}])

    def download_file(self, bucket, key, dest):
        got.append(key)
        open(dest, 'wb').write(objs[key])


sys.modules['boto3'] = types.SimpleNamespace(client=lambda name: S3())
d2 = tempfile.mkdtemp(prefix='ep_seed_')
open(os.path.join(d2, 'jakenew_state.json'), 'w').write('{"from": "efs"}')
ep2 = load(d2, HERE)
os.environ['SEED_S3_URI'] = 's3://bucket/seed/'
ep2._seed()
check(open(os.path.join(d2, 'jakenew_campaign_flow.db'), 'rb').read() == b'journal'
      and os.path.exists(os.path.join(d2, 'cf_obs', '2026-11-05.jsonl')), 'seed files copied, sub-folders created')
check(json.load(open(os.path.join(d2, 'jakenew_state.json'))) == {'from': 'efs'}
      and 'seed/jakenew_state.json' not in got, 'a file already on the volume is never overwritten')
check(json.load(open(os.path.join(d2, '.seeded')))['files'] == 2, '.seeded marker records the copy')
got.clear()
ep2._seed()
check(got == [], 'second start: no seed copy (marker present)')

print('── single-copy lock ──')
d3 = tempfile.mkdtemp(prefix='ep_lock_')
ep3 = load(d3, HERE)
fh = ep3._lock()
try:
    ep3._lock()
    check(False, 'a second copy must not start')
except SystemExit as e:
    check(e.code == 75, 'a second copy on the same volume exits with code 75')
fh.close()

print('── hand-off to main.py ──')
app = tempfile.mkdtemp(prefix='ep_app_')
d4 = tempfile.mkdtemp(prefix='ep_run_')
open(os.path.join(app, 'main.py'), 'w').write(
    "import json, os, sys\n"
    "sys.path.insert(0, %r)\n"
    "import config\n"
    "json.dump({'cwd': os.getcwd(), 'dotenv': os.environ.get('DOTENV_PATH'),\n"
    "           'foo': os.environ.get('FOO_FROM_DOTENV'), 'path0': sys.path[0]}, open('ran.json', 'w'))\n"
    "sys.exit(0)\n" % HERE)
runner = (
    "import sys, types; f = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, lockf=lambda *a: None); "
    "sys.modules['fcntl'] = f; import runpy; runpy.run_path(%r, run_name='__main__')"
    % os.path.join(HERE, 'deploy', 'aws', 'entrypoint.py'))
envp = {**os.environ, 'DATA_DIR': d4, 'APP_DIR': app, 'SECRETS_DIR': tempfile.mkdtemp(prefix='ep_sec2_'), 'JAKENEW_DOTENV': 'FOO_FROM_DOTENV=42\n',
        'GOOGLE_SA_JSON': 'none', 'SCHWAB_TOKEN_JSON': 'none', 'SEED_S3_URI': ''}
envp.pop('DOTENV_PATH', None)
envp.pop('FOO_FROM_DOTENV', None)
r = subprocess.run([sys.executable, '-c', runner], env=envp, capture_output=True, text=True, timeout=120)
ran = json.load(open(os.path.join(d4, 'ran.json'))) if os.path.exists(os.path.join(d4, 'ran.json')) else {}
check(r.returncode == 0 and os.path.samefile(ran.get('cwd', '.'), d4),
      f"main.py runs with the state volume as working dir (rc {r.returncode}) {r.stderr[-300:] if r.returncode else ''}")
check(ran.get('foo') == '42', 'config.py loads the .env from DOTENV_PATH')

open(os.path.join(app, 'report.py'), 'w').write(
    "import json, sys\njson.dump(sys.argv[1:], open('report.json', 'w'))\n")
open(os.path.join(d4, '.jakenew.lock'), 'w').close()
r = subprocess.run([sys.executable, '-c', runner.replace("run_name='__main__')",
                    "run_name='__main__')").replace("import runpy;", "import runpy; sys.argv += ['report.py', '2026-11-06'];")],
                   env=envp, capture_output=True, text=True, timeout=120)
check(r.returncode == 0 and json.load(open(os.path.join(d4, 'report.json'))) == ['2026-11-06'],
      'one-off script mode: runs report.py with its arguments on the state volume')
r = subprocess.run([sys.executable, '-c', runner.replace("import runpy;", "import runpy; sys.argv += ['../x.py'];")],
                   env=envp, capture_output=True, text=True, timeout=120)
check(r.returncode == 2, 'a script outside the app folder is refused (exit 2)')

print()
if FAILS:
    print(f"{len(FAILS)} ENTRYPOINT CHECK(S) FAILED")
    raise SystemExit(1)
print('ALL ENTRYPOINT CHECKS PASSED (synthetic, no AWS)')
