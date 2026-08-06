"""Campaign replay / candidate archive tests (Phase 6). Run: python test_replay.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import replay

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1


def metric(sym, side='CALL', rank=1, share=0.5, z=4.0):
    cc = 0.8 if side == 'CALL' else 0.2
    return {'symbol': sym, 'rank': rank, 'attention_score': 90.0, 'attention_share': share,
            'mass_z': z, 'velocity': 1e6, 'acceleration': 1e5,
            'call_control': cc, 'put_control': 1 - cc}


def cand(**kw):
    base = {'best': {'strike': 250.0, 'mark': 2.0}, 'notional': 1.2e5, 'dist_low': 1.1,
            'accumulation': True, 'acc_label': 'COMPACT_ACCUMULATION', 'dist_prob': 0.1,
            'archetype': {'archetype': 'SHOCK_ACCUMULATION'},
            'surface': {'classification': 'SINGLE_STRIKE_DOMINANT'}, 'eas': 72.0}
    base.update(kw)
    return base

print("── candidate record ──")
rec = replay.candidate_record(1000.0, 'NVDA', 'CALL', metric('NVDA'), cand(), 'ACTIVE', 'ENTERED')
ck("record carries the core fields", rec['symbol'] == 'NVDA' and rec['decision'] == 'ENTERED'
   and rec['rank'] == 1 and rec['archetype'] == 'SHOCK_ACCUMULATION'
   and rec['surface_class'] == 'SINGLE_STRIKE_DOMINANT' and rec['control'] == 0.8)
rec2 = replay.candidate_record(1000.0, 'X', 'PUT', None, None, 'DORMANT', 'OBSERVED')
ck("record tolerates missing metric/cand", rec2['symbol'] == 'X' and rec2['rank'] is None)

print("── missed-event diagnostics ──")
# A campaign that ranked #1, showed accumulation, but was rejected repeatedly on one gate.
recs = [replay.candidate_record(1000.0 + 60 * i, 'AMZN', 'CALL', metric('AMZN', rank=2, share=0.3),
        cand(accumulation=True), 'FORMING', 'REJECTED', 'ENTRY_GATE') for i in range(5)]
recs.append(replay.candidate_record(1400.0, 'AMZN', 'CALL', metric('AMZN', rank=1, share=0.45),
            cand(), 'ACTIVE', 'OBSERVED'))
d = replay.diagnose_missed(recs)
ck("diagnosis: observed, best rank tracked, never entered",
   d['observed'] and d['best_rank'] == 1 and d['ranked_top3'] and not d['entered'])
ck("diagnosis: dominant blocking gate identified",
   d['dominant_block'] == 'ENTRY_GATE' and d['rejection_reasons']['ENTRY_GATE'] == 5)
ck("diagnosis: accumulation was present", d['ever_accumulation'] and d['n_polls'] == 6)
ck("empty diagnosis is safe", replay.diagnose_missed([]) == {'observed': False})

print("── archive round-trip ──")
path = os.path.join(tempfile.gettempdir(), 'jakenew_test_archive.jsonl')
if os.path.exists(path):
    os.remove(path)
arch = replay.ResearchArchive(path)
arch.write(rec)
arch.write(rec2)
loaded = arch.load()
ck("archive writes + reloads JSONL", len(loaded) == 2 and loaded[0]['symbol'] == 'NVDA')
os.remove(path)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
