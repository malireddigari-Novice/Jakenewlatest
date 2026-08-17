"""Runtime-authority table tests (v3-audit item 1). Run: python test_runtime_authority.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

rows = config.runtime_authority()
ck("returns a non-empty table", len(rows) >= 15)
required = {'feature', 'code_default', 'env_value', 'effective', 'decision_owner'}
ck("every row has the required columns", all(required <= set(r) for r in rows))
ck("every feature has a decision owner", all(r['decision_owner'] for r in rows))

# the effective value must equal the actually-loaded config attribute (single source of truth)
mism = [r['feature'] for r in rows if hasattr(config, r['feature']) and getattr(config, r['feature']) != r['effective']]
ck("effective column matches the loaded config value", not mism)

# key features present with correct owners
by = {r['feature']: r for r in rows}
ck("REVERSAL owner = opposite-side exits", 'opposite' in by['REVERSAL_ENABLED']['decision_owner'])
ck("DAILY_ENTRY_LOCK noted authoritative over refractory",
   'authoritative over refractory' in by['DAILY_ENTRY_LOCK_ENABLED']['decision_owner'])
ck("VALUE_STATE_AUTHORITATIVE supersedes session-low gate",
   'supersedes' in by['VALUE_STATE_AUTHORITATIVE']['decision_owner'])

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
