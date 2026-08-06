# Jakenew — the MAG-7 Attention Engine

Jakenew is a rebuild of the JakeVolume idea around **one** question instead of several
competing signal engines:

> **Where is institutional attention flowing right now — and which side of that name controls it?**

The old system asked, per contract, *"did this strike qualify?"* — running three parallel
engines (Primary Level, Chain Leader, Gamma Ramp) that competed to fire alerts. Jakenew treats
Wall Street's attention as a **finite pool** that rotates between the Mag-7 and allocates it:
a name is traded because it *owns the day's attention*, not because it printed volume in
isolation. Primary levels, chains, and gamma ramps aren't separate signals here — they're
*reasons* attention concentrates, and they collapse into a single **Attention Score**.

The observed behaviour it's built to reproduce: AAPL owns the tape in the morning → buy calls;
NVDA takes it over in the afternoon → buy puts. Two trades, not eight.

> **New here? Read [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md)** — a plain-English walkthrough of the
> trading day (what happens at launch / open / close), the entry logic, and the exit logic.

---

## The hierarchy

```
        MAG-7 fresh option premium  ──►  ATTENTION BOARD      Layer 1: where is the money?
                                                │
                                                ▼
                    within the leader…    CALL vs PUT control  Layer 2: what is the money doing?
                                                │
                                                ▼
              gate: owns attention (score ≥ 70, rank 1-2) AND control agrees  Layer 3: ONE trade
                                                │
                                                ▼
                 hold until the objective is met  OR                          Layer 4: exit
                 attention rotates away / control flips (sustained)
```

### Attention Score (0–100)

| Weight | Component | Meaning |
|--:|---|---|
| 40% | Fresh-premium **share** | this name's slice of the day's fresh $-premium pool |
| 25% | Premium **velocity** | Δ premium vs the prior poll (is attention *arriving*?) |
| 15% | Premium **acceleration** | Δ velocity (is the inflow speeding up?) |
| 10% | Control **dominance** | how one-sided the name is (2·control_share − 1) |
| 10% | Distance-**from-low** | room left on the controlling contract (optional) |

A component with no input (no history yet, or unknown range) drops its weight and the rest
renormalise — the score never silently penalises a missing input. Weights are configurable in
`.env`.

### The two exits (and only two)

1. **Structural objective met** — the trade did what it was entered to do (`STRUCTURAL_TP1`
   scales half at +60%, `STRUCTURAL_TP2` banks the rest at +150%, `TRAIL_GIVEBACK` protects a
   run). This stands in for JakeVolume's OI-target ladder; wire real OI targets via the Schwab
   OI map when you want them.
2. **Thesis invalidated** — attention **rotated away** (`ATTENTION_ROTATED_AWAY`) or within-name
   **control flipped** (`CONTROL_FLIPPED`). Requires `ATTENTION_EXIT_SUSTAIN` consecutive polls
   of deterioration so ordinary intraday noise doesn't churn the position.

---

## Data sources (ported from JakeVolume)

| Source | Role |
|---|---|
| **Alpaca** | Intraday spot (SIP) + OPRA option snapshots (the fresh-premium feed) **and execution**. The engine runs on Alpaca alone. |
| **Schwab** | *Optional.* The only source of live **open interest**, used to enrich the structural (OI-target) exit. Degrades gracefully if its ~weekly token has expired. |
| **Discord** | *Optional.* Entry/exit notifications via webhook. |

**Fresh premium** is measured by diffing each near-ATM contract's cumulative day volume between
polls, dollar-weighting the delta (`Δvol × mark × 100 × relevance_to_spot`), and summing across
the name. First sighting of a contract records a baseline (delta 0) so the opening-print flush
never reads as one giant burst of "fresh" attention.

---

## Layout

**The current architecture is v2 — four layers.** See [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md) for
the full plain-English design and [`config.py`](config.py) (`v2 RESEARCH PARAMETERS`) for every
tunable. Runs on a ~5s fast loop with rolling 30/60/180s windows; captures the opening auction;
dynamic expiry (not 0DTE-only).

```
config.py                 all tunables (env-backed) incl. the WAVE / RESPONSE research params
main.py                   entry point — fast loop (FAST_POLL_SECONDS) + pre-open seeding
engine.py                 orchestrator: ingest → mass → waves → accumulation → orders
execution.py              execution controls (limit pricing, spread/liquidity/staleness, dedup)
state.py                  JSON store (positions list) surviving restarts
notify.py                 Discord embed cards (entry/scale/exit)
check_connections.py      one-shot connectivity + live pipeline check
gather.py                 one-shot snapshot of the live attention pipeline
schwab_reauth.py          refresh the (optional) Schwab token
analysis/
  flow.py                 rolling windows, fresh vol/premium, velocity/accel, per-contract series
  mass.py                 Layer 1 — weighted mass, EWMA fast/slow, Z-abnormality, ranking
  control.py              Layer 2 — five-state control machine (+ quote-location bias)
  waves.py                Layer 3 — attention-wave state machine (one wave = one entry)
  response.py             accumulation-vs-distribution (price response + volume-pattern shapes)
  events.py               contract selection, entry-freshness, strike helpers
  attention.py, premium.py   earlier v2 board / helper (kept for reference + tests)
data/
  alpaca_data_client.py   spot + option snapshots (marks, cum volume, sizes, quote ts)
  alpaca_client.py        execution (buy-to-open, scale, close)
  schwab_client.py        optional OI / structural context
  market_utils.py         CST market-hours + pre-open/opening-window helpers
backtest.py               replay real Alpaca 1-min option bars through the engine
tests: test_attention.py  test_premium.py  test_v2.py  test_waves.py  test_response.py  (all green)
```

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in Alpaca (required) + Schwab (optional)
python check_connections.py   # verify feeds + see a live AAPL attention row
python test_attention.py && python test_premium.py
python main.py                # run the loop
```

**Execution is OFF by default** (`ALPACA_ENABLED=false`). Until you flip it on, the engine runs
the full decision logic and logs a **SHADOW** narrative — position P&L tracked off live option
marks — so you can watch the entries and rotations before committing capital. Keep
`ALPACA_PAPER=true` for paper trading even after enabling execution.

For the optional Schwab OI enrichment, run `python schwab_reauth.py` once (opens a browser); the
refresh token lasts ~a week.

### Key knobs (`.env`)

| Var | Default | Effect |
|---|--:|---|
| `ATTENTION_SCORE_MIN` | 70 | a name must score ≥ this to own attention |
| `ATTENTION_MIN_TOTAL` | 250000 | pool must carry this much fresh $ before we allocate at all |
| `ATTENTION_SINGLE_TRADE` | true | hold at most one position — the day's leader |
| `ATTENTION_EXIT_SUSTAIN` | 3 | polls of deterioration before a rotation/flip exit |
| `TRADE_PCT` | 0.01 | fraction of portfolio value per trade |
| `ALPACA_ENABLED` | false | flip to true to place real (paper/live) orders |

> ⚠️ `.env` in this repo carries the real Alpaca/Schwab/Discord credentials copied from
> JakeVolume. It is git-ignored — never commit it, and rotate the keys if it's ever exposed.
