"""MAG7 Attention Engine test. Run: python test_attention.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis import attention as at

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

def by(board):
    return {r['symbol']: r for r in board['ranked']}

# ── 1. Morning: AAPL owns the pool (spec example) ──
morning = {
    'AAPL':  {'premium': 5_200_000, 'control_share': 0.81, 'control_side': 'CALL'},
    'NVDA':  {'premium': 1_100_000, 'control_share': 0.60, 'control_side': 'PUT'},
    'META':  {'premium':   400_000, 'control_share': 0.55, 'control_side': 'CALL'},
    'TSLA':  {'premium':   600_000, 'control_share': 0.58, 'control_side': 'CALL'},
    'MSFT':  {'premium':   200_000, 'control_share': 0.52, 'control_side': 'CALL'},
    'AMZN':  {'premium':   300_000, 'control_share': 0.53, 'control_side': 'CALL'},
    'GOOGL': {'premium':   200_000, 'control_share': 0.51, 'control_side': 'PUT'},
}
b = at.attention_board(morning, min_total=250_000, score_min=70)
r = by(b)
ck("AAPL is the attention leader", b['leader'] == 'AAPL' and r['AAPL']['rank'] == 1)
ck("AAPL owns >50% of the pool", r['AAPL']['share'] > 0.50)
ck("AAPL score is highest and >=70", r['AAPL']['attention_score'] >= 70
   and r['AAPL']['attention_score'] == max(x['attention_score'] for x in b['ranked']))
ck("AAPL control side surfaced = CALL", r['AAPL']['control_side'] == 'CALL')
ck("MSFT (2% share) scores far below threshold", not r['MSFT']['above_threshold'])
print(f"     -> leader={b['leader']}  AAPL={r['AAPL']['attention_score']} share={r['AAPL']['share']}")

# ── 2. Afternoon rotation: NVDA now owns attention, on PUTS ──
after = {
    'AAPL':  {'premium':   600_000, 'control_share': 0.55, 'control_side': 'CALL'},
    'NVDA':  {'premium': 4_800_000, 'control_share': 0.82, 'control_side': 'PUT'},
    'META':  {'premium':   200_000, 'control_share': 0.50, 'control_side': 'CALL'},
    'TSLA':  {'premium':   300_000, 'control_share': 0.54, 'control_side': 'PUT'},
    'MSFT':  {'premium':   100_000, 'control_share': 0.51, 'control_side': 'CALL'},
    'GOOGL': {'premium':   100_000, 'control_share': 0.50, 'control_side': 'PUT'},
    'AMZN':  {'premium':   200_000, 'control_share': 0.52, 'control_side': 'CALL'},
}
prevmap = {s: morning[s]['premium'] for s in morning}
b2 = at.attention_board(after, prev=prevmap, min_total=250_000, score_min=70)
r2 = by(b2)
ck("attention rotated to NVDA", b2['leader'] == 'NVDA' and r2['NVDA']['rank'] == 1)
ck("NVDA control side = PUT", r2['NVDA']['control_side'] == 'PUT')
ck("NVDA positive velocity (premium surged)", r2['NVDA']['velocity'] > 0)
ck("AAPL demoted below NVDA", r2['AAPL']['rank'] > r2['NVDA']['rank'])
print(f"     -> leader={b2['leader']}  NVDA score={r2['NVDA']['attention_score']} vel={r2['NVDA']['velocity']}")

# ── 3. Quiet pool: total below min_total -> no leader declared ──
quiet = {'AAPL': {'premium': 40_000, 'control_share': 0.9, 'control_side': 'CALL'},
         'NVDA': {'premium': 30_000, 'control_share': 0.6, 'control_side': 'PUT'}}
b3 = at.attention_board(quiet, min_total=250_000, score_min=70)
ck("quiet pool -> no attention leader", b3['leader'] is None)
ck("but board still ranks + scores", b3['ranked'][0]['rank'] == 1)

# ── 4. control_dominance mapping ──
ck("50/50 control -> 0 dominance", at.control_dominance(0.5) == 0.0)
ck("100/0 control -> 1 dominance", at.control_dominance(1.0) == 1.0)
ck("None control -> 0", at.control_dominance(None) == 0.0)

# ── 5. Missing low_score renormalises weights; score stays within 0-100 ──
one = {'AAPL': {'premium': 1_000_000, 'control_share': 1.0, 'control_side': 'CALL', 'low_score': None},
       'NVDA': {'premium': 10_000, 'control_share': 0.5, 'control_side': 'PUT', 'low_score': None}}
b5 = at.attention_board(one, min_total=0, score_min=70)
r5 = by(b5)
ck("sole dominant name scores <=100", r5['AAPL']['attention_score'] <= 100.0)
ck("low_score present raises score vs absent",
   at.attention_board({'AAPL': {**one['AAPL'], 'low_score': 1.0}}, min_total=0)['ranked'][0]['attention_score']
   >= at.attention_board({'AAPL': {**one['AAPL'], 'low_score': 0.0}}, min_total=0)['ranked'][0]['attention_score'])

# ── 6. Entry gate: leader + control agreement -> KEEP ──
gate_board = at.attention_board({
    'AAPL': {'premium': 5_000_000, 'control_share': 0.81, 'control_side': 'CALL'},
    'META': {'premium':   300_000, 'control_share': 0.55, 'control_side': 'PUT'},
    'MSFT': {'premium':   200_000, 'control_share': 0.52, 'control_side': 'CALL'},
}, min_total=250_000, score_min=70)
gk = at.gate_signal(gate_board, 'AAPL', 'BULLISH', score_min=70, max_rank=2)
ck("leader + call-control + BULLISH -> KEEP", gk['decision'] == 'KEEP')
gd = at.gate_signal(gate_board, 'AAPL', 'BEARISH', score_min=70, max_rank=2)
ck("control disagrees (BEARISH vs CALL control) -> DROP", gd['decision'] == 'DROP'
   and gd['reason'] == 'CONTROL_SIDE_DISAGREES')
gr = at.gate_signal(gate_board, 'MSFT', 'BULLISH', score_min=70, max_rank=2)
ck("low-attention name -> DROP (below threshold)", gr['decision'] == 'DROP'
   and gr['reason'] in ('ATTENTION_BELOW_THRESHOLD', 'ATTENTION_RANK_TOO_LOW'))
gm = at.gate_signal(gate_board, 'AAPL', 'BULLISH', score_min=70, max_rank=1)
ck("single-trade rank-1 gate keeps the leader", gm['decision'] == 'KEEP')
gn = at.gate_signal(gate_board, 'XYZ', 'BULLISH')
ck("unknown symbol -> DROP NO_ATTENTION_DATA", gn['reason'] == 'NO_ATTENTION_DATA')

# ── 7. Single-trade selection picks the highest-attention approved signal ──
approved = [{'symbol': 'META', 'x': 1}, {'symbol': 'AAPL', 'x': 2}]
pick = at.select_single_trade(approved, gate_board)
ck("select_single_trade picks AAPL (highest attention)", pick['symbol'] == 'AAPL')
ck("empty candidates -> None", at.select_single_trade([], gate_board) is None)

# ── 8. Rotation exit: sustained deterioration required (anti-churn) ──
mon = at.AttentionExitMonitor()
gone = at.attention_board({
    'NVDA': {'premium': 5_000_000, 'control_share': 0.85, 'control_side': 'PUT'},
    'AAPL': {'premium':   150_000, 'control_share': 0.55, 'control_side': 'CALL'},
}, min_total=250_000, score_min=70)
e1 = mon.evaluate(gone, 'AAPL', 'CALL', score_min=70, rotate_rank=2, sustain_polls=3)
e2 = mon.evaluate(gone, 'AAPL', 'CALL', score_min=70, rotate_rank=2, sustain_polls=3)
ck("no exit before sustain threshold", not e1['exit'] and not e2['exit'])
e3 = mon.evaluate(gone, 'AAPL', 'CALL', score_min=70, rotate_rank=2, sustain_polls=3)
ck("exit after 3 sustained polls of rotation", e3['exit'] and e3['reason'] == 'ATTENTION_ROTATED_AWAY')

mon2 = at.AttentionExitMonitor()
mon2.evaluate(gone, 'AAPL', 'CALL', sustain_polls=3)
back = at.attention_board({'AAPL': {'premium': 5_000_000, 'control_share': 0.8, 'control_side': 'CALL'},
                           'NVDA': {'premium': 200_000, 'control_share': 0.6, 'control_side': 'PUT'}},
                          min_total=250_000, score_min=70)
rr = mon2.evaluate(back, 'AAPL', 'CALL', sustain_polls=3)
ck("streak resets when attention recovers", rr['streak'] == 0 and not rr['exit'])

mon3 = at.AttentionExitMonitor()
flip = at.attention_board({'AAPL': {'premium': 5_000_000, 'control_share': 0.85, 'control_side': 'PUT'},
                           'NVDA': {'premium': 200_000, 'control_share': 0.6, 'control_side': 'CALL'}},
                          min_total=250_000, score_min=70)
for _ in range(2):
    mon3.evaluate(flip, 'AAPL', 'CALL', sustain_polls=3)
ef = mon3.evaluate(flip, 'AAPL', 'CALL', sustain_polls=3)
ck("control-flip exit reason after sustain", ef['exit'] and ef['reason'] == 'CONTROL_FLIPPED')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
