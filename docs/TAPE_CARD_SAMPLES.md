# Discord card samples

> **SYNTHETIC EXAMPLES**, rendered from constructed test data by the current code. Not real trades, not verified history. Tickers prefixed XMP are fictitious.

## NEW_OBSERVATION

**🔵 XMPL 2026-10-23 20P**  
color `#3498DB`

Observation — unusual relative activity (research candidate, not a trade).

- **Observed**: 10:00:02 ET · DTE 4 · `weekly`
- **Facts**: Volume **400** = **8.0×** its 20-session median (50, n=20) · vs prior OI **100** (as of 2026-10-16)  
taker side: buy 0% / sell 100% / UNKNOWN 0% over 2 prints  
quote 1.0×1.1 (50ms old)
- **Read**: Neutral observation — who opened or closed is not visible on the public tape.
- **Next check**: whether ordinary electronic volume reaches 500 contracts
- **Catalyst**: Catalyst: no verified calendar loaded.

_footer: signal 1dbeb500728509e9 v1 · For research only. Not investment advice. Verify fills and manage your own risk._

## WORKING_HYPOTHESIS

**🟡 XMPL 2026-10-23 20P**  
color `#F1C40F`

Working hypothesis — a conditional side thesis, not a verified position.

- **Observed**: 10:00:04 ET · DTE 4 · `weekly`
- **Facts**: Volume **600** = **8.0×** its 20-session median (50, n=20) · vs prior OI **100** (as of 2026-10-16)  
taker side: buy 0% / sell 100% / UNKNOWN 0% over 3 prints  
quote 1.0×1.1 (50ms old)
- **Read**: **If** this is a real position: put-writing is a conditional opening thesis. Alternative: long puts sold to close, or a package/hedge leg.
- **Next check**: next session's OI change vs full-session volume (≥50% would support aggregate opening)
- **Catalyst**: Catalyst: no verified calendar loaded.

_footer: signal 1dbeb500728509e9 v2 · For research only. Not investment advice. Verify fills and manage your own risk._

## THESIS_WEAKENED

**🟡 XMPL 2026-10-23 20P**  
color `#F1C40F`

Revision — the working hypothesis no longer meets its gate.

- **Observed**: 10:00:28 ET · DTE 4 · `weekly`
- **Facts**: Volume **2,200** = **8.0×** its 20-session median (50, n=20) · vs prior OI **100** (as of 2026-10-16)  
taker side: buy 46% / sell 55% / UNKNOWN 0% over 11 prints  
quote 1.0×1.1 (50ms old)
- **Read**: Neutral observation — who opened or closed is not visible on the public tape.
- **Next check**: whether one taker side reaches 60% of captured volume
- **Catalyst**: Catalyst: no verified calendar loaded.

_footer: signal 1dbeb500728509e9 v3 · For research only. Not investment advice. Verify fills and manage your own risk._

## INVALIDATED

**🟡 XMPC 2026-10-23 50C**  
color `#F1C40F`

Revision — a correction removed the evidence behind this observation.

- **Observed**: 10:00:00 ET · DTE 4 · `weekly`
- **Facts**: vs prior OI **10** (as of 2026-10-16)  
taker side: buy 0% / sell 0% / UNKNOWN 0% over 0 prints  
quote 1.0×1.1 (10ms old)
- **Read**: Neutral observation — who opened or closed is not visible on the public tape.
- **Next check**: whether new prints re-earn the screens (the corrected data no longer qualifies)
- **Catalyst**: Catalyst: no verified calendar loaded.

_footer: signal 9f3f98251a3e80cf v2 · For research only. Not investment advice. Verify fills and manage your own risk._

## PACKAGE

**🔵 XMPK package candidate 1:2 — DIAGONAL_OR_ROLL_CANDIDATE**  
color `#3498DB`

DIAGONAL_OR_ROLL_CANDIDATE: leg sides UNKNOWN — geometry only; net side, debit/credit and initiator unresolved.

- **Observed**: 10:00:00 ET · DTE 0 · `zero_dte` (all expiries shown)
- **Legs**: `   400` 2026-10-19 80C @ VWAP 2.1 · C · cond f · taker UNKNOWN  
`   800` 2026-11-20 85C @ VWAP 0.8 · C · cond f · taker UNKNOWN
- **Association**: A_COMPLEX_COMMON_VENUE_TIGHT — descriptive grade, not a probability or a proven parent order
- **Next check**: next-session OI on each leg (a far leg is not presumed to survive the front leg without reconciliation)
- **Catalyst**: Catalyst: no verified calendar loaded.

_footer: package f39125ba437de175 v1 · For research only. Not investment advice. Verify fills and manage your own risk._

## CONVEXITY_CONTEXT_CHANGED

**🟡 XMPK 2026-10-19 80C**  
color `#F1C40F`

Revision — a sibling leg suggests this print may belong to a package.

