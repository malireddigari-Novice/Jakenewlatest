"""Multi-expiration structure tests (Phase 3). Run: python test_expiry.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import expiry

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1


def masses(call, put):
    return {'call_mass': call, 'put_mass': put}

print("── control side ──")
ck("call-heavy expiry → CALL control", expiry.control_side(masses(9e5, 1e5))[0] == 'CALL')
ck("put-heavy expiry → PUT control", expiry.control_side(masses(1e5, 9e5))[0] == 'PUT')
ck("empty expiry → no side", expiry.control_side(masses(0, 0))[0] is None)

print("── rows / shares ──")
by = {'2026-07-31': masses(8e5, 2e5), '2026-08-07': masses(1e5, 1e5)}
dte = {'2026-07-31': 0, '2026-08-07': 7}
rows, total = expiry.expiry_rows(by, dte)
ck("rows sorted near→forward", rows[0]['dte'] == 0 and rows[-1]['dte'] == 7)
ck("shares sum to ~1", abs(sum(r['share'] for r in rows) - 1.0) < 1e-3)
ck("near expiry dominates the pool", rows[0]['share'] > rows[-1]['share'])

print("── classification ──")
# NVDA-style: 0DTE puts, Friday calls → opposite sides near vs forward.
conf = {'2026-07-31': masses(1e5, 6e5), '2026-08-01': masses(6e5, 1e5)}
cdte = {'2026-07-31': 0, '2026-08-01': 1}
ck("near-put / forward-call → NEAR_TERM_PUT_FORWARD_CALL",
   expiry.classify(expiry.expiry_rows(conf, cdte)[0]) == 'NEAR_TERM_PUT_FORWARD_CALL')
# Same side across expiries → coherent multi-expiry campaign.
same = {'2026-07-31': masses(6e5, 1e5), '2026-08-01': masses(5e5, 1e5)}
ck("same side near+forward → SAME_SIDE_MULTI_EXPIRY_CONTROL",
   expiry.classify(expiry.expiry_rows(same, cdte)[0]) == 'SAME_SIDE_MULTI_EXPIRY_CONTROL')
# Only a forward expiry meaningful → forward positioning.
fwd = {'2026-07-31': masses(2e4, 1e4), '2026-08-01': masses(8e5, 1e5)}
ck("forward-only meaningful → FORWARD_POSITIONING",
   expiry.classify(expiry.expiry_rows(fwd, cdte)[0]) == 'FORWARD_POSITIONING')

print("── migration ──")
ck("rising forward share → FORWARD_MIGRATION",
   expiry.migration_label(config.EXPIRY_MIGRATION_SLOPE + 0.01) == 'FORWARD_MIGRATION')
ck("falling forward share → NEAR_MIGRATION",
   expiry.migration_label(-(config.EXPIRY_MIGRATION_SLOPE + 0.01)) == 'NEAR_MIGRATION')
ck("flat → STABLE", expiry.migration_label(0.0) == 'STABLE')
ck("no prior → None", expiry.migration_label(None) is None)

# summarize() computes the migration slope from a prior forward-share.
s0 = expiry.summarize(by, dte, prev_forward_share=None)
s1 = expiry.summarize({'2026-07-31': masses(3e5, 1e5), '2026-08-07': masses(5e5, 1e5)}, dte,
                      prev_forward_share=s0['forward_share'])
ck("summarize detects capital migrating forward over time",
   s1['forward_share'] > s0['forward_share'] and s1['migration'] == 'FORWARD_MIGRATION')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
