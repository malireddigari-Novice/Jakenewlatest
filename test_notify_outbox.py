"""Discord outbox tests: timeout / 429 / 5xx / 4xx without a lost or duplicated card.
Run: python test_notify_outbox.py  (no network — requests.post is stubbed)."""
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import notify

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1


class Resp:
    def __init__(self, code, body=None, headers=None):
        self.status_code, self._body, self.headers = code, body, headers or {}
        self.text = str(body)
    def json(self):
        return self._body


class FakeDiscord:
    """Scripted responses; an Exception instance in the script is raised (timeout)."""
    def __init__(self, script):
        self.script, self.calls = list(script), []
    def __call__(self, url, params=None, json=None, timeout=None):
        self.calls.append(json)
        r = self.script.pop(0) if self.script else Resp(200, {'id': f"m{len(self.calls)}"})
        if isinstance(r, Exception):
            raise r
        return r


tmp = tempfile.mkdtemp()
def fresh(script):
    config.NOTIFY_OUTBOX_DB = os.path.join(tmp, f"ob{time.time_ns()}.db")
    config.DISCORD_WEBHOOK_URL = 'https://discord.invalid/api/webhooks/1/secret'
    fake = FakeDiscord(script)
    notify.requests.post = fake
    return fake

def rows():
    con = sqlite3.connect(config.NOTIFY_OUTBOX_DB)
    out = con.execute("SELECT status, attempts, message_id, next_attempt_at, payload FROM outbox").fetchall()
    con.close()
    return out

def make_due():
    con = sqlite3.connect(config.NOTIFY_OUTBOX_DB)
    con.execute("UPDATE outbox SET next_attempt_at=0"); con.commit(); con.close()

config.NOTIFY_BACKOFF_BASE_S = 5

print("── happy path ──")
fake = fresh([])
notify.send("hello", signal_id="s1")
r = rows()
ck("2xx → SENT with Discord message id", r[0][0] == 'SENT' and r[0][2] == 'm1')
ck("payload suppresses all mentions", '"allowed_mentions": {"parse": []}' in r[0][4])
notify.send("hello", signal_id="s1")
ck("same key re-sent → no second post, no second row", len(fake.calls) == 1 and len(rows()) == 1)

print("── timeout then recovery ──")
fake = fresh([TimeoutError("read timed out")])
notify.send("card", signal_id="s2")
r = rows()
ck("timeout → stays PENDING (not marked sent)", r[0][0] == 'PENDING' and r[0][1] == 1)
ck("timeout → backoff scheduled in the future", r[0][3] > time.time())
notify.flush()
ck("flush before backoff elapses → no retry yet", len(fake.calls) == 1)
make_due(); notify.flush()
ck("flush after backoff → SENT exactly once", rows()[0][0] == 'SENT' and len(fake.calls) == 2)
notify.flush()
ck("further flushes never re-post a SENT card", len(fake.calls) == 2)

print("── 429 rate limit ──")
fake = fresh([Resp(429, {'retry_after': 2.5})])
notify.send("a", signal_id="r1")
notify.send("b", signal_id="r2")
r = rows()
ck("429 → PENDING, attempt not consumed", r[0][0] == 'PENDING' and r[0][1] == 0)
ck("429 → next attempt honours retry_after", 1.5 < r[0][3] - time.time() <= 2.6)
make_due(); notify.flush()
r = rows()
ck("after retry_after both cards SENT, in order, no duplicates",
   all(x[0] == 'SENT' for x in r) and len(r) == 2
   and [c['content'] for c in fake.calls] == ['a', 'a', 'b'])

print("── 5xx and dead-letter ──")
config.NOTIFY_MAX_ATTEMPTS = 3
fake = fresh([Resp(502), Resp(503), Resp(500)])
notify.send("x", signal_id="d1")
make_due(); notify.flush()
make_due(); notify.flush()
r = rows()
ck("transient failures → DEAD after NOTIFY_MAX_ATTEMPTS", r[0][0] == 'DEAD' and r[0][1] == 3)
make_due(); notify.flush()
ck("DEAD cards are not retried", len(fake.calls) == 3)
config.NOTIFY_MAX_ATTEMPTS = 8

fake = fresh([Resp(404, {'message': 'Unknown Webhook'})])
notify.send("y", signal_id="d2")
notify.send("z", signal_id="d3")
r = rows()
ck("permanent 4xx → DEAD immediately, next card still delivered",
   sorted(x[0] for x in r) == ['DEAD', 'SENT'])

print("── embeds / evidence hash ──")
fake = fresh([])
e = {'title': 't', 'fields': [{'name': 'a', 'value': '1'}], 'timestamp': '2026-10-16T10:00:00'}
notify._post(dict(e), signal_id='near|X')
notify._post({**e, 'timestamp': '2026-10-16T10:00:05'}, signal_id='near|X')
ck("same evidence re-rendered later → one card", len(rows()) == 1 and len(fake.calls) == 1)
notify._post({**e, 'fields': [{'name': 'a', 'value': '2'}]}, signal_id='near|X')
ck("changed evidence → a new card", len(rows()) == 2)
ck("webhook token never stored", 'secret' not in ''.join(str(x) for x in rows()))

print("── disabled ──")
config.DISCORD_WEBHOOK_URL = ''
config.NOTIFY_OUTBOX_DB = os.path.join(tmp, 'never.db')
notify.send("nothing")
ck("no webhook → no outbox file, no post", not os.path.exists(config.NOTIFY_OUTBOX_DB))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