- **Observed**: 10:00:00 ET · DTE 0 · `zero_dte`
- **Facts**: Volume **400** = **40.0×** its 20-session median (10, n=20) · vs prior OI **10** (as of 2026-10-16)  
taker side: buy 0% / sell 0% / UNKNOWN 100% over 1 prints  
quote 2.0×2.1 (52ms old)
- **Read**: Neutral — the print overlaps a package candidate; its outright meaning is unresolved.
- **Next check**: whether the package linkage resolves (sibling-leg OI next session)
- **Catalyst**: Catalyst: no verified calendar loaded.

_footer: signal ee880e97d6944fa5 v2 · For research only. Not investment advice. Verify fills and manage your own risk._

## OI_ANNOTATION

**🟡 XMPK 2026-11-20 85C**  
color `#F1C40F`

Revision — next-session open interest is in (aggregate, never who traded).

- **Observed**: next session · DTE 32 · `swing`
- **Facts**: Volume **800** = **80.0×** its 20-session median (10, n=20) · vs prior OI **10** (as of 2026-10-16)  
taker side: buy 0% / sell 0% / UNKNOWN 100% over 1 prints  
quote 0.8×0.9 (52ms old)
- **OI (aggregate)**: **OPENING_SUPPORTED** — ΔOI 640 vs full-session volume 800; opening contracts between 640 and 720. Never identifies the earlier trader.
- **Read**: Neutral — the print overlaps a package candidate; its outright meaning is unresolved.
- **Next check**: whether the package linkage resolves (sibling-leg OI next session)
- **Catalyst**: Catalyst: no verified calendar loaded.

_footer: signal 1cf0c8a1373c2393 v3 · For research only. Not investment advice. Verify fills and manage your own risk._

## DEGRADATION

**🔵 Feed degraded — tape lane**  
color `#95A5A6`

Options feed disconnected (ConnectionClosedError: 1006). Prints in the gap are backfilled where possible but quotes cannot be, so their side stays UNKNOWN and affected contracts are context only.


_footer: For research only. Not investment advice. Verify fills and manage your own risk._

## WATCHED_ACTIVITY

**🟡 Watched contract activity — XMPC261023C00050000**  
color `#F1C40F`

25 @ 1.05 (C, cond I, taker UNKNOWN). Market activity only — it is NOT assigned to your position.


_footer: watch w-example · For research only. Not investment advice. Verify fills and manage your own risk._

## USER_FILL

**🟢 BUY XMPC261023C00050000 × 2**  
color `#2ECC71`

User-recorded fill @ **1.07** at 2026-10-19T10:01:00-04:00 (expiry 2026-10-23). Recorded by its owner; not generated from market data.


_footer: watch w-example · For research only. Not investment advice. Verify fills and manage your own risk._

## ENGINE_ENTRY (own paper order)

**🟢 ENTER  NVDA CALL 215**  
color `#2ECC71`

**NVDA** carries **41%** of the Mag-7 fresh-premium pool and **CALL-side premium leads** — read as bullish flow *if* it is fresh directional buying. Best alternative: closing a profitable position (p=0.18). Buying the convexity (paper).

- **Attention**: score **71** · rank **#1** · share **41%**
- **Control**: **CALL** · dominance 0.72
- **Pool**: $4,210,000 fresh
- **Contract**: NVDA 215C exp 2026-10-19  
spot $213.80
- **Entry**: $1.42 × 2  =  $284
- **Observed**: 10:05:00 ET · DTE 0 · `zero_dte`
- **Catalyst**: Catalyst: no verified calendar loaded.
- **Exit plan**: Scale ½ at +60% · rest at +150% · trail 35% off peak (arms +40%)  
Rotation / control-flip exit after 3 sustained polls
- **Attention board**: ```  
  #  SYM    SCORE  SHARE  CTRL  
> 1  NVDA    71   41%  CALL  
```

_footer: Jakenew Attention Engine · ROUTE · Alpaca paper_

## ENGINE_NEAR_MISS

**🟡 NEAR-MISS WATCH  AAPL PUT 245**  
color `#F1C40F`

High-quality event **0.520/0.550** — below the entry boundary. **RESEARCH ONLY — no order placed.** Watching whether this converts.

- **Route score**: **0.520** / 0.550  (short 0.03)
- **Archetype**: COMPACT  
`COMPACT_SHOCK`
- **Top drag**: response -0.04
- **Qualified control**: 68%
- **Value**: EARLY
- **Distribution**: 0.21
- **Acceptance**: ABSORPTION
- **Info-mass rank**: #2
- **Observed**: 10:05:00 ET · DTE 0 · `zero_dte`
- **Interpretation**: Working hypothesis: fresh bearish put flow. Best alternative: a hedge / volatility demand (p=0.22).
- **Next check**: whether response improves — the largest drag on the route score
- **Catalyst**: Catalyst: none on file before expiry.

_footer: Jakenew · near-miss research alert (not an entry) · For research only. Not investment advice. Verify fills and manage your own risk._

## ENGINE_FEED_GAP

**🔵 FEED GAP  TSLA  74s**  
color `#5865F2`

No usable option data for **74s**. New entries on TSLA are paused for 180s while flow windows refill — reads across the gap are **context only**.


_footer: Jakenew · coverage notice · For research only. Not investment advice. Verify fills and manage your own risk._
