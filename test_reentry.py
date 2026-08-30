"""Re-entry-after-cooling tests (handoff P4). Run: python test_reentry.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import reentry

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

config.REENTRY_ENABLED = True
config.REENTRY_MAX_PER_SLOT = 1
config.REENTRY_ELIGIBLE_CATEGORIES = {'OBJECTIVE'}
config.REENTRY_MIN_CONTROL = 0.60
config.REENTRY_MIN_ACCEL = 0.0

print("── cooling vs terminal exit categories ──")
ck("OBJECTIVE (took profit) is a cooling exit", reentry.is_cooling_exit('OBJECTIVE'))
ck("REVERSAL is NOT cooling", not reentry.is_cooling_exit('REVERSAL'))
ck("RISK_STOP is NOT cooling", not reentry.is_cooling_exit('RISK_STOP'))
ck("DISTRIBUTION is NOT cooling", not reentry.is_cooling_exit('DISTRIBUTION'))
ck("THESIS_DEATH is NOT cooling", not reentry.is_cooling_exit('THESIS_DEATH'))

print("── reacceleration confirmation ──")
strong = {'authorized': True, 'abnormal': True, 'control': 0.72, 'accel': 0.4,
          'value_state': 'CHEAP', 'spot_confirms': True}
ck("full reaccel confirms", reentry.reaccel_confirmed(strong)['confirmed'])
ck("weak absolute signal blocks", not reentry.reaccel_confirmed({**strong, 'authorized': False})['confirmed'])
ck("no fresh abnormality blocks", not reentry.reaccel_confirmed({**strong, 'abnormal': False})['confirmed'])
ck("control not re-seized blocks", not reentry.reaccel_confirmed({**strong, 'control': 0.5})['confirmed'])
ck("not accelerating blocks", not reentry.reaccel_confirmed({**strong, 'accel': 0.0})['confirmed'])
ck("extended value blocks", not reentry.reaccel_confirmed({**strong, 'value_state': 'EXTENDED'})['confirmed'])
ck("spot not confirming blocks", not reentry.reaccel_confirmed({**strong, 'spot_confirms': False})['confirmed'])

print("── can_reenter end-to-end ──")
cooled = {'category': 'OBJECTIVE', 'count': 0}
r = reentry.can_reenter(cooled, 'OBJECTIVE', strong)
ck("cooled + reaccel → ALLOW", r['allow'] and r['reason'] == 'reaccel_confirmed_after_cooling')

r2 = reentry.can_reenter(cooled, 'OBJECTIVE', {**strong, 'control': 0.4})
ck("cooled but no reaccel → WATCH (not allow)", (not r2['allow']) and r2['watch'])

r3 = reentry.can_reenter(None, None, strong)
ck("never cooled → no re-entry, no watch", (not r3['allow']) and not r3['watch'])

r4 = reentry.can_reenter({'category': 'REVERSAL', 'count': 0}, 'REVERSAL', strong)
ck("terminal exit → never re-eligible", (not r4['allow']) and r4['reason'] == 'terminal_exit_not_re_eligible')

r5 = reentry.can_reenter({'category': 'OBJECTIVE', 'count': 1}, 'OBJECTIVE', strong)
ck("cap reached (1/1) → blocked", (not r5['allow']) and r5['reason'] == 'reentry_cap_reached')

config.REENTRY_ENABLED = False
ck("disabled → no re-entry", not reentry.can_reenter(cooled, 'OBJECTIVE', strong)['allow'])
config.REENTRY_ENABLED = True

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
