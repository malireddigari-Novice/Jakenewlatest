"""Intraday-vs-overnight session-thesis tests (handoff P6). Run: python test_session_thesis.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import session_thesis as st
from analysis import campaign_store

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

config.SESSION_THESIS_ENABLED = True
config.SESSION_THESIS_LATEDAY_MIN = 60
config.OVERNIGHT_MIN_CONTROL = 0.60
config.OVERNIGHT_MAX_DIST_PROB = 0.35

overnight = {'minutes_to_close': 0, 'dte': 1, 'control': 0.72, 'dist_prob': 0.10,
             'value_state': 'FAIR', 'spot_confirms': True}

print("── classification ──")
r = st.classify(overnight)
ck("late-day durable read → OVERNIGHT (carry)", r['thesis'] == 'OVERNIGHT' and r['carry'])

ck("mid-session read → INTRADAY (no carry)",
   st.classify({**overnight, 'minutes_to_close': 180})['thesis'] == 'INTRADAY')

ck("control not held into close → INTRADAY",
   st.classify({**overnight, 'control': 0.5})['thesis'] == 'INTRADAY')
ck("distribution in progress → INTRADAY",
   st.classify({**overnight, 'dist_prob': 0.5})['thesis'] == 'INTRADAY')
ck("value extended → INTRADAY",
   st.classify({**overnight, 'value_state': 'EXTENDED'})['thesis'] == 'INTRADAY')
ck("spot not confirming → INTRADAY",
   st.classify({**overnight, 'spot_confirms': False})['thesis'] == 'INTRADAY')

config.SESSION_THESIS_ENABLED = False
ck("disabled → UNKNOWN, no carry", st.classify(overnight)['thesis'] == 'UNKNOWN')
config.SESSION_THESIS_ENABLED = True

print("── carry_forward honours the INTRADAY verdict ──")
today = '2026-08-31'
camps = {
    'a': {'state': 'ACTIVE', 'expiry': '2026-09-05', 'session_carry': True},    # overnight → carries
    'b': {'state': 'ACTIVE', 'expiry': '2026-09-05', 'session_carry': False},   # intraday → dropped
    'c': {'state': 'ACTIVE', 'expiry': '2026-09-05'},                           # unclassified → carries
}
out = campaign_store.carry_forward(camps, today)
ck("overnight campaign carries", 'a' in out)
ck("intraday campaign is dropped", 'b' not in out)
ck("unclassified campaign carries (unchanged behaviour)", 'c' in out)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
