"""Decision ledger tests (v3-review #17). Run: python test_decision_ledger.py"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import decision_ledger as dl

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

now = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)
metric = {'rank': 2, 'attention_share': 0.18, 'mass_z': 4.1, 'velocity': 500, 'acceleration': 30,
          'call': {'total': 1_000_000}, 'put': {'total': 400_000},
          'qualified_control': {'q_call_mass': 60000, 'q_put_mass': 575000,
                                'dominant_side': 'PUT', 'flipped_from_raw': True}}
cand = {'inventory': {'state': 'LIKELY_FUNDED', 'ambiguity': 'LOW', 'depletion': {'state': 'LIKELY_FUNDED'}},
        'package': {'label': 'OUTRIGHT_LIKELY', 'confidence': 0.0},
        'hypotheses': {'top': 'FRESH_DIRECTIONAL', 'top_p': 0.4, 'directional_p': 0.4},
        'barshock': {'shock': 6.0, 'rel_shock': 3.0, 'cluster': 1, 'event_type': 'CONCENTRATED_SINGLE_STRIKE_EVENT'},
        'acceptance': {'label': 'ABSORPTION'}, 'campaign_score': 72, 'dist_prob': 0.1, 'cont_prob': 0.8}

print("── record captures state + ALL veto reasons ──")
rec = dl.build_record(now=now, ticker='NVDA', side='PUT', metric=metric, cand=cand,
                      decision='REJECT', owner='_open_wave:MISSED_DUE_TO_EV_GATE',
                      veto_reasons=['MISSED_DUE_TO_EV_GATE', 'INVENTORY_AMBIGUITY_PASS'],
                      code_version='abc123', config_hash='def456', candidate_strike=222.5)
ck("qualified control flip captured", rec['qualified_control_side'] == 'PUT' and rec['control_flipped'])
ck("attention rank captured", rec['attention_rank'] == 2)
ck("ALL veto reasons captured (not just first)", len(rec['veto_reasons']) == 2)
ck("provenance stamped", rec['code_version'] == 'abc123' and rec['config_hash'] == 'def456')
ck("candidate strike captured", rec['candidate_strike'] == 222.5)
ck("decision + owner captured", rec['decision'] == 'REJECT' and 'EV_GATE' in rec['owner'])

print("── append writes a valid JSON line ──")
path = os.path.join(tempfile.gettempdir(), 'ledger_test.jsonl')
if os.path.exists(path):
    os.remove(path)
dl.append(path, rec)
dl.append(path, dl.build_record(now=now, ticker='TSLA', side='CALL', metric=metric, cand=cand,
                                decision='ALLOW', owner='_open_wave', veto_reasons=[]))
lines = open(path, encoding='utf-8').read().strip().split('\n')
ck("two records appended", len(lines) == 2)
ck("each line is valid JSON", all(json.loads(l) for l in lines))
ck("allow record has empty veto list", json.loads(lines[1])['veto_reasons'] == [])
os.remove(path)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
