# How Jakenew works — in plain words (v3: attention waves)

Jakenew watches the Mag-7 (AAPL, MSFT, AMZN, GOOGL, META, NVDA, TSLA) and tries to catch the
**small number of institutional accumulation events** that actually shape a session — the moment
dormant option volume becomes a **statistically abnormal, high-information institutional event/
campaign** (v3-review item 20 — compact clustering is one exceptional archetype, not the definition) **while the
option is still cheap**. It is not a scanner for "big volume." One real campaign = **one wave =
one trade**, held until its objective is met or the thesis genuinely dies.

**Mode: ACTIVE on the Alpaca PAPER account** (`ALPACA_ENABLED=true`, `ALPACA_PAPER=true`) — it
places **real orders with simulated money** (no real capital), a forward-test with real fills and
spreads. Set `ALPACA_ENABLED=false` to return to SHADOW (log only). Risk controls in force: 1%
sizing, **up to `MAX_PRIMARY_POSITIONS` (default 4) concurrent campaigns** — multiple independent
Mag-7 campaigns may coexist, governed by the portfolio-correlation gate, NOT a one-position tournament
(v3-review items 1-2) — −40% hard stop, EOD flatten.

> **Authoritative runtime status — `.env` wins, not this doc.** The knob tables below show code
> DEFAULTS (many read **false** there); the *actual* loaded values come from `.env`, which overrides
> them, and are printed at every launch as a `RUNTIME CONFIG` log line (and `EXIT DECISION OWNER = …`).
> As of **2026-08-16** the live paper `.env` has ALL behavior flags **ON** — including the 8/16
> v3-review integration corrections (multi-campaign / MAX_PRIMARY_POSITIONS=4, reversal-owns-exits,
> FORMING spot-exemption, inventory micro-distribution, ContractValueMemory, probabilistic packages,
> InformationMass, continuous attention-transfer, shadow ExpirySelector, Decision Ledger) and the 8/15
> additions: the inventory / package-roll / portfolio-risk layers *and* the rotation resolver,
> expiry-value (late-0DTE + overnight carry), cross-expiry direction, multi-hypothesis (H1–H8),
> data-quality/quote-sync, hedge-flow, premium-decomposition, regime, and campaign-end taxonomy
> (see the two "Addendum subsystems" / "Final gap-closure" sections below). So wherever a per-feature
> note or knob table says "default OFF / shadow / pending backtest", read that as the *code default and
> original rollout intent* — the live paper run has it ON. Four distinct statuses per feature:
>
> | Feature | Implemented | Enabled (live .env) | Authoritative (owns a decision) | Validated (backtest/live edge) |
> |---|:--:|:--:|:--:|:--:|
> | CampaignConfidence hold-engine exits | ✅ | ✅ | ✅ **sole thesis-exit owner** (legacy rotation/exhaustion/control-transfer are superseded; WATCH/REDUCE gated off) | ⚠️ in-sample only |
> | Daily one-ENTER-per-side lock | ✅ | ✅ | ✅ blocks re-entry all day | ❌ first live day 8/7 |
> | Archetype entry routes (+ hard vetoes) | ✅ | ✅ | ✅ **replaces the conjunctive stack** for entries | ⚠️ 8/5 live, veto-fixed 8/6 |
> | Premium Acceptance (absorption/rejection) | ✅ | ✅ | ✅ REJECTION vetoes / ABSORPTION lifts evidence (route mode) | ❌ |
> | Reinforcement lifecycle notes | ✅ | ✅ | n/a (notification only) | n/a |
> | Strike-surface / cluster in entries | ✅ | ✅ | ✅ via route cluster notional + SURFACE_GATE | ❌ |
> | Runner profit-management | ✅ | ✅ | ✅ (post-TP1) | ❌ |
> | Multi-expiration scan + cross-expiry direction | ✅ | ✅ | ✅ forward-expiry agreement confirms/vetoes direction (#8) | ❌ |
> | Qualified directional control (info > raw mass) | ✅ | ✅ | ✅ **re-derives side control** from qualified mass (NVDA 8/11) | ⚠️ dry-run only |
> | Reversal cluster (EXIT≠REVERSE) | ✅ | ✅ | ✅ **owns opposite-side exits** | ❌ |
> | Inventory memory + PASS (cost-basis/MFE) | ✅ | ✅ | ✅ HIGH-ambiguity abstains; MED discounts; suppresses false STRENGTHENING | ⚠️ dry-run only |
> | Package / roll resolver | ✅ | ✅ | ✅ soft EV discount + hard veto (`PKG_VETO` ON) | ❌ |
> | Portfolio correlation-risk gate | ✅ | ✅ | ✅ vetoes over-concentration at entry | ⚠️ dry-run: non-binding |
> | Rotation resolver | ✅ | ✅ | ◑ names destination on rotation exit (log) | ❌ |
> | Late-0DTE value gate | ✅ | ✅ | ✅ vetoes theta-dominated late 0DTE | ❌ |
> | Multi-hypothesis (H1–H8) | ✅ | ✅ | ✅ soft + abstain-on-ambiguity (`HYP_PASS` ON) | ❌ |
> | Data-quality / quote-sync | ✅ | ✅ | ✅ drops invalid snapshots; cuts stale-quote confidence | ❌ |
> | Hedge-flow (directional vs convexity) | ✅ | ✅ | ◑ soft EV discount | ❌ |
> | Premium decomposition (delta/gamma/IV) | ✅ | ✅ | n/a (feeds hedge + log) | n/a |
> | Regime context | ✅ | ✅ | ◑ confidence modifier only | ❌ |
> | Campaign end taxonomy | ✅ | ✅ | n/a (historical memory) | n/a |
> | Multi-campaign (no tournament) | ✅ | ✅ | ✅ up to MAX_PRIMARY_POSITIONS (4); incumbent doesn't block challenger | ❌ new 8/17 |
> | Reversal owns opposite exits (raw-flip disabled) | ✅ | ✅ | ✅ raw control flip can't flatten (item 13) | ❌ new 8/17 |
> | FORMING spot-exemption (volume senior) | ✅ | ✅ | ✅ exceptional events not spot-gated (item 9) | ❌ |
> | Inventory micro-distribution | ✅ | ✅ | ✅ suppresses false STRENGTHENING (item 5) | ❌ |
> | ContractValueMemory (robust-value cheapness) | ✅ | ✅ | ✅ overrides session-low reject (item 4) | ❌ |
> | InformationMass (discovery blend) | ✅ | ✅ | ◑ discovery_share blend (item 15) | ❌ |
> | Attention-transfer (continuous) | ✅ | ✅ | ◑ priority-investigate log (item 12) | ❌ |
> | ExpirySelector | ✅ | ✅ | ❌ shadow/log only (item 10) | n/a |
> | Decision Ledger (all veto reasons) | ✅ | ✅ | n/a (diagnostics → jakenew_decisions.jsonl, item 17) | n/a |
> | Time-of-day BarVolumeShock | ✅ | ❌ | ❌ built+tested, NOT wired (needs multi-session history, item 7) | n/a |
> | T+1 OI confirmation | ✅ | ❌ | ❌ needs Schwab OI (off) | n/a |
>
> **Allowed exits that bypass the hold engine (by design):** hard stop, EOD flatten, a **qualified
> ReversalCluster activation** (NOT a raw control flip — v3-review item 13), and profit objective
> (TP/trail/runner). Everything else about staying-in vs leaving is decided by CampaignConfidence,
> logged per-poll as `… HOLD conf=… (Δ… ctrl_ok=… dist=…)` and, on exit, `decided_by=CAMPAIGN_CONFIDENCE`.

> **Pre-open readiness check — 2026-08-16 (for the 08-17 session).** Verified live: 39/39 test files
> pass; all modules compile; `main.py` imports; state file healthy (flat, 5 campaigns queued for
> session-roll carry-forward). Alpaca **data feed LIVE** (`data.verify()`=True — the hard dependency)
> and **paper execution verified** (`exec.verify()`=True, portfolio ≈ $75k, 0 positions,
> `ALPACA_PAPER=True`). Scheduler `Jakenew_DailyRun` = Ready, next run **Mon 08:10 CST**, Mon–Fri,
> last result 0. End-to-end poll smoke: 8 polls, 0 exceptions, all candidate reads populate. Schwab is
> **optional** (degrades to Alpaca-only; OI-confirm off) so its stale token is not a blocker. Net
> new day-one behavior vs prior sessions: **up to 4 concurrent campaigns** + the **absolute-event
> activation route** — expect more, lower-rank entries; watch `jakenew_decisions.jsonl`.

> **Campaign-flow policy (2026-10-17, `Logic for Jake.txt` Oct-15 revision) — runs beside the engine below.**
> A second, separate policy (`campaign_flow/`) is evaluated on the **same 5-second polls** as everything in this
> document. `CF_MODE=SHADOW` (default): it decides and journals, and its fills come from a simulated broker
> (tagged SIM, never published). `CF_MODE=PAPER`: it owns the Alpaca **paper** orders and the legacy engine
> keeps computing but stops ordering and stops the EOD account-wide liquidation. Full description in
> **Campaign-flow policy** at the end of this document; compare both with `python cf_report.py <session>`.
> **Live `.env` as of 2026-10-17: `CF_MODE=PAPER`, `CF_DISCORD_ENABLED=true`.** The campaign-flow policy owns the
> paper orders and posts its ENTRY/EXIT cards; the legacy engine below runs for comparison only (no orders,
> no EOD liquidation).

---

## The core idea

Volume alone means nothing. The engine asks five questions, in order:

1. **Which ticker** is receiving the greatest share of *fresh, relevant* Mag-7 option premium?
2. **Which side** (calls or puts) actually controls that ticker?
3. Is this a **genuinely new attention wave**, or just another minute inside one we already know?
4. Is the option **accumulating** (premium expanding while cheap) or **distributing** (heavy
   volume while premium bleeds)?
5. Has the wave **ended**, hit its objective, or **rotated** to another ticker?

A trade is born when a *new* wave, on the *qualified-controlling* side of a ticker with **exceptional
absolute event/campaign quality**, shows *accumulation* while the contract is still cheap by robust
value. Attention rank guides *where to look first* — it is NOT an eligibility requirement (a rank #2/#3
ticker with a pristine event qualifies; multiple Mag-7 campaigns coexist — v3-review items 1-2, 21).
All of that is rolled
into **one explicit verdict** — *"is this a genuine institutional campaign starting while convexity
is still cheap?"* (see **The campaign verdict** below). The engine does not ask "did a threshold get
crossed?"; it asks whether a campaign is being born.

---

## The trading day (times in Central)

| Time | What happens |
|---|---|
| **~8:10 AM** | Scheduled task launches `main.py` (wakes the PC if asleep). Connects to Alpaca (+ Schwab if a token exists). Idle until 8:20. |
| **8:20 – 8:30** | **Pre-open seeding.** Reads every contract every few seconds and records volume baselines — no trading. This is what lets the engine measure the opening auction as *fresh* flow instead of discarding it. |
| **8:30** | **Open.** Fresh volume counts from the first seconds, including the opening burst (often the clearest institutional commitment of the day). |
| **8:30 – 8:35** | **Opening window** — trading is live but the quality floors are raised ~1.4×. |
| **8:35 → 2:55 PM** | Full-speed. Each cycle fetches the Mag-7 **in parallel** (~1.7 s), processes them, then sleeps **5 s**; scoring runs over rolling **30s / 60s / 180s** windows. |
| **2:55 PM** | End-of-day flatten — everything closed (same-day convexity is never carried). |

**Expiry is dynamic** — each name uses its true nearest listed expiry (0DTE when it exists, else
1DTE / the nearest weekly). It is *not* 0DTE-only. **Confirmation is DTE-sensitive** — a 0DTE has
only ~30–90s before its convexity is gone, so it is promoted and entered on very little
persistence; a 1DTE is allowed more; 2DTE+ demands the most (see the timing table below).

---

## Layer 1 — which ticker owns attention?

Every poll, for each name, the engine turns option activity into **mass**:

```
mass(contract) = fresh_volume × option_price × 100 × strike_relevance
```

where `strike_relevance = exp(-α·|K−S|/S)` weights ATM ≈ 1, one strike ≈ 0.8, two ≈ 0.6, fading
fast. Summed to CallMass / PutMass / TickerMass, and each ticker's **AttentionShare** = its mass ÷
the whole Mag-7 pool.

Then three things separate a *fresh surge* from activity that's merely *stayed elevated*:

- **Fast / slow EWMA + Impulse** — a fast average reacts immediately, a slow one is the recent
  norm; `Impulse = fast / slow` flags a genuine acceleration.
- **Attention Shock (Z-score)** — how abnormal this is versus the ticker's *own* rolling baseline
  (robust mean/MAD, always adapting so a wave that just sits elevated decays back toward zero). A
  name doing 5× its normal outranks a name that's always busy.
- **Velocity / Acceleration** — is mass rising, and is the rise speeding up?

An **Attention Score** (35% share · 20% shock · 15% velocity · 10% acceleration · 10% side
dominance · 10% strike quality) ranks all seven. Weights are research knobs, not gospel.

---

## Layer 2 — which side controls it?

More call premium does **not** prove bullish call *buying* (it can be selling, spreads, rolls,
hedges). Control blends premium share with the opposite side's **awakening** (is it accelerating?),
**persistence** across polls, and **quote-location** (marks lifting the ask = buying). It resolves
to one of five states: `CALL_CONTROL · CALL_CONTROL_PUTS_AWAKENING · BALANCED_CONTEST ·
PUT_CONTROL_CALLS_AWAKENING · PUT_CONTROL`. A contested name is never traded.

---

## Layer 3 — the attention-wave state machine (one wave = one entry)

Each ticker/side has one persistent **wave** with a unique id, moving through:

```
DORMANT → FORMING → ACTIVE → MATURE → DECAYING → ENDED
```

- **FORMING** — mass becomes abnormal (Z ≥ 2), share rising, side control meaningful, velocity
  positive. The wave records its **event price** here (used later to judge accumulation). FORMING
  is **tradeable** (we enter early to capture convexity) but only under a stricter early-asymmetry
  test — see Entry.
- **ACTIVE** — reached by one of two routes:
  - **Fast route** (exceptional evidence now): overwhelming burst (Z ≥ 4, share ≥ 0.40, control
    ≥ 0.70, velocity & acceleration positive) → promote immediately.
  - **Slow route** (persistence develops): sustained (share ≥ 0.30, control ≥ 0.60, Z ≥ 3) for a
    number of consecutive polls that **scales with DTE** (below).
- **MATURE / DECAYING** — still dominant but acceleration turned negative / share falling.
- **ENDED** — exhausted, control transferred, rotated away, a structural/EOD stop, or —
  **`FAILED_FORMATION`** — a FORMING wave that never confirmed inside its DTE-sensitive maximum
  window (the two-stage "upgrade or kill the thesis" made concrete).

**DTE-sensitive confirmation / hold windows** (a fixed wait is wrong for options that decay at
very different speeds):

| DTE | Slow-route confirmations | Min-hold (young-wave protection) | Max FORMING window → FAILED_FORMATION |
|---|--:|--:|--:|
| **0DTE** | 1 | 120 s | 120 s |
| **1DTE** | 2 | 180 s | 300 s |
| **2DTE+** | 3 | 240 s | 600 s |
| *unknown* | 3 | 180 s | none (old fixed behaviour) |

A wave issues **at most one primary entry**. Every later elevated minute is a *wave update*
(strengthening / peaking / decaying), **not** a new trade. This is what killed the old churn
(the same idea used to fire ~25 entries/day; now it's a handful).

---

## Accumulation vs distribution — the price-response filter

This is the piece that stops the engine buying "big volume" that is really people *getting out*.

When a wave forms it stamps the option's **event price**. At entry the engine checks how the
premium has **responded**:

- **Accumulation** — premium is *expanding* off the event while the contract is still near its
  value low, in a compact burst. Labeled `COMPACT_ACCUMULATION` / `PERSISTENT_ACCUMULATION` /
  `SINGLE_STRIKE_ACCUMULATION` / `COORDINATED_CHAIN_ACCUMULATION`. **Tradeable.**
- **Distribution** — heavy volume while the premium *collapses* or is already extended/mature, or
  volume smeared broadly with no compact start. Labeled `HEAVY_VOLUME_NEGATIVE_RESPONSE` /
  `MATURE_DISTRIBUTION` / `LATE_CHASING_ACTIVITY` / `DISTRIBUTED_BACKGROUND` /
  `EXHAUSTION_ACTIVITY`. **Management info only — never a new entry.**

It reads the contract's per-minute volume series into shape metrics — EventShare20, Top3Share20,
DominantSingleBar, BurstPersistence, CompactCluster, PersistentDistributedFlow, and **VolumeSkew**
(did the volume arrive early, centrally, or late in the window?) — and classifies the **event
shape**: `DORMANT_BACKGROUND · ISOLATED_PRINT · COMPACT_SHOCK · PERSISTENT_COMPACT_WAVE ·
DISTRIBUTED_BACKGROUND · MATURE_SCALING_ACTIVITY · DISTRIBUTION_AT_PREMIUM_HIGH ·
STALE_OPENING_VOLUME · EXHAUSTION_OR_EXIT_FLOW`. Only `COMPACT_SHOCK` and `PERSISTENT_COMPACT_WAVE`
(with a positive premium response) are entry-eligible. `DISTRIBUTION_AT_PREMIUM_HIGH` (heavy volume
already extended from the low while the premium gives back) and `STALE_OPENING_VOLUME` (volume that
arrived early and has since gone quiet) are explicit distribution/stale tells. The canonical
positive case is the TSLA 312.5P pattern: dormant → compact abnormal shock near the contract low →
premium expands immediately.

### Single strike vs chain — chains must prove more

A chain is a *synchronised shape*, not three mediocre strikes summed. To be a `COORDINATED_CHAIN`
(not `SINGLE_STRIKE_DOMINANT`), two strikes must **each** own a meaningful share of the side's mass,
a real second participant must exist (≥28% of side mass), and the top two together must dominate
(≥70%). Chain entries then face a **1.5× higher notional floor** than single strikes. One strike
carrying almost all the volume is correctly labeled `SINGLE_STRIKE_DOMINANT` — never a fake chain.

---

## Event shape *through time* — the same volume means different things at different moments

Equal contract counts are not economically equal: 1,000 contracts at $1.00 (fresh accumulation
near value) is not 1,000 at $6.00 (after a move — far more likely profit-taking, closing, or late
chasing). So the engine measures not just *how much* flow, but **where in the option's life it
arrives and how the price, IV and spot respond**. Every poll it computes, for the candidate
contract:

- **Response efficiency** — `ΔP% ÷ (fresh notional / $100k)`: how much premium progress each unit
  of flow bought. High in early accumulation ($300k → +35%), low or negative in maturity /
  distribution ($1.2M → flat). Its **decay** from the campaign's peak efficiency is a distribution
  tell (more and more flow buying less and less progress).
- **Relative-to-accumulation ratios** — current contracts / notional / premium vs the campaign's
  *start*. Premium 6× the campaign start with flat response = maturity, not a fresh event.
- **IV velocity (dIV/dt)** — IV rising/firm supports accumulation; IV rolling over while premium
  stalls supports distribution. (Contributing signal; not always available in historical data.)
- **Spot-direction confirmation (dS/dt)** — is the underlying moving the right way for the side?
- **Delta-adjusted notional** — `contracts × price × 100 × |Δ|`, directional exposure rather than
  gross dollars.
- **Opposite-side acceleration** — is the *other* side building its own coherent campaign?

These fold into a single **distribution probability** (a weighted logistic — no one component
decides it): high when the premium is extended, response efficiency is decaying, the premium is
already a large multiple of the campaign start, IV is rolling over, the premium is giving back from
its peak, the opposite side is accelerating, and spot is not confirming. A high distribution
probability **vetoes** a new entry and drives the **WATCH/REDUCE** trim on a live position.

### Campaign lifecycle — self-sustainability, delayed convexity, continuation (`analysis/lifecycle.py`)

The clearest institutional signatures are *temporal*. The engine measures the campaign's arc:

- **Self-sustainability** — is the premium **still rising while the buying fades**? The AAPL/TSLA
  signature: inventory is accumulated in a compact burst, volume then declines, yet the premium
  keeps climbing — the move has become self-sustaining. High when recent volume has dropped well
  below the campaign's peak *and* the recent premium slope is still positive; low when the premium
  stalls the instant volume drops.
- **Windowed premium response + delayed convexity** — response is judged across **30/60/90/180/300s**
  windows plus **max-favourable-excursion** and the **area under the premium curve**, not just the
  latest bar. A compact campaign that briefly **consolidated** — showed a real positive excursion
  and, after a **shakeout** (dip below the event price that flushes weak hands), is recovering back
  through it — is **not rejected** for a slightly-negative instant response (the NVDA-put case).
  A genuine collapse below the delayed floor is still rejected.
- **Premium-efficiency trend** — is `ΔP per unit flow` **RISING / STABLE / DECAYING** across polls?
  A campaign that needs *less* incremental buying to keep rising is structurally healthier than one
  needing ever more just to hold price.
- **Continuation probability** — a joint 0-1 estimate the campaign continues (self-sustainability +
  efficiency trend + premium persistence + control + spot + recovered shakeout). It blends into the
  **P(continue)** term of expected-value entry timing.
- **Expanded shape geometry** — Gini + entropy (concentration), decay-rate, volume half-life,
  reacceleration (a second burst), and silence fraction round out the volume-through-time picture.

---

## The campaign verdict — the one question that decides a trade

Everything above rolls into a single explicit assessment (`analysis/campaign.py`): **is this a
genuine institutional campaign starting while convexity is still cheap?** A campaign is
**CONFIRMED** only when all five entry signals hold *and* the combined conviction clears a minimum
score. The verdict names the six campaign signals the detector exists to find:

1. **WHERE capital is concentrating** — this ticker leads the Mag-7 fresh-premium pool
2. **dormant WAKING UP** — a statistical shock (z ≥ 3)
3. **accumulation BEGINNING** — positive premium response in a compact shape
4. **who CONTROLS the tape** — the trade side owns ≥ 66% of fresh premium
5. **still CHEAP** — the contract is ≤ 1.5× its value low
6. **campaign ENDING** — narrated on exit (control transferred / rotated to a stronger campaign /
   statistically exhausted / objective reached)

The verdict combines a five-signal weighted score with a **heuristic posterior proxy** (v3-review
item 7 — *not* a calibrated Bayesian probability until calibration proves it; also called the
**continuation-evidence score**): a context prior (morning bias, DTE) updated by the likelihood ratio
of each observed signal — must clear their thresholds. Entry then also requires **positive expected
value**:

```
ExpectedEntryValue = P(continue) · RemainingConvexity − P(false) · ExpectedLoss
```

where `P(continue)` is the posterior, `RemainingConvexity` blends how fresh (un-run) and how cheap
the contract still is, `P(false)` is the distribution probability, and `ExpectedLoss` ≈ the hard
stop. The optimum is **not** maximum confirmation: as the engine waits, `P(continue)` rises but
`RemainingConvexity` falls — so it enters at the *earliest positive-asymmetry* moment.

Every entry logs a plain thesis — *"CAMPAIGN CONFIRMED — AAPL calls lead the Mag-7 (52% of fresh
premium); dormant flow woke (z=4.2); accumulation begun; calls control the tape (0.90); still cheap
(1.2× low)."* — plus `post=… dist=… ev=… eff=…`. Every exit logs *"CAMPAIGN ENDED: attention rotated
to a stronger campaign."* This is §14/§15 made concrete: the engine thinks in campaigns, not thresholds.

---

## Entry — every condition must hold

A new position opens only when **all** are true (and the unified campaign verdict is CONFIRMED):

1. A **new wave** has reached entry-eligibility (FORMING or ACTIVE — we enter early, on value).
2. The ticker is within the **discovery window** (top `ROUTE_MAX_RANK`, default 3) — attention rank
   is discovery context, NOT a rank-1 tournament; absolute event/campaign quality is what qualifies,
   and multiple Mag-7 campaigns may coexist (v3-review items 1-2). *(Legacy rank-1 + lead-margin
   applies only if `ENTRY_ROUTES_ENABLED` is off.)*
3. **Qualified control** belongs to the trade direction — economic-intent-weighted flow (after event
   morphology / inventory / package / acceptance discounts), NOT raw call-vs-put premium share
   (v3-review item 3; `qualified.py`). Raw ≥66%-share is no longer authoritative on its own.
4. **Accumulation**, not distribution (positive premium response, compact shape) — *or* a
   **delayed-convexity** campaign that briefly consolidated (positive prior excursion + recovering
   shakeout), which is tolerated rather than rejected.
5. The contract is **on value** — mark ≤ **1.5× its session low** (never chase after the pop).
6. Freshness isn't `MISSED`, notional clears the floor (higher for chains), quote liquid / not stale.
7. The **campaign verdict is CONFIRMED** — five signals present, linear score ≥ minimum, **and**
   heuristic posterior proxy ≥ minimum (uncalibrated — see item 7).
8. **Distribution probability** is below the entry veto, and **expected value is positive**.
9. If the wave is still **FORMING** (not yet ACTIVE), it faces the **stricter early-asymmetry
   test**: higher posterior, lower distribution probability, larger EV, and positive spot
   confirmation. (Optional gates, off by default: delta-adjusted-notional floor, IV-firmness.)

It buys the best contract among **ATM ± 1 strike** at a bounded limit (mid + small offset, capped
at the ask — never a naked market order), sized at `TRADE_PCT` of portfolio, with duplicate-order
protection. **No new entries in the final 15 minutes** before the flatten.

---

## Exits — two real reasons, plus a hard stop

**A — Objective met (profit):** +60% → sell half · +150% → sell the rest · trailing giveback
(once up +40%, give back 35% from the peak → out).

> **The giveback trail does NOT own a position before TP1** (`TRAIL_REQUIRE_TP1`, default on).
> A 0DTE contract routinely gives back 35% of a *sub-TP1* peak on an ordinary high-gamma retracement
> and then resumes — that is quote noise (gamma/theta/IV/spread), not campaign death. Arming the trail
> at +40% (below the +60% TP1) liquidated the **08/28 AMZN 260C near flat** after it peaked ~+56%,
> minutes before the campaign produced the major move. So **before TP1 there is no premium trail**: the
> position is held only by the hard stop, the reversal manager, distribution, the hold engine and EOD —
> thesis exits, not a premium stop. **After** TP1 is banked, the giveback trail resumes protecting the
> realised gains as before. Set `TRAIL_REQUIRE_TP1=false` to restore the legacy pre-TP1 trail. The rule
> is the pure `campaign.trail_should_exit(...)` (unit-tested in `test_exits.py`, AMZN case).

**A′ — WATCH/REDUCE (deterioration, not yet death):** if the **distribution probability** rises
past its reduce threshold *and* the premium has given back ≥15% from its peak while the wave thesis
is still alive, the engine **trims once** to de-risk (distinct from the profit scale-out) and lets
the remainder run to its objective or a real thesis exit.

**B — Thesis died (asymmetric, so 0DTE gains aren't lost to slow confirmation):**
- **Immediate** — the opposite side seizes overwhelming control (very high bar) → out at once.
- **Confirmed control transfer** — opposite side genuinely controls (persistent) → out.
- **Rotation** — another ticker confirms a stronger wave *and our own wave is already fading*
  (a healthy leader is never abandoned for a briefly-higher score).
- **Statistical exhaustion** — Z < 1, velocity ≤ 0, share < 0.15 for several polls.

A **minimum-hold** protects a young wave from B for ~3 minutes (unless an overwhelming flip), so
normal one-minute noise can't churn it. After a wave ends, a **refractory** (~12–20 min) prevents
re-entering the same name on residual volume unless an exceptional fresh shock appears.

**C — Hard stop-loss** — a risk backstop at −40% that fires regardless of thesis or min-hold,
capping the per-trade tail. **No new entries** are opened within 15 minutes of the flatten (avoids
late 0DTE lottery tickets and can't leave a fill open past the close).

**D — 2:55 PM** flatten no matter what; the process then exits so the next day's launch starts
fresh with the on-disk code.

---

## Next-architecture upgrades (built behind flags — NOW ALL ENABLED live on paper)

> **Historical note:** the P1–P8 / follow-up descriptions below were written during the *shadow
> rollout*, when each layer defaulted OFF pending backtest — that is why they say "default OFF /
> pending backtest / shadow." As of **2026-08-15** every one of these flags is **ON** in the live
> paper `.env` (see the authoritative status banner at the top). Read the per-layer "default OFF" notes
> as code-default + rollout history, not the current runtime.


A consolidated developer spec asked the engine to grow from an attention-wave detector into a
**stateful, multi-expiration, multi-archetype institutional-campaign tracker**. That is being built
in the spec's own priority order (P1→P8). **Every new layer is gated by a flag that defaults OFF**,
so the validated live-paper entries/exits are *identical* to before until a backtest proves the new
logic and the flag is turned on deliberately — the same shadow rollout used for the lifecycle layer.

**P1 — campaign memory / stabilization (fix premature exits).** The old engine conflated three
different things: a cooling Z-score, a lost attention rank, and campaign *death*. They are not the
same — a big burst naturally becomes *less* statistically abnormal as time passes; that is not
failure. With `STABILIZE_ENABLED=true` the wave machine gains a **STABILIZING** state: a wave that is
cooling but **structurally intact** (still controls its side, faces no strong opposite-side campaign,
is not distributing, and premium has not failed) moves ACTIVE→STABILIZING and *keeps its campaign
memory* instead of decaying into a statistical-exhaustion exit. It returns to ACTIVE (same wave_id,
no new entry) if it reaccelerates, and only accrues exhaustion on **coherent multi-signal
deterioration** — or after it has stabilised far past `WAVE_STABILIZE_MAX_S` (15 min) without
reviving. A **ROTATION** exit now also requires the incumbent's own campaign to be materially
deteriorating (`ROTATION_REQUIRE_INCUMBENT_WEAK`), never just being out-ranked. This directly targets
the observed one-to-six-minute scratch exits (`STATISTICAL_EXHAUSTION`/`ROTATION`) that closed
still-controlled positions. Engine feeds a per-`(ticker,side)` structural-health read into the wave
machine; with the flag off no health is computed and the code path is unchanged. Tests:
`test_waves.py` (+3 stabilization checks). *Default OFF — pending backtest.*

**P2 — early detection / latency (reduce detection lag).** The jump from "nothing" to "ENTER" was
too large and gave no way to measure *how late* the engine acts. With `EARLY_DETECT_ENABLED=true`
the wave machine gains two **observation-only** pre-entry stages recorded *before* the FORMING birth
threshold: **WATCH** (first abnormal print with minimal one-sidedness) and **BUILDING** (sustained
participation + emerging control). These record timestamps only — they do **not** change when the
engine enters (still FORMING/ACTIVE + the §16/EV gates). At entry the engine now logs a **LATENCY**
line — abnormal→alert, watch→alert, building→alert, accumulation→alert, premium drift (alert price ÷
campaign-start price) — so detection/decision latency becomes a first-class, trackable metric. A new
**EarlyAccumulationScore** (`campaign.early_accumulation_score`, always computed and logged, gates
nothing on its own) scores the *earliest favorable phase* — fresh-premium velocity, abnormal
participation, value proximity, emerging control, firming/recovering response, low distribution — and
is deliberately distinct from mature campaign confidence. Tests: `test_waves.py` (+3 early-detection /
EAS checks). *Default OFF for the WATCH/BUILDING logging; EAS computes harmlessly. Pending backtest.*

**P3 — multi-expiration scanning (`analysis/expiry.py`).** The base engine centres on the *nearest*
expiry, so a thesis expressed across expirations is invisible (NVDA 0DTE puts while Friday calls
build; forward positioning ahead of a catalyst). With `MULTI_EXPIRY_ENABLED=true` the engine runs a
**throttled shadow scan** (at most every `MULTI_EXPIRY_POLL_S`, default 60s) over several relevant
expiries — the nearest (0DTE if listed), the nearest strictly-future, the current-week Friday, and
the following weekly — and derives the **per-expiry share and controlling side**, the **near→forward
migration** of capital over the session, and a structural classification (`SAME_DAY_ACCUMULATION`,
`FORWARD_POSITIONING`, `SAME_SIDE_MULTI_EXPIRY_CONTROL`, `NEAR_TERM_PUT_FORWARD_CALL`, …). It emits an
**EXPIRY** log line per ticker and nothing more — **entries/exits still trade the nearest expiry**;
wiring expiry structure into the entry decision is a later, separately-gated step. The shadow scan
uses cumulative (not fresh) volume as a coarse mass proxy, which is enough for share/control/migration
direction. Data layer gains `get_scan_expiries()`; `get_nearest_expiry()` is unchanged. Tests:
`test_expiry.py` (14 checks). *Default OFF — shadow, no entry impact.*

**P4 — campaign archetypes (`analysis/archetype.py`).** The base engine over-rewards one shape,
the compact 0DTE shock. Institutional commitment actually appears in several forms, and each has
different expectations for how premium *should* behave. Every candidate is now classified into an
archetype — **SHOCK_ACCUMULATION, PERSISTENT_ACCUMULATION, SELF_SUSTAINING_EXPANSION** (premium
rising as volume fades — the AAPL case), **SHAKEOUT_AND_RECOVERY, STAIR_STEP_ACCUMULATION,
IMPULSE_REPRICING, FORWARD_POSITIONING / CROSS_EXPIRY_ACCUMULATION** (from the P3 expiry scan),
**DISTRIBUTION**, or UNCLASSIFIED — from features already computed (volume geometry, abnormality,
response, self-sustainability, distribution probability). It is logged at entry (an **ARCHETYPE**
line) and stored on the position. `ARCHETYPE_ENABLED` (default **true**) only computes + logs the
label — it changes nothing. Applying archetype-specific *entry* expectations is reserved behind
`ARCHETYPE_GATE_ENABLED` (default **false**) and not wired in yet. Tests: `test_archetype.py`
(9 checks). *Classification is live-harmless; behavioural use is OFF.*

**P5 — distributed strike-surface aggregation (`analysis/strikes.py`).** The base engine asks a
*contract-selection* question ("which single strike dominates?") and can therefore miss a real
ticker-level campaign spread across a ladder — the AMZN case, calls distributed over ~237.5…257.5
with no single strike passing a dominant-strike test. This layer answers the **ticker-level**
question first ("is capital concentrating in this side across the surface?") and only then names a
representative contract (nearest the mass-weighted center). It computes surface measures —
LadderMass, participation **breadth**, concentration (HHI), dispersion, weighted center, strike
**momentum**, and a **breadth-adjusted strength** that *rewards* broad participation — and classifies
the surface: SINGLE_STRIKE_DOMINANT, TWO_STRIKE_COORDINATED, ADJACENT_STRIKE_LADDER,
**BROAD_SURFACE_ACCUMULATION** (the AMZN campaign — broad participation is not weak participation),
DISTRIBUTED_BACKGROUND, THIN. `SURFACE_ENABLED` (default **true**) computes + logs a **SURFACE** line
per entry; letting a broad-surface campaign qualify *without* a dominant strike is reserved behind
`SURFACE_GATE_ENABLED` (default **false**). Tests: `test_strikes.py` (11 checks, incl. an explicit
AMZN-ladder case). *Profile is live-harmless; behavioural use is OFF.*

**P6 — campaign replay + candidate archive (`analysis/replay.py`).** Development cannot depend on
hand-picked screenshots. With `RESEARCH_ARCHIVE_ENABLED=true` the engine appends a structured JSONL
record (the §46 field set — attention/abnormality, chosen contract, accumulation/response/lifecycle,
plus the new EAS/archetype/surface reads) for the top-K candidates every `RESEARCH_ARCHIVE_EVERY_S`,
**and** a record at every entry (`ENTERED`/`REJECTED`) and exit (`EXIT` with P&L + hold time). That
lets a campaign be reconstructed poll-by-poll and a **missed winner** turned into a reproducible
diagnostic (`diagnose_missed`): did the ticker ever rank top-1/2/3, was accumulation ever present,
which gate blocked it most, or was it genuinely invisible? All record-building is pure; the archive
is a swallow-errors JSONL appender, so research logging can never disrupt the loop. Default **OFF** —
when off, no record is built and nothing is written. Tests: `test_replay.py` (9 checks incl. an
archive round-trip). *This is the layer that makes P1–P5/P7–P8 honestly validatable.*

**P7 — profit-taking revalidation / runner + exit taxonomy.** The fixed +60% / +150% ladder
mechanically forfeits the +300/+500/+1000% campaigns the engine exists to catch. With
`RUNNER_ENABLED=true`, half is still banked at +TP1, but the rest becomes a **runner** held while
the campaign is intact — exited only on coherent **distribution** (dist-prob ≥ exit), a **wide,
expiry-aware trail** (arms past +100%, gives back 50% of peak, vs the base 40%/35%), an optional hard
ceiling, control transfer, or EOD — instead of a hard +150% close. The **−40% hard stop stays a pure
backstop.** Every exit is also tagged into a **taxonomy** (`campaign.exit_category`: OBJECTIVE /
THESIS_DEATH / DISTRIBUTION / CONTROL_TRANSFER / RISK_STOP / EOD) and each position now tracks MFE
**and MAE**, both written to the archive for by-archetype / by-DTE exit-quality analysis. Default
**OFF** → the validated +60/+150 ladder is unchanged live. Tests: `test_exits.py` (16 checks).
*Runner behaviour OFF pending backtest; taxonomy/MAE logging is live-harmless.*

**P8 — honest probability calibration (`analysis/calibration.py`).** The engine gates on a
"posterior" (`CAMPAIGN_MIN_POSTERIOR = 0.55`) and blends a continuation probability into EV. Calling
that **Bayesian** is only honest if it is *calibrated* — so the terminology is corrected everywhere to
a **heuristic posterior proxy (uncalibrated)**, and until proven, 0.55 is a heuristic knob, not a
true 55%. The new module measures calibration from the P6 archive: **Brier score, log loss, a
reliability curve + Expected Calibration Error, and a decile table** (predicted-probability decile →
realized continuation rate), with `slice_reports` to check **stability by archetype / DTE / symbol**.
`pairs_from_archive` builds (probability, outcome) pairs by matching each ENTERED record to its EXIT
P&L; `python -m analysis.calibration` prints the report over the archive. Tests: `test_calibration.py`
(13 checks). This is a *measurement* tool — it changes no trading behaviour; it tells us whether the
proxy deserves to be trusted (and, per the deferred-research note, whether the heavier statistical
machinery is yet justified).

### Addendum subsystems — inventory / packages / portfolio (2026-08-15, ON for the paper run)

The consolidated addendum named the "biggest remaining blind spots": the engine was modeling **events
and campaigns** while institutions actually manage **inventory**. Three new layers close that gap.
Each is flag-gated (default ON in `.env` for the paper forward-test) and the read is wrapped so a
data-shape surprise can never break a poll.

**Inventory Memory (`analysis/inventory.py`, `INVENTORY_ENABLED`).** *A print has no meaning in
isolation from the inventory history that preceded it.* Per surviving contract
(`ticker|side|strike|expiry`) the engine remembers each significant print (size + price) as a
size-weighted **cost-basis zone**, and derives on every fresh print: **drift** vs basis,
**MarginalFlowEfficiency** (ΔP since the last clip ÷ that clip's size — the genuinely marginal read),
an **inventory state** (`UNKNOWN / LIKELY_BUILDING / LIKELY_FUNDED / LIKELY_PARTIAL_EXIT`) and an
**ambiguity** (`LOW/MED/HIGH`). The flagship case — *yesterday 1,000 @ $3, today 1,000 @ $1* — lands
far **below** basis, so unwind-vs-fresh is genuinely ambiguous → **HIGH → `INVENTORY_AMBIGUITY_PASS`**
(a first-class abstain; passing is a feature, not a failure). A clip **far above** basis whose
marginal MFE has **stalled** is distribution-into-strength → also HIGH. MED softly discounts
`P(continue)` before the EV gate; HIGH abstains. The same memory suppresses a false **CAMPAIGN
STRENGTHENING** when same-side flow on a held position no longer advances premium (weak MFE = the
"slow hidden exit"). Records are **cross-session**, pruned only when the expiry dies (like campaign
memory). Tests: `test_inventory.py` (15 checks).

**Package / Leg / Roll Resolver (`analysis/packages.py`, `PACKAGES_ENABLED`).** A gorgeous
single-strike print can be one leg of a vertical / calendar / roll / ratio / straddle. Without
buy/sell tags we resolve by **size-matched co-prints** on the surface within a poll: adjacent
same-side match → `VERTICAL_LIKELY`; same-strike call+put → `STRADDLE_COMBO_LIKELY`; ~2:1 ratio →
`RATIO_LIKELY`; equal same-strike/side in a neighboring expiry → `ROLL_LIKELY`; otherwise
`OUTRIGHT_LIKELY`. A leg-looking contract is **discounted** (its `P(continue)` is cut by
`PKG_DISCOUNT`), and — behind `PKG_VETO_ENABLED` (**OFF** for Monday: observe first) — hard-rejected.
Tests: `test_packages.py` (9 checks).

**Portfolio correlation risk (`analysis/portfolio.py`, `PORTFOLIO_RISK_ENABLED`).** Discovery stays
unconstrained (multiple Mag-7 campaigns may coexist — safeguard #7), but the Mag-7 are **one
correlated factor**: four independent CALL campaigns is really one big long-Nasdaq bet. This layer
aggregates same-direction exposure across open positions and, at entry only, **vetoes** a new leg that
would push correlated same-direction campaigns past `PORT_MAX_CORR_SIDE` (default 4) — a risk gate,
never a discovery or hold constraint, and it never forces an exit. Tests: `test_portfolio.py` (7
checks). New entry-reject reasons: `INVENTORY_AMBIGUITY_PASS`, `PACKAGE_LEG_REJECTION`,
`PORTFOLIO_CONCENTRATION_LIMIT`.

> **Flag status (2026-08-15):** the entire new-spec cluster (qualified control, reversal cluster, exit
> arbitration, campaign confidence, stabilize, entry routes, daily lock, event-select, barshock gate,
> surface gate, cross-session memory, early detect, opening quality, archetype gate, multi-expiry,
> runner) **and** these three addendum subsystems are **ON** in `.env`. Execution is **Alpaca PAPER**
> (`ALPACA_ENABLED=true`, `ALPACA_PAPER=true`) — simulated money, live paper forward-test.

### Final gap-closure — the remaining spec/addendum items (2026-08-15, ON for paper)

The last partials and unbuilt items were implemented as pure, tested, flag-gated modules. All wired
poll-safe (every candidate-side read is exception-guarded), default ON for the paper run; the two
hard-gate *abstain* variants (hypotheses PASS, package veto) are left OFF to observe first.

- **§23-24 Rotation resolver** (`rotation.py`) — on a rotation exit, name WHERE attention went
  (Δattention + event shape + control) and log the destination for the entry engine to interrogate
  the same poll, instead of the generic queue.
- **§36 late-day 0DTE value + #6 overnight carry + #8 cross-expiry direction** (`expiry_value.py`) —
  `LateDay0DTEValue = strength×activation×remaining_convexity − θ·theta_risk`, theta ramping through
  the session so a weak late 0DTE is vetoed; forward-expiry control agreement now *confirms or vetoes*
  a direction (was shadow-log); a restored overnight campaign is classified CONTINUATION /
  OPENING_MONETIZATION / ROLL_FORWARD / REVERSAL before new discovery.
- **#4 inventory depletion** (`inventory.depletion`) — coarse remaining-inventory ladder
  FUNDED → PARTIAL_EXIT → MAJORITY_EXITED → LIKELY_CLOSED from distribution-near-strength evidence.
- **#9 multi-hypothesis engine** (`hypotheses.py`) — competing H1–H8 (fresh directional / closing
  profitable / closing losing / overwrite / roll / spread leg / hedge / unknown), evidence-weighted;
  residual ambiguity can PASS (gate OFF for now, logged).
- **#11-12 data quality / quote-sync** (`dataquality.py`) — validate every OPRA snapshot before event
  detection; drop crossed/negative/no-mark; stale/wide quotes cut aggressor/acceptance confidence.
- **#13 hedge flow** (`hedge.py`) — DirectionalConfidence vs ConvexityDemandConfidence; IV bid with
  weak spot follow-through reads convexity and soft-discounts P(continue).
- **#14 premium decomposition** (`decompose.py`) — ΔP ≈ delta·ΔS + ½·gamma·ΔS² + IV residual; tags a
  move DELTA_DRIVEN vs IV_DRIVEN and feeds the hedge read.
- **#17 regime context** (`regime.py`) — macro-event (config calendar) / high-vol confidence
  *modifier*, never a hard gate.
- **#21 campaign end taxonomy** (`campaign_store.classify_end`) — FAILED / DISTRIBUTED /
  REALIZED_PROFIT / EXPIRED_PROFITABLY / ROLLED / CARRIED_OVERNIGHT / UNKNOWN, stored at close.
- **§59 + #15/#16 regression harness** (`test_regression.py`) — the named cases (NVDA 8/11, TSLA
  8/13, AAPL 307.5P, GOOGL 8/10, AMZN overnight) as **frozen-time** assertions through the pure
  classifiers (no future price is ever an input — the #15 look-ahead guard), plus a **negative
  control**: a look-alike event with identical morphology but opposite economics that the intent
  reads (hypotheses + inventory) correctly reject.

Tests: `test_rotation.py`, `test_expiry_value.py`, `test_hypotheses.py`, `test_dataquality.py`,
`test_hedge.py`, `test_decompose.py`, `test_regime.py`, `test_campaign_taxonomy.py`,
`test_regression.py` (+ inventory depletion). Full suite: **35/35 green.**

**Genuinely deferred (needs external data / calibration, not architecture):** vega/theta greeks for a
fuller decomposition (OPRA gives delta+gamma+IV only); an OPRA trade-condition/complex-order tape
(snapshot feed has no condition codes — we validate what's observable); and populating
`REGIME_EVENT_DATES` each week. These are data-availability limits, not missing logic.

### v3 architecture review — integration corrections (2026-08-16)

A full review against the NVDA/TSLA/AAPL/GOOGL/META/AMZN + overnight-inventory studies found the
danger was mostly *integration*, not missing subsystems: legacy assumptions still coexisted with the
new architecture and could recreate old failures. Corrections (all tested; wired unless noted):

- **Items 1-2 — the winner-take-all tournament is gone.** `MAX_PRIMARY_POSITIONS` was **1**; now
  `MULTI_CAMPAIGN_ENABLED` with cap **4**. A held incumbent no longer blocks an independent
  challenger — the slot cap + the portfolio-correlation gate govern concurrency. Attention rank is
  discovery, not eligibility (routes already allow rank ≤ 3).
- **Item 13 — one canonical exit path.** A raw overwhelming control flip no longer flattens a
  position (`RAW_FLIP_EXIT_DISABLED` when `REVERSAL_ENABLED`): the ReversalCluster machine owns all
  non-risk opposite-side exits. Only hard risk / EOD / profit / a *qualified* reversal can exit.
- **Item 9 — volume senior to price.** An exceptional FORMING event (posterior ≥
  `FORMING_SPOT_EXEMPT_POSTERIOR`) is no longer spot-gated (the NVDA 222.5P case); weak FORMING events
  still require spot confirmation.
- **Item 5 — inventory micro-distribution** (`inventory.micro_distribution`): cumulative small-clip
  unwind detection that does **not** need a ≥250 print — catches the slow hidden exit (1,000 accrued,
  then 100-lots into strength). Suppresses false CAMPAIGN STRENGTHENING.
- **Item 4 — ContractValueMemory** (`value_memory.py`): state-adjusted historical value; cheapness vs
  a **robust percentile** of real marks, not the corruptible session low. Overrides the crude
  `mark ≤ 1.5× session-low` reject when the robust value is genuinely cheap.
- **Item 14 — packages are probabilistic.** No complex-order tape exists, so size/time-matched legs
  emit probabilities; the hard veto fires only when complex prob ≥ `PKG_VETO_MIN_CONF` (0.75),
  otherwise a graduated EV discount — so a clean standalone isn't suppressed by a coincidence.
- **Item 15 — InformationMass** parallel to premium mass (`mass.compute_masses` → `ticker_info`;
  `discovery_share` blend): a cheap clean-convexity event isn't buried by expensive deep-ITM inventory.
- **Item 10 — ExpirySelector** (`expiry_selector.py`, **shadow**): ranks 0DTE/1DTE/next/weekly for the
  campaign; logs the recommendation (execution still nearest-expiry until wired).
- **Item 12 — continuous attention transfer**: a destination accelerating while another cools is a
  PRIORITY-INVESTIGATE signal every poll, not only on an exit.
- **Item 17 — Decision Ledger** (`decision_ledger.py` → `jakenew_decisions.jsonl`): one immutable
  record per near-candidate poll with full state, decision, owner, and **every** hard veto (not just
  the first) + code/config provenance. The tool for diagnosing false negatives without serial fixes.
- **Verified already-correct (locked with regression tests):** #8 fresh volume is a cumulative-day
  delta, so a forming minute is never multiply-counted; #6 a dominant standalone classifies as
  `SHOCK_ACCUMULATION` and is entry-eligible.
- **Item 7 — time-of-day BarVolumeShock** (`barshock.session_phase` / `bar_shock_tod`): built + tested
  but **not wired** — its baseline needs multi-session history to be useful, so wiring it adds risk for
  zero day-one benefit; deferred deliberately.

### Final canonicalization pass (2026-08-16) — items 1-20

Reconciling the last old-language / old-path contradictions so "How Jakenew Works" is canonical. New
code is tested (39/39 files) + an end-to-end poll smoke; the rest is language reconciliation.

**Code changes this pass:**
- **Item 3 — two activation routes.** Besides the relative-attention route (`share ≥ WAVE_ACTIVE_SHARE`)
  there is now an **exceptional-absolute route** (`ABSOLUTE_ROUTE_ENABLED`): a genuine campaign whose
  Mag-7 pool share is *diluted* by other simultaneous excellent campaigns can still activate on
  absolute abnormality (`WAVE_ABSOLUTE_Z`) + control + information concentration
  (`WAVE_ABSOLUTE_INFO_SHARE`). Removes the residual share-tournament math. (`waves.py`)
- **Item 5 — premium acceptance > required appreciation.** Exceptional flow being **ABSORBED** without
  contract-price deterioration is now entry-eligible even if premium isn't yet rising
  (`ACCEPT_ABSORPTION_ENABLED`). Accumulation no longer requires price to have already moved.
- **Item 8 — one ValueState owner.** `value_memory.assess` now returns `CHEAP / FAIR / EXTENDED /
  MATURE` from robust value percentiles; the session low is merely one input, no longer authoritative.
- **Item 17 — event-level provenance** (`event_memory.py`): each significant contract event is stored
  **immutably** (event_id, ts, size, price, spot, moneyness, IV, shape, direction/inventory hypotheses)
  so future logic can recognize **multiple latent campaigns superposed on one contract** instead of
  collapsing everything into one inventory story. Cross-session; pruned by expiry.
- **Item 7 — terminology:** the score is a **heuristic posterior proxy / continuation-evidence
  score**, not a calibrated Bayesian probability (fixed in the verdict section + philosophy).

**Verified already-correct / already-enforced (locked with tests):**
- **Item 14** — the daily one-ENTER-per-side lock is authoritative: a consumed slot is suppressed at
  the poll level *before* the refractory can propose a re-entry (`test_regression`).
- **Items 1-2, 13** — multi-campaign, qualified control, and reversal-owns-exits landed on 8/16.
- **Item 4** — ContractValueMemory now *owns* value (ValueState), not just overriding the session-low.
- **Item 18** — the doc's top banner + entry conditions + knobs now state one current runtime per module.

**Language reconciled (no code change needed — behavior already correct):**
- **Item 1** Layer-1 discovery consumes PremiumMass **and** InformationMass (`discovery_share`).
- **Item 2** Layer-2 is **qualified** control (raw call/put share is observation only).
- **Item 4/6** the campaign verdict no longer lists rank-1 / raw ≥66% / session-low / compact-only.
- **Item 9** exceptional FORMING events are not spot-gated (volume senior).
- **Item 10** contract selection is event-information inside `EVENT_SELECT_WINDOW` (no hard ATM±1).
- **Item 11** ExpirySelector is **shadow** — a *known active limitation*: campaign direction can be
  right while the traded nearest expiry is suboptimal. Not "solved" until it owns execution.
- **Item 12** attention transfer → PRIORITY_INVESTIGATE, never mandatory capital rotation.
- **Item 15/16** InformationMass parallel to premium mass; inventory stays probabilistic (a later
  participant may accumulate while an earlier one exits — never treated as one identifiable owner).
- **Item 18** cross-strike confirmation measures temporal/economic coherence (`cluster_shock`), not
  identical morphology. **Item 19** opening gets opening-specific normalization, not a blanket penalty.

**Still genuinely open (honest):** ExpirySelector owning execution (item 11) is the largest live
limitation; time-of-day BarVolumeShock (item 7 of the 8/16 pass) awaits multi-session history; and
inventory reconstruction under multiple superposed participants (items 16-17) is the next research
problem — event provenance is now stored to make it *possible*, not yet *solved*.

### Second integration audit (2026-08-16) — ownership & single-owner decisions

Focus: not features but **ownership** — proving which behavior owns each decision, killing stale
legacy paths, and making every rejection answerable from the ledger. Code tested (40/40 files) + smoke.

**Code changes:**
- **Item 1 — one runtime-authority table.** `config.runtime_authority()` returns
  `feature / code_default / env_value / effective / decision_owner` for every behaviour flag, logged at
  startup as `RUNTIME-AUTHORITY …`. This is the single source of truth — "default OFF" prose is noise
  once running. (The knob tables above still show *code defaults*; the effective values are here.)
- **Item 2 — strict reversal ownership.** CampaignConfidence answers "is MY thesis alive?"; only
  ReversalCluster may authorize an **opposite-side** exit. A confidence collapse whose dominant cause is
  CONTROL/OPP is now **suppressed** when `REVERSAL_ENABLED` — closing the GOOGL/NVDA backdoor where weak
  opposite flow indirectly exits. (Tested both ways: suppressed on; exits with reversal off.)
- **Item 5 — one value owner.** ContractValueMemory's **ValueState (CHEAP/FAIR/EXTENDED/MATURE)** now
  *owns* the value gate: EXTENDED/MATURE rejects, CHEAP/FAIR allows, and `GATE_MAX_DIST_FROM_LOW` is a
  logged component — it governs only when there is no value history.
- **Item 6 — discovery ranks logged.** Every candidate records PremiumMassRank / InformationMassRank /
  BlendedDiscoveryRank / QualifiedControlRank in the ledger, so we can *see* whether the 0.30 info
  blend still buries a pristine cheap event (the NVDA 220P failure mode) — data before we retune.
- **Item 7 — barshock baseline quality.** `bar_shock` tags `ESTABLISHED / PARTIAL / UNSEEDED`; an
  UNSEEDED opening baseline is never treated as a statistically-confirmed shock (logged in the ledger).
- **Item 13 — honest premium decomposition.** ΔP − δΔS − ½γΔS² is the **UNEXPLAINED premium
  component** (driver `SPOT_DRIVEN` / `UNEXPLAINED_DRIVEN` / `MIXED`), not "IV" — it also holds theta,
  vega nonlinearity, quote noise and timestamp skew until real greeks + sync exist.
- **Item 14 — cross-feed skew.** The ledger stores `quote_ts` + `quote_skew_ms`; `SNAPSHOT_MAX_SKEW_MS`
  is the threshold above which economic inference should be discounted.
- **Item 20 — authoritative candidate fields.** The candidate carries one `authoritative_control`
  (already resolved to qualified control upstream) and one `value_state`; no downstream module
  recomputes a conflicting version. Same-shape single-owner discipline for control/value/exit.
- **Item 4 — legacy tournament knobs quarantined.** `WAVE_LEAD_SHARE` / `WAVE_LEAD_MARGIN` are marked
  **LEGACY / bypassed under `ENTRY_ROUTES`** in config — they cannot silently re-enter eligibility.

**Verified / documented (behavior already correct):**
- **Item 3** trade-lock ≠ observation-lock: a consumed daily side-slot blocks *execution* only;
  detection, classification, event-memory and the ledger keep recording second same-side waves.
- **Item 9** EOD flatten ⇒ POSITION=FLAT; only **informational campaign memory** survives overnight
  (never an open position). **Item 16** inventory stays multi-participant/probabilistic; **item 15**
  multiple price anchors (first-abnormal/onset/basis/entry/reinforcement/peak) partly captured today.

**Deferred to the frozen-architecture research phase (as the audit recommends):** temporal
package/roll graphs (items 10-11 — `PKG_WINDOW_S` is the forward hook; today's resolver uses the
30-180s windowed surface); T+1 OI as a *learning label* (item 10 of the list); corporate-action
contract-identity checks (item 13 of the list, matters beyond Mag-7); and the backtestable-vs-live-tape
validation split (items 18-19). The next cycle is **collecting Decision-Ledger data, not new indicators.**

### Entry-bottleneck observability (2026-08-20) — visibility without loosening execution

Three sessions (08/17–08/19) produced 0 entries. The audit found the choke point is the *route stage*,
not discovery — and that `asym=0.00` was a **sentinel for a hard veto**, not a weak score (it conflated
"terrible" with "not computed"). Fixes — **execution boundary unchanged** (`ENTRY_ROUTE_MIN_SCORE`
stays 0.55):

- **Item 1 — kill the 0.00 ambiguity.** `entry.decide()` now always computes the **raw** route score
  (even under a veto) and reports `score_status` (`SCORED` / `HARD_VETO`), `score` = null under a veto
  (never 0.00), `raw_score` = what it would have scored, and `hard_vetoes[]` = **every** veto family
  that applied (`DISTRIBUTION` / `EXIT_SHAPE` / `PREMIUM_REJECTION` / `OBJECTIVELY_LATE` / …). All in
  the ledger.
- **Item 2 — 🟡 near-miss WATCH tier (RESEARCH ONLY, never an order).** A genuinely-scored candidate
  in `[NEAR_MISS_MIN_SCORE 0.45, 0.55)` with no hard veto, qualified control, low distribution, a
  non-EXTENDED/MATURE ValueState, and an approved route posts a Discord amber card ("RESEARCH ONLY —
  no order") with score/shortfall/top-drag/value/control. Throttled per (ticker,side). Restores
  visibility and collects live evidence on whether 0.50–0.54 events convert. **Discord cards OFF since
  2026-10-25** (`NEAR_MISS_ALERT_ENABLED=false`); the near-miss funnel counts still land in the EOD
  ATTRITION-REPORT log.
- **Items 3/6 — EOD attrition report.** `ATTRITION-REPORT` logs the entry funnel (Discord EOD cards — campaign-flow + legacy — OFF since 2026-10-25, `EOD_DISCORD_ENABLED=false`; the `CF-EOD` lines stay in the log)
  **ACTIVE_EVENT(evaluated) → QUALIFIED_CAMPAIGN(no-veto) → ENTRY_READY → ENTERED**, plus hard-veto
  counts by family and near-miss counts by route — so we see exactly where candidates are lost.

**Deliberately NOT changed (per the brief):** the execution threshold (item 9), and the route-score
*math* — the audit's point that a route named `CROSS_STRIKE` doesn't actually *score* cross-strike
synchronization (routes share the same 7 ingredients — rank/notional/control/response/abn/persist/cheap
— with only different weights) is **documented as a real gap** but not rewired, because that would
change execution. That, plus the **forward-outcome replay** (score-bucket MFE/MAE by archetype + the
hard-veto false-positive study) is the evidence-based next phase — the near-miss stream + attrition
report are the instruments that make it possible.

### Missed-winner audit — TSLA 350C 08/21 + the "ENTRY_READY 7 → ENTERED 0" bug (2026-08-22)

Two distinct causes found from the 08/21 logs + candidate archive (no hindsight — traced chronologically):

**Cause 1 — the 7-ENTRY_READY-0-ENTERED contradiction: `HYPOTHESIS_AMBIGUITY_PASS`.** 8 of 9
post-route abstains were hypotheses-ambiguous (65 across the day). The 8-way hypotheses distribution's
top probability rarely clears `HYP_DOMINANT_MIN=0.35` (observed tops: 0.17–0.27, even when
`FRESH_DIRECTIONAL` was correctly the top), so this **hard** PASS gate abstained on ~every route-passer.
It was only ON because of the blanket "all flags on"; its design default is OFF ("observe first").
**Fix (2026-08-22, two stages):** first reverted `HYP_PASS_ENABLED` to OFF to unblock trading; then
**re-enabled it with a recalibrated ambiguity rule.** The absolute top-prob bar (`HYP_DOMINANT_MIN
0.35`) is unreachable in an 8-way distribution, so it abstained on ~everything. The gate now abstains
only when a **NON-directional** hypothesis (roll / spread-leg / hedge / closing) *leads*
fresh-directional by `HYP_ABSTAIN_MARGIN` (0.05), or when `UNKNOWN` dominates — a `FRESH_DIRECTIONAL`
lead (even at a modest 8-way prob) is **not** ambiguous for a directional entry. Verified on the 08/21
cases: the AMZN-PUT `FRESH_DIRECTIONAL` reads now enter; the AAPL/NVDA `SPREAD_LEG` reads still abstain
(correctly). `abstain_cause` names the leading non-directional family in the ledger. (No threshold
changed.) Also fixed the **funnel semantics**: `ROUTE_PASSED` (score ≥ 0.55) is now distinct from
entry-eligible — the attrition report shows `ACTIVE_EVENT → QUALIFIED_CAMPAIGN → ROUTE_PASSED →
ENTERED` plus a **POST-ROUTE veto breakdown** so "route passed but didn't enter" is always attributed.

**Cause 2 — TSLA was found early & cheap, then killed by `EXIT_SHAPE`.** At **08:32 the TSLA 347.5C was
$3.10, z=8.0, route raw_score 0.71** (well above 0.55) — but `HARD_VETO=EXIT_SHAPE` every poll. The
shape/acceptance classifier tagged the violent opening pullback ($3.10→$2.28 in the first minutes) as
`EXHAUSTION_OR_EXIT_FLOW` / `HEAVY_VOLUME_NEGATIVE_RESPONSE` — i.e. it **misread a shakeout as
rejection/exit** on a high-gamma opening move. Later polls added `OBJECTIVELY_LATE` (the confirmation-
lag Catch-22). So a pristine early convexity event (identified at ~$2.3–3.1, ran to $13+) never reached
the route funnel.

**FIXED (2026-08-22): EXIT_SHAPE now distinguishes shakeout from rejection** (`entry._is_shakeout_not_
rejection`, `EXIT_SHAPE_SHAKEOUT_EXEMPT`). Only the two *ambiguous* dip shapes (`EXHAUSTION_OR_EXIT_
FLOW`, `HEAVY_VOLUME_NEGATIVE_RESPONSE`) can be exempted, and only with a real dip-then-recover
signature (`shakeout ≥ EXIT_SHAKEOUT_MIN`) **plus** campaign vitality (prior favorable excursion
`mfe > EXIT_SHAKEOUT_MIN_MFE` or still self-sustaining), or when the archetype engine already called it
`SHAKEOUT_AND_RECOVERY`. Premium that is merely being destroyed (no recovery, no prior excursion — the
GOOGL 362.5C case the veto was built for) still hard-vetoes, and genuine distribution shapes
(`DISTRIBUTION_AT_PREMIUM_HIGH`, stale/mature/lone-print) are **not** shakeout-eligible and always
veto. The same discriminator also suppresses a `PREMIUM_REJECTION` veto for a genuine shakeout (a
transient lower-low is not a thesis rejection). Tests in `test_entry.py`. **TSLA 350C 08/21/2026 is in
the permanent regression set** (opening concentrated volume → premium acceptance → self-sustaining
convexity, recognized while cheap). **FIXED (2026-08-22): OBJECTIVELY_LATE now means "we identified it late", not "the price is high
now."** The veto keys off **premium drift since first identification** (`rel_premium` = current mark ÷
premium at first capture): a small drift (≤ `LATE_MAX_DRIFT`, default 2×) means we found it while cheap
and any later extension is our own confirmation latency — not a chase — so it is **not** late. Robust
`ValueState` is authoritative when known: `MATURE` (top of the contract's own history) → late even if
it hasn't moved since; `CHEAP/FAIR` → never late (rescues a corruptible session-low). Only when there's
no capture reference and value isn't cheap does it fall back to the raw session-low extension
(`ENTRY_HARD_EXTENSION`). So the TSLA window (identified ~$3, drift ≤2× up to ~$6) is now tradeable,
while a genuine 3×+ post-identification run still vetoes. Flag `LATE_BY_DRIFT_ENABLED` (default on);
tests in `test_entry.py`.

**FIXED (2026-08-22): shape-classifier noise + entry re-arm (the TSLA residual).** A replay showed
TSLA still wouldn't enter because its high-gamma opening flips the SHAPE poll-to-poll (`PERSISTENT_
COMPACT_WAVE ↔ EXHAUSTION/MATURE/ISOLATED`), so the ACTIVE/entry polls landed on exit-shape reads, and
by the time the shape settled clean the wave had cooled out of ACTIVE. Two fixes: **(1) rolling-shape**
(`ROLLING_SHAPE_ENABLED`) — `EXIT_SHAPE` hard-vetoes only when the exit shape is *persistent* across
the recent window (`recent_exit_frac ≥ EXIT_PERSIST_FRAC`), not on a single-poll flip inside an
accumulating window (too little history → veto stands); **(2) entry re-arm**
(`ENTRY_REARM_ENABLED`, `waves._can_enter_state`) — a wave that cooled ACTIVE→STABILIZING without ever
entering keeps its one entry chance (all §16/route gates still apply, so it widens *when* we may try,
not *what* qualifies). Regression `test_regression.py` replays the TSLA 350C 08/21 sequence.

**FIXED (2026-08-23): EntryWindow — separate campaign lifecycle from entry eligibility.** The deepest
TSLA cause: entry required the *accidental coincidence* of `wave_state==ACTIVE` **and** a clean
instantaneous shape on the **same** poll — but its opening flips shape poll-to-poll and cools ACTIVE→
MATURE within a minute, so the two never aligned during the cheap $2–3 window. Now a **persistent
EntryWindow** (`Wave.ew_open`, `waves._can_enter_state`, `ENTRY_WINDOW_ENABLED`) opens when a campaign
first becomes entry-relevant (FORMING birth) and stays open across **ACTIVE→MATURE→STABILIZING→
DECAYING** until the trade fires, the wave ends, the window ages out (`ENTRY_WINDOW_MAX_MIN`), or a
genuine economic invalidator rejects it. The per-poll value/late/shape/EV gates in `_open_wave` remain
the "still actionable?" test — so this widens *when* we may try, not *what* qualifies. Campaign lifecycle
state (MATURE) no longer implies premium maturity (value/late own that). Also **ISOLATED_PRINT is no
longer an exit shape** — it's a valid standalone archetype (DOMINANT_STANDALONE); a late lone print is
caught by OBJECTIVELY_LATE, not the shape label. The ledger now logs `entry_window` / `_age_s` /
`campaign_state` per candidate. Tests: `test_waves.py` (EntryWindow eligibility), `test_entry.py`
(ISOLATED_PRINT freed), `test_regression.py` (TSLA).

### Exit-regression fixes (2026-08-24) — Monday's first entries died in 3–5 min

Monday 08/24 was the first session on the full stack and it *entered* (NVDA 210C, MSFT 490P) — progress
from the zero streak — but both died fast: **NVDA at 3.5 min (`PREMIUM_STRUCTURE_FAILURE`)** and **MSFT
at 5 min (`ROTATION_WITH_CURRENT_CAMPAIGN_FAILURE`)**, both via CampaignConfidence. Two targeted fixes:

- **Rotation is discovery-only, never an exit** (`ROTATION_EXIT_DISABLED`). Another Mag-7 ticker
  becoming the attention leader no longer erodes an existing campaign's confidence — the invariant
  *"AttentionShift ≠ CampaignEnded."* (MSFT 490P was flattened purely because NVDA took the board.)
- **Floor-break persistence** (`CONF_EXIT_PERSIST_EVALS=3`). A confidence dip below the exit threshold
  must persist for 3 consecutive polls before it flattens the campaign — one liquidity-sweep / one
  higher-low failure near the open is not floor-break (NVDA 210C died on one-poll premium noise). A
  recovering poll resets the counter. Combined with the drop-cap, a thesis exit now needs sustained
  deterioration, not a 3-minute wobble. Hard stop / EOD / qualified reversal still act immediately.

**Reporting fixes:** near-miss WATCH cards now **dedup** — one card per campaign, re-alerting only on a
material score gain (`NEAR_MISS_REALERT_DELTA`), not a fresh card every 10 min for the same candidate;
and route scores display **3 decimals** (0.548, not a contradictory "0.55/0.55").

**Deferred to the next research phase (NOT done — honest scope):** the larger campaign-concurrency and
information-quality work the 08/24 review called for is multi-session and not attempted here:
cross-strike **campaign aggregation** (recognize one TSLA-put campaign across 345–362.5P and pick one
expression, instead of per-strike evaluation); the **InformationMass** formula (√premium × abnormality
× concentration × price-response × acceptance × coherence × freshness) so distributed theta-decay call
volume contributes ~0 to qualified control; **value-floor / EventCostZone** tracking for floor-break;
a labeled **morphology library** (DOMINANT_STANDALONE / CROSS_STRIKE_CLUSTER / VALUE_ACCEPTANCE vs
PERSISTENT_DISTRIBUTED / ZERO_VALUE_CHURN); **WEAK_LEAN vs CONTROL** classification (NVDA 0.55 control
is a lean, not control); and post-entry **CampaignShape** persistence separate from position mgmt.
Four named regression cases are recorded for that phase: **NVDA 210C** (weak 0.55 control → should be
LEAN), **MSFT 490P** (no rotation-only exit — it later hit +63%), **NVDA 212.5P** (73% put attention
that produced no alert — silent-suppression bug), **TSLA put surface** (multi-strike bearish campaign),
plus the TSLA-call negative control (distributed decay must rank below the clean put fingerprints).

### Strategy handoff (2026-08-30) — Priority 1 done; the rest scoped

A full strategy-redesign handoff (5 case studies, a 17-state campaign machine, whole-surface package/
greeks ranking, premium-value engine, flip workflows, intraday/overnight theses, replay acceptance
tests). Much of it already exists: reversal cluster, EntryWindow, ValueState, InformationMass, package
resolver, overnight_carry, remaining_convexity, morphology archetypes, decision ledger. The one clear
GAP — and the through-line of every case study — was implemented:

**Priority 1 — the ABSOLUTE ENTRY GATE** (`absolute_gate.py`, `ABS_GATE_ENABLED`). Rank tells the
engine WHERE to look; it must NOT authorize a trade. Entry now requires, rank-independently,
`attention_score ≥ ABS_MIN_SCORE (50)` AND directional `dominance ≥ ABS_MIN_DOMINANCE (0.60)` — a
0.54–0.60 read is a **WEAK_LEAN**, not control. A failing signal is a **WATCH**, not an entry
(`MISSED_DUE_TO_WEAK_ABSOLUTE_SIGNAL`). Calibrated to the case studies: passes the winners (NVDA
94/0.73, TSLA 75) and blocks all three losers (META 42, MSFT 47/0.54, AAPL 49/0.57). Uses QUALIFIED
dominance. Tests: `test_absolute_gate.py`.

### Strategy handoff — P2 / P4 / P5 / P6 built (2026-08-30, ON for paper)

Following the absolute gate, the next four priorities were implemented and enabled. All flag-gated (ON),
each with standalone tests; suite 45/45.

**P2 — remaining-convexity contract ranking** (`convexity.py`, `CONVEXITY_SELECT_ENABLED`). The engine
kept buying the most VISIBLE strike (META 565C) while a nearby strike (570C/580C) offered far more
**convexity per premium dollar** after resetting. Direction can be right while the expression is
expensive. `contract_select` now scans the wider near-ATM surface (**ATM ± `CONVEXITY_WINDOW` = 5**) and
adds a convexity term to the event-select score (`ES_W_CONVEXITY = 0.45`, score normalized to [0,1]):
`convexity_score = 0.5·gamma-per-premium + 0.3·room-from-low + 0.2·moneyness-relevance`. Gamma-based
(OPRA has no vega/theta — a documented follow-up); the moneyness term keeps a far-OTM lottery strike from
winning. Tests: `test_convexity.py`.

**P4 — re-entry after a COOLING exit** (`reentry.py`, `REENTRY_ENABLED`). The daily one-ENTER-per-side
lock must not permanently forbid a legitimate return: a campaign that **took profit / trailed off** (a
COOLING exit — category in `REENTRY_ELIGIBLE_CATEGORIES = {OBJECTIVE}`) can reaccelerate the SAME side
later. Resolution of the daily-lock conflict: allow a re-entry **only after a cooling exit AND on
confirmed reacceleration** — fresh abnormality + same-side control re-seized (`≥ REENTRY_MIN_CONTROL
0.60`) + positive premium acceleration + value not extended/matured + spot confirming — capped at
`REENTRY_MAX_PER_SLOT = 1` per side per session (the count is persistent across the intervening cooling
exit). **Terminal exits (REVERSAL / RISK_STOP / DISTRIBUTION / CONTROL_TRANSFER / THESIS_DEATH) are never
re-eligible** — re-buying a failed thesis is the exact mistake this guards against. Until reacceleration
confirms, a cooled slot sits in **REACCELERATION_WATCH** (logged, not traded). Tests: `test_reentry.py`.

**P5 — opposite-side flip workflow** (`reversal.flip_plan`, `FLIP_WORKFLOW_ENABLED`). When the P3
ReversalCluster reaches REVERSAL_ACTIVATED and the outcome is `EXIT_REVERSE`, leaving the incumbent is
only half the flip. The opposite side is now **FLIP_PENDING**: it must be entered as a FRESH campaign that
recomputes its own ATM/best-convexity contract (contract_select does this each poll) and passes **every
normal activation gate** (absolute + route + spot) before it opens — the flip is never automatic off the
incumbent's exit. `EXIT_REVERSE` deliberately does NOT lock the opposite slot, so the normal gated entry
path owns the opposite entry; a 🔄 Discord flip card (`FLIP_ANNOUNCE`) makes the hand-off visible. Tests:
`test_flip.py`.

**P6 — intraday vs overnight thesis** (`session_thesis.py`, `SESSION_THESIS_ENABLED`). A 0/1-DTE campaign
carries an implicit horizon. At EOD each held short-DTE campaign is classified **INTRADAY** (spent at the
bell — default) vs **OVERNIGHT** (carry the campaign MEMORY forward). OVERNIGHT requires independent
late-day confirmation: same-side control held into the close (`≥ OVERNIGHT_MIN_CONTROL 0.60`), no
distribution (`≤ OVERNIGHT_MAX_DIST_PROB 0.35`), value retained, spot confirming. We classify the
THESIS, not the position (paper flattens either way); the label is stamped on the serialized campaign and
`carry_forward` drops any campaign judged INTRADAY (`session_carry = False`). Tests: `test_session_thesis.py`.

**Still deliberately NOT built (honest — remaining):**
- **P2 full surface economics** — synthetic-NBBO verticals and **vega/theta**-per-premium ranking across
  neighboring expiries (OPRA gives only delta/gamma/IV, so convexity is gamma-based today).
- **P3 premium-percentile engine** — the full intraday/historical premium-percentile-by-DTE value model
  (ValueState + late-by-drift + EV convexity are present).
- **P1 activation half** — "require spot reclaim/break + premium higher-low; first countertrend flow →
  COUNTERTREND_WATCH" is only partially present (FORMING spot-confirm + the reaccel gate reuse).
- **P7 replay acceptance tests** — TSLA/META/MSFT/NVDA/AAPL as causal no-lookahead tests: not yet.

The engine's strength remains discovery; the absolute gate (P1) attacks its core weakness (converting
weak information into an expensive purchase), P2 fixes the *expression*, P4 stops it abandoning a campaign
that legitimately reaccelerates, P5 makes reversals into disciplined re-activations, and P6 stops an
intraday thesis leaking into next-open memory. Recommend a replay after live sessions accumulate.

### Phase-upgrade validation (2026-08-02, 4-week backtest 06/29–07/24)

Real 1-min bars, SHADOW fills — a directional check, not live P&L.

| Config (4 weeks) | Entries/day | Win% | Avg/trade | Worst | Profitable wks |
|---|--:|--:|--:|--:|--:|
| **All flags ON** (all gates + P1/P4/P5/P7) | 1.1 | 32% | +0.7% | −32% | 2/4 |
| P1 + safe flags only (entry gates OFF) | 1.1 | 43% | +0.4% | −43% | 2/4 |

**Neither config is a proven edge** — both ~breakeven, 2/4 weeks, with −30–40% tail weeks. The two
are essentially a **wash**: the full gate stack trades some of the tuned week's upside (P1-alone hit
win 55%/+10% on 07/20–24) for a smaller worst-case tail (−32% vs −43%) via the distribution veto.
P1 (the premature-exit fix) is the one change with a clear in-sample win (07/20–24: win 36%→55%,
+5%→+10% vs baseline). **Calibration (P8)** over a backtest archive (14 matched pairs) gave Brier
0.40 / ECE 0.37 / non-monotonic deciles → the posterior/continuation **proxy is NOT yet calibrated**
(confirms the "uncalibrated proxy" terminology; the 0.55 threshold is not a true probability yet).
The P6 archive → P8 calibration loop is proven end-to-end.

**LIVE POSTURE 2026-08-03 (paper):** per request, **all behaviour-changing flags are ON** for a
paper forward-test (STABILIZE, EARLY_DETECT, ARCHETYPE_GATE, SURFACE_GATE, RUNNER, all prior gates
re-enabled, RESEARCH_ARCHIVE on; MULTI_EXPIRY kept OFF live — pure-shadow, adds API load for no
trade benefit). This is **not** a claim the edge is proven — it is a data-gathering forward-test on
simulated money; a −40% stop day is plausible. `RESEARCH_ARCHIVE_ENABLED` means tomorrow's real
fills feed the P8 calibration harness. Roll back any flag in `.env` after reviewing the logs.

**Follow-up P1 — campaign-based exits (`analysis/hold.py`).** Live sessions kept showing the same
management flaw the spec calls out: healthy positions exited on *cooling* (TSLA +3% ROTATION, GOOGL
4-min STATISTICAL_EXHAUSTION). This separates **holding** from **entering**. With
`CAMPAIGN_CONFIDENCE_ENABLED=true`, each held wave carries a stateful **CampaignConfidence** (starts
`CONF_INIT`=0.75): **rotation is a penalty, not a command** (§4/§6); verified deterioration (lost
control, opposite-side strengthening, distribution, premium-not-progressing, higher-low failure) also
subtracts; **reacceleration / an ACTIVE revival adds** — so a still-ACTIVE incumbent *resists* being
rotated out, while genuine multi-signal decay erodes confidence below `HOLD_EXIT_THRESHOLD`=0.40 and
exits with a **§20 label** (`VERIFIED_DISTRIBUTION`, `PERSISTENT_CONTROL_TRANSFER`,
`ROTATION_WITH_CURRENT_CAMPAIGN_FAILURE`, `PREMIUM_STRUCTURE_FAILURE`, `RESILIENCE_FAILURE`,
`TRUE_MULTI_VARIABLE_EXHAUSTION`). Adds **FUNDED / SELF_SUSTAINING / REACCELERATING** lifecycle labels
(§7) and premium-structure metrics — **PremiumPersistence / PremiumSmoothness / HigherLowQuality**
(§15-16) — that recognise an orderly persistent build (AAPL) rather than only a violent shock. It
supersedes the STABILIZE exit path when on. Tests: `test_hold.py` (13 checks). *Default OFF — pending
backtest.* Remaining follow-up items (gate-stack refactor, local-value cheapness + latency diagnosis,
persistent-accumulation entry scoring + opening rework, named campaign replays) are tracked separately.

**Follow-up §10-19 — the rest of the v2 spec (all flag-gated / research; default OFF unless noted).**
- **§19/§20 labels** — entries now return a specific rejection label (`MISSED_DUE_TO_DETECTION_LATENCY`,
  `_SINGLE_STRIKE_NOTIONAL`, `_CLUSTER_AGGREGATION`, `_EV_GATE`, `ECONOMICALLY_VALID_REJECTION`, …)
  archived per candidate; `campaign.reject_is_model_miss` separates a false-negative worth researching
  from a disciplined reject. Exits use the §20 campaign labels.
- **§10 archetype entry routes (`analysis/entry.py`, `ENTRY_ROUTES_ENABLED`)** — replaces the brittle
  conjunctive gate stack with **hard vetoes + archetype-specific routes + a total expected-asymmetry
  score**, so strong evidence in one dimension (e.g. a broad AMZN ladder's cluster notional, or an
  AAPL build's persistence) can offset a weak reading in another. Fixes the "demands early pricing
  AND late confirmation" contradiction.
- **§11/§12 (`analysis/value.py`)** — CHASED is now split into `MISSED_DUE_TO_DETECTION_LATENCY`
  (cheap when found, ran before we acted) vs `MISSED_DUE_TO_PRICE_EXTENSION` (valid); notional
  shortfalls split single-strike vs cluster-aggregation; local-value cheapness + latency metrics.
- **§15-17 (`archetype.quality_score`)** — an archetype-aware CampaignQualityScore (persistence-
  weighted for persistent builds, acceleration-weighted for shocks, expiry for forward, post-volume
  for self-sustaining), computed + logged. Premium persistence/smoothness/higher-low live in
  `hold.py`. **§13 (`OPENING_QUALITY_ENABLED`)** waives the blanket 1.4× opening penalty for a clean
  opening campaign.
- **§18 campaign replay (`replay_campaign.py`)** — poll-by-poll reconstruction of any contract from
  real bars. Ran the four named misses: **NVDA 200C +720%, TSLA 315C +417%, MSFT 490C +163%, AAPL
  305C +131%** — each had a long *cheap window* before the move, confirming the misses were detection
  latency, not invalid setups. Tests: `test_entry.py`, `test_value.py`, +hold/archetype checks.
  **17 test files green.**

**New-spec — "campaign detector, not an intraday bot" (MSFT/GOOGL/AMZN lessons).** The exit half of
this spec (rotation ≠ invalidation, campaign persistence, P&L ≠ campaign state, reinforcement-not-
re-entry) was already delivered by FU-P1 (CampaignConfidence). The new entry/alerting pieces:
- **Daily one-ENTER-per-side lock (`DAILY_ENTRY_LOCK_ENABLED`, default OFF).** Max one CALL + one PUT
  entry per ticker per session; a fired entry consumes that slot for the whole day — **no re-entry
  that side/ticker even after an exit/invalidation** (kills the ENTER→EXIT→ENTER churn). "The scanner
  gets unlimited observations; the trader gets extremely few decisions."
- **Premium Acceptance (`analysis/flow_response.py`, `ACCEPTANCE_ENABLED`, default ON).** High call
  volume ≠ bullish. Distinguishes **ABSORPTION** (heavy volume + premium *holding* — tradeable even
  flat) from **REJECTION** (heavy volume + premium making *lower lows* — the GOOGL 362.5C that was
  being destroyed). Wired into the entry routes: REJECTION is a hard veto; ABSORPTION lifts response
  evidence **without requiring appreciation** (so we're not late — the AMZN lesson).
- **Reinforcement lifecycle updates (`REINFORCE_LOG_ENABLED`, default ON).** Same-side flow resurging
  on a held position posts **CAMPAIGN STRENGTHENING** (a lifecycle note, throttled) instead of a new
  ENTER — the AMZN 12:04 $1.44M second wave is reinforcement, not a new trade.
- **T+1 OI review (`analysis/oi_confirm.py`, `OI_CONFIRM_ENABLED`, default OFF).** Stores each
  campaign's fingerprint and a next-day reconciliation — how much of the session's volume *can* have
  become net new open interest. Needs Schwab OI (currently off). Tests: `test_newspec.py`.
  *(2026-10-17 revision `oi-recon-v1`: see "OI reconciliation & Discord outbox" below — the old
  NEW_POSITION_CONFIRMED / PARTIALLY_CONFIRMED / LIKELY_CLOSING_CHURN labels are retired.)*

**New-spec §1-37 — "institutional campaign detector" priority build (NVDA/AAPL churn lessons).**
Built in priority order, each a pure module + config + test, **all flag-gated OFF** (live posture
unchanged):
- **P1 — cross-session campaign memory (`analysis/campaign_store.py`, `CROSS_SESSION_MEMORY_ENABLED`,
  default OFF).** A campaign that is still valid at EOD (multi-day expiry, side still in control) is
  serialized to the state file and **restored at startup**, so a real institutional position survives
  a restart or an overnight gap instead of being re-discovered cold. `carry_forward` on a new day,
  overnight classification + hysteresis, terminal on any non-EOD exit. Tests: `test_campaign_store.py`.
- **P2 — per-strike BarVolumeShock (`analysis/barshock.py`, `BARSHOCK_ENABLED`, default OFF).** Total
  volume is not information. Each contract's current 1-min volume is scored against its **own robust
  baseline (median + MAD)** so a persistently-busy strike adapts into its background while a normally-
  quiet strike that suddenly prints becomes highly informative; a tiny-baseline safeguard (#6) requires
  an absolute contracts + notional floor before a shock is `significant`. Cross-strike `relative_shock`,
  `cluster_shock`, and `classify_event` (CONCENTRATED vs COORDINATED_MULTI_STRIKE). Event-time
  moneyness (#8) is stored, never recomputed from a later spot. A **hard entry-gate**
  (`barshock.entry_gate`, `BARSHOCK_GATE_ENABLED`, default OFF) can veto any entry whose traded side
  shows no genuine abnormal event — `NO_ABNORMAL_EVENT` (shock below the robust-Z threshold, i.e.
  background flow) or `SUBTHRESHOLD_EVENT` (clears Z but fails the absolute contracts/$ floor, i.e. a
  tiny-baseline ratio spike). It applies in BOTH route and conjunctive modes and degrades to ALLOW
  when no barshock read exists (so a not-yet-formed opening baseline never starves entries).
  Tests: `test_barshock.py`.
- **P3 — cross-strike ReversalCluster + EXIT≠REVERSE (`analysis/reversal.py`, `REVERSAL_ENABLED`,
  default OFF).** Opposite-side flow is a *state machine* — OPPOSITE_FLOW_DETECTED → REVERSAL_WATCH →
  REVERSAL_CLUSTER_CONFIRMED → REVERSAL_ACTIVATED — not an instant flip. `outcome()` separates the two
  decisions the old engine conflated: **HOLD / EXIT_FLAT / EXIT_REVERSE** (exiting your side ≠
  entering the other). When enabled, `_manage_reversal` owns opposite-side exits and CampaignConfidence's
  `opp_strong` shortcut is gated off. Tests: `test_reversal.py`.
- **P4 — event-information contract selection (`analysis/contract_select.py`, `EVENT_SELECT_ENABLED`,
  default OFF).** The representative contract is chosen by event **information** — BarVolumeShock
  significance + ATM relevance + executability (spread/liquidity) + value (room from low) over the
  ATM±`EVENT_SELECT_WINDOW` strikes — not by raw mass. This is how the engine picks the NVDA 222.5P
  carrying the event over the noisier, higher-volume 220P. Consumes the P2 per-strike shocks (computed
  once in the engine and shared with the barshock log). Falls back to the mass-based `events.select_contract`
  when it finds nothing quotable. Tests: `test_contract_select.py`.
- **P5 — TSLA control/detection replay (`replay_session.py`).** A read-only, campaign-level replay
  (no orders, no state) that reconstructs a whole (ticker, side) campaign poll-by-poll through the
  **real** analysis modules — `attention.attention_board` (Layer 1 MAG7 pool), P2 `barshock`, P4
  `contract_select`, P3 `reversal`, and the `hold` CampaignConfidence engine — and answers the
  spec's post-mortem questions: raw/fresh CALL+PUT premium, control, attention score/rank/pool
  share, incumbent campaign state + confidence, opposite-side cross-strike reversal state, premium
  acceptance, the selected contract, the exact exit condition and **which module owned it**, and
  whether another module simultaneously read the campaign as *strengthening* (the "EXIT while
  STRENGTHENING" contradiction). It quantifies forfeited convexity as **MFE/MAE measured from ENTRY
  and from EXIT**. Bid/ask/size are synthesized from the bar (as the backtest does); all
  volume/premium/price data is real Alpaca 1-min. First run — TSLA 2026-08-04 CALL — reproduced the
  pattern: entry 09:35 ET, exit 9 min later at -28% (`HOLD_CONFIDENCE` / `PREMIUM_STRUCTURE_FAILURE`),
  the contract then ran **+75% from the exit price** — the early exit forfeited that convexity.
  **22 test files green** (P5 is a network diagnostic, like `replay_campaign.py`, so it carries no
  unit test — its inputs are the already-tested pure modules).

---

## Honest status — running ACTIVE on paper, edge NOT yet proven

The engine is running **ACTIVE on the Alpaca PAPER account** (simulated money) as a forward-test
with real fills. That is a *learning* step, **not** a statement that the edge is proven — because
the multi-week backtest says it isn't:

**4-week validation** (real 1-min option bars, 06/29–07/24), most recent week is the one thresholds
were tuned on, the earlier three are out-of-sample:

| Config | Entries/day | Profitable weeks | Overall avg/trade |
|---|--:|--:|--:|
| precision pass | 1.4 | **2 / 4** | +4% |
| + campaign gate | 1.2 | **1 / 4** | −1.4% |

Two out-of-sample weeks lost ~15–19%; the tuned week looks best (an overfitting signature). The
campaign gate improved *precision* (fewer entries) but **hurt profit** — it cut winners as well as
losers. So: frequency and discipline are good; a **robust, repeatable edge is not established.**

**Event-shape-through-time layer (2026-07-29):** the DTE-sensitive timing, distribution-probability
veto, expected-value gate, stricter FORMING entry and WATCH/REDUCE were added on top. First check on
the (in-sample) 2026-07-20..24 week: **2.6 entries/day, win 31%, avg +4%, worst −15%** — it cut the
worst-case tail (−24% → −15%) but *also* trimmed winners (win 44% → 31%, avg +12% → +4%) on that
tuned week. The new probabilistic gates default to lenient/degrading values (the backtest carries
no IV and a constant delta), so this is a directional check, **not** proof; the layer still needs a
full multi-week, out-of-sample re-validation before it changes the live posture.

Why paper-active anyway: the backtest's **1-minute granularity + synthesized bid/ask** may distort
0DTE behavior enough to matter, and paper forward-testing replaces those with **real Alpaca fills,
spreads, and quotes**. It costs nothing (simulated money) and produces honest live data to judge
against. Every `config.py` threshold is still a **research parameter**, not proven truth.

**Do not move to a real-money account** until several weeks are *consistently* positive on paper.

**Deferred research (deliberately not built yet).** The research notes list heavier statistical
machinery — **Hidden Markov Models, Kalman filtering, survival/hazard functions, kernel density
estimation, online learning, fractal dimension, and historical time-of-day distribution matching.**
These are *not* implemented: they need stored, labelled training history and add real complexity,
and bolting them onto an engine whose base edge is not yet validated would add overfitting risk
without a way to measure it. The current engine approximates their intent with lighter, testable
pieces — robust Z/MAD (vs. KDE), the wave state machine (vs. a full HMM), the min-hold + refractory
(vs. hazard/survival timing), and per-ticker adaptive baselines (vs. historical matching). Revisit
once there is a stored campaign-outcome dataset to train and validate against.

**Deployment:** the process **exits after the EOD flatten**, so the daily 08:10 scheduled launch
always runs the latest on-disk code — no manual restart needed to deploy a change.

**Google Sheets trade log (`output/sheets_logger.py`, ported from Jakevolume 2026-07-31).** Jakenew
previously had **no** Sheets integration — which is why the shared "Trading Log" spreadsheet never
updated with Jakenew's trades (only Jakevolume fed it). It now logs every **ENTRY / SCALE / EXIT** to
a dedicated **`Jakenew_Trades`** tab in the *same* spreadsheet, reusing the *same* service-account
credentials, so both engines share one workbook without colliding. Writes are async + throttled +
429-retried in a daemon thread, so the ~5s loop is never blocked; a missing credential/spreadsheet
logs a warning and the engine runs on without Sheets (never fatal). Enable with `SHEETS_ENABLED=true`.

```
Layer 1  analysis/mass.py  (+ analysis/flow.py)   which ticker  (mass, Z, EWMA, ranking, Δ-adj notional, IV series)
Layer 2  analysis/control.py                       which side    (5-state control)
Layer 3  analysis/waves.py                          the wave      (birth→death, one entry, DTE-sensitive windows, FAILED_FORMATION)
Filter   analysis/response.py                       accumulation vs distribution (event shapes, response efficiency, distribution probability)
Lifecycle analysis/lifecycle.py                      self-sustainability, windowed/delayed response, shakeout, continuation prob
Verdict  analysis/campaign.py                        §14/§15 — campaign decision + posterior proxy (uncalibrated) + expected value
Engine   engine.py + execution.py                   orchestration + orders + WATCH/REDUCE
Backtest backtest.py [N weeks] [--quiet]            replay real option bars, multi-week validation
```

## Key knobs (`.env` / `config.py`, defaults shown)

| Setting | Default | Meaning |
|---|--:|---|
| `WAVE_LEAD_SHARE` | 0.42 | leader must own this share of the pool |
| `WAVE_LEAD_MARGIN` | 10 | …and lead rank-2 by this score margin, or sit out |
| `WAVE_ACTIVE_Z` / `WAVE_IMMEDIATE_Z` | 3.0 / 4.0 | abnormality to reach ACTIVE |
| `WAVE_MIN_HOLD_SECONDS` | 180 | protect a young wave from thesis-exits (unknown-DTE default; DTE-scaled otherwise) |
| `DTE_TIMING_ENABLED` | true | scale confirm/min-hold/forming-window by days-to-expiry |
| `WAVE_REFRACTORY_MIN` | 20 | bench a name this long after its wave ends |
| `GATE_MIN_SYMBOL_PREMIUM` / `_EVENT_NOTIONAL` | 100k / 55k | premium floors |
| `CHAIN_NOTIONAL_MULT` | 1.5 | chains face a higher notional floor than single strikes |
| `GATE_MAX_DIST_FROM_LOW` | 1.50 | buy only within 1.5× the contract's session low |
| `REQUIRE_ACCUMULATION` | true | reject distribution / negative-response events |
| `CAMPAIGN_ENABLED` / `CAMPAIGN_MIN_SCORE` | true / 62 | the unified campaign gate (§14/§15) |
| `CAMPAIGN_BAYES_ENABLED` / `CAMPAIGN_MIN_POSTERIOR` | true / 0.55 | Bayesian posterior gate on entry |
| `DIST_PROB_ENABLED` / `DIST_PROB_MAX_ENTRY` | true / 0.60 | distribution-probability veto on entry |
| `DIST_PROB_REDUCE` / `REDUCE_MIN_GIVEBACK` | 0.60 / 0.15 | WATCH/REDUCE trim thresholds |
| `REQUIRE_POSITIVE_EV` / `EV_MIN` | true / 0.0 | expected-value entry gate |
| `FORMING_MIN_POSTERIOR` / `FORMING_MAX_DIST_PROB` / `FORMING_MIN_EV` | 0.66 / 0.45 / 0.05 | stricter early (FORMING) entry |
| `REQUIRE_IV_CONFIRM` / `DELTA_ADJ_NOTIONAL_MIN` | false / 0 | optional IV-firmness / directional-size gates (off) |
| `TAKE_PROFIT_1/2_PCT` | +60% / +150% | scale / full profit targets |
| `TRAIL_ARM_PCT` / `TRAIL_GIVEBACK_PCT` | 0.40 / 0.35 | giveback trail: arm past +40%, exit on 35% peak giveback |
| `TRAIL_REQUIRE_TP1` | true | trail owns the position only **after** TP1 (no pre-TP1 premium stop; AMZN 08/28 fix) |
| `STOP_LOSS_PCT` | 0.40 | hard stop-loss (risk backstop) |
| `ENTRY_CUTOFF_BUFFER_MIN` | 15 | no new entries within this many min of the flatten |
| `FAST_POLL_SECONDS` | 5 | sleep between poll cycles (a cycle = parallel Mag-7 fetch + processing) |
| `ALPACA_ENABLED` / `ALPACA_PAPER` | **true** / true | **ACTIVE on paper** (real orders, simulated money) |
| `SHEETS_ENABLED` | **true** | log every entry/scale/exit to the Google Sheet (ported from Jakevolume) |
| `GOOGLE_SPREADSHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_FILE` | (shared) | same workbook + service account as Jakevolume; Jakenew writes only its `Jakenew_Trades` tab |
| `STABILIZE_ENABLED` | **false** | P1: STABILIZING state + campaign memory (cooling ≠ death) — shadow |
| `STABILIZE_MIN_CONTROL` / `_OPP_CONTROL` | 0.55 / 0.60 | side still controls / opposite side is a real threat |
| `WAVE_STABILIZE_MAX_S` | 900 | max time a wave stays STABILIZING before fade-out counts as decay |
| `ROTATION_REQUIRE_INCUMBENT_WEAK` | true | rotation exit needs the incumbent's own campaign fading too |
| `CROSS_SESSION_MEMORY_ENABLED` | **false** | new-spec P1: campaigns valid at EOD survive restart/overnight — shadow |
| `BARSHOCK_ENABLED` | **true** | new-spec P2: per-strike robust BarVolumeShock (median/MAD) — compute + log + feed P4 event-select |
| `BARSHOCK_GATE_ENABLED` | **false** | P2 hard entry-gate: VETO entries with no genuine abnormal event (background / sub-floor spike) |
| `QUALIFIED_CONTROL_ENABLED` | **false** | side control from QUALIFIED mass (discount DISTRIBUTED / premium-REJECTING / stale flow), not raw call-vs-put mass — NVDA 8/11 220C-vs-220P |
| `EXIT_ARBITRATION_ENABLED` | **false** | a raw control-flip is an INPUT to the reversal machine, not an exit; STRENGTHENING campaign suppresses control/opp exits |
| `REVERSAL_ENABLED` | **false** | new-spec P3: cross-strike ReversalCluster state machine; EXIT≠REVERSE — shadow |
| `EVENT_SELECT_ENABLED` | **false** | new-spec P4: pick the highest-event-information contract (not raw mass) — shadow |
| `EVENT_SELECT_WINDOW` | 2 | P4: consider ATM ± this many strikes when event-selecting |
| *— addendum layers (all ON in `.env`; code defaults shown) —* | | |
| `INVENTORY_ENABLED` / `INV_PASS_ON_HIGH` | true / true | #1-4: cost-basis + MFE; HIGH ambiguity → `INVENTORY_AMBIGUITY_PASS` |
| `INV_EVENT_MIN_CONTRACTS` / `INV_OBSERVE_INTERVAL_S` | 250 / 300 | min print size remembered; min seconds between recorded prints |
| `INV_DEPLETION_ENABLED` | true | #4: coarse remaining-inventory ladder FUNDED→PARTIAL→MAJORITY→CLOSED |
| `PACKAGES_ENABLED` / `PKG_VETO_ENABLED` | true / **false** *(env: ON)* | #7: size-matched spread/roll legs → soft discount + hard veto (both ON in `.env`) |
| `PORTFOLIO_RISK_ENABLED` / `PORT_GATE_ENABLED` | true / true | #18: correlated-exposure gate (`PORT_MAX_CORR_SIDE`, default 4) |
| `ROTATION_RESOLVER_ENABLED` | true | §23-24: name the rotation destination on a rotation exit |
| `EXPIRY_VALUE_ENABLED` / `LATE0DTE_GATE_ENABLED` | true / true | §36: LateDay0DTEValue (theta ramp) vetoes weak late 0DTE; #6 overnight carry |
| `CROSS_EXPIRY_DIR_ENABLED` | true | #8: forward-expiry control agreement confirms/vetoes direction |
| `HYPOTHESES_ENABLED` / `HYP_PASS_ENABLED` | true / **false** *(env: ON)* | #9: H1–H8 distribution + abstain-on-ambiguity (both ON in `.env`) |
| `DATA_QUALITY_ENABLED` / `DQ_DROP_ENABLED` | true / true | #11-12: validate OPRA snapshots; drop crossed/negative/no-mark; stale→low confidence |
| `HEDGE_FLOW_ENABLED` | true | #13: directional vs convexity-demand confidence (soft discount) |
| `DECOMPOSE_ENABLED` | true | #14: ΔP = delta·ΔS + ½·gamma·ΔS² + IV residual |
| `REGIME_ENABLED` / `REGIME_EVENT_DATES` | true / (empty) | #17: macro/vol confidence modifier; fill CPI/FOMC/earnings/OpEx dates weekly |
| `CAMPAIGN_TAXONOMY_ENABLED` | true | #21: end taxonomy (FAILED/REALIZED_PROFIT/ROLLED/…) stored at close |
| *— v3-review integration corrections (2026-08-16; all ON in `.env`) —* | | |
| `MULTI_CAMPAIGN_ENABLED` / `MAX_PRIMARY_POSITIONS` | true / **4** | items 1-2: multiple coexisting campaigns; incumbent no longer blocks a challenger |
| `RAW_FLIP_EXIT_DISABLED` | true | item 13: raw control flip can't flatten; ReversalCluster owns opposite exits |
| `FORMING_SPOT_EXEMPT_POSTERIOR` | 0.62 | item 9: exceptional FORMING events not spot-gated (volume senior) |
| `INV_MICRODIST_ENABLED` / `INV_MICRO_EXIT_FRAC` / `INV_MICRO_MIN_CLIPS` | true / 0.50 / 4 | item 5: cumulative small-clip unwind (no 250 floor) |
| `VALUE_MEMORY_ENABLED` / `VALUE_LOW_PCTILE` / `VALUE_CHEAP_PCTILE` | true / 0.10 / 0.35 | item 4: robust-value cheapness, not session-low |
| `INFO_MASS_ENABLED` / `INFO_MASS_WEIGHT` | true / 0.30 | item 15: InformationMass blended into discovery_share |
| `ATTN_TRANSFER_ENABLED` | true | item 12: continuous priority-investigation on attention transfer |
| `EXPIRY_SELECTOR_ENABLED` / `EXPIRY_SELECTOR_SHADOW` | true / true | item 10: rank expiries (shadow — logs, execution still nearest) |
| `PKG_VETO_MIN_CONF` | 0.75 | item 14: package hard-veto only when complex prob overwhelming |
| `DECISION_LEDGER_ENABLED` / `DECISION_LEDGER_FILE` | true / jakenew_decisions.jsonl | item 17: per-candidate record, ALL veto reasons |
| `BARSHOCK_TOD_ENABLED` | true *(module only)* | item 7: time-of-day baseline built+tested but NOT wired (needs multi-session history) |

---

## OI reconciliation & Discord outbox (2026-10-17, from the flow-handoff review)

The parts of the "Logic for Jake" flow handoff that apply to this engine. The rest of that document
(trade-level OPRA capture, condition-code maps, quote-at-print side reads, package taxonomy, `/follow`)
belongs to a separate tape-based bot — Jakenew polls contract snapshots and never infers a print's
aggressor side from quote location, so there was nothing there to correct.

**OI reconciliation (`analysis/oi_confirm.py`, rule `oi-recon-v1`).** For one contract and two adjacent
OI vintages, with V = the *full completed* session's volume and Δ = new OI − old OI, every traded
contract is opening-both-sides (OO), closing-both-sides (CC) or a transfer (T): V = OO+CC+T, Δ = OO−CC.
`oi_bounds(V, Δ)` returns the admissible ranges OO∈[max(Δ,0), ⌊(V+Δ)/2⌋], CC∈[max(−Δ,0), ⌊(V−Δ)/2⌋],
T∈[(V−|Δ|) mod 2, V−|Δ|]. Labels are aggregate annotations, never a trader's BTO/STO:
- `OPENING_SUPPORTED` Δ ≥ `OI_SUPPORT_RATIO` (0.50) × V · `OPENING_PARTIAL` 0 < Δ below that (was
  "inconclusive" under 15% before) · `OPENING_WEAKENED` Δ ≤ 0 (flat OI can hide transfers; falling OI =
  aggregate closes) · `RECONCILE_REQUIRED` |Δ| > V (missing/corrected volume, wrong vintage, exercise,
  expiry, corporate action) · `INCONCLUSIVE` an input is missing.
- The fingerprint no longer passes the fresh-*window* volume as V. It stores `fresh_vol_window`,
  `cum_volume_at_entry` (partial day) and an empty `session_volume` to fill after the close, plus
  `prior_oi_asof`/`new_oi_asof` — today's published OI belongs to the *prior* settlement and must never
  be compared with today's partial volume. Missing V → INCONCLUSIVE, never substituted. 0DTE has no
  next-session OI before expiry, so it gets no review.
- `LEGACY_LABELS` maps the retired labels for old `jakenew_campaigns.jsonl` rows (rows are not rewritten).

**Discord outbox (`notify.py`).** Cards were fire-and-forget: a timeout or Discord outage silently
dropped them. Now every card is written PENDING to a sqlite outbox (`NOTIFY_OUTBOX_DB`, default
`jakenew_outbox.db`, git-ignored) under key sha256(signal_id | state_version | evidence_hash | channel)
*before* the webhook is called, and marked SENT only when Discord returns a message id (`?wait=true`).
- 429 → honour `retry_after`; it holds the whole queue (order preserved) and does not use up an attempt.
- Timeout / connection error / 5xx → exponential backoff (`NOTIFY_BACKOFF_BASE_S` 5s, capped at
  `NOTIFY_BACKOFF_MAX_S` 300s); `NOTIFY_MAX_ATTEMPTS` (8) → DEAD. Other 4xx (bad webhook) → DEAD at once.
- `engine.poll()` calls `notify.flush()` first every poll (≤ `NOTIFY_FLUSH_LIMIT` cards), so the backlog
  drains after an outage or restart. The EOD attrition log prints `NOTIFY-OUTBOX {status: count}`.
- Same key enqueued twice → one card. Trade cards (entry/scale/exit) and STRENGTHENING carry a unique
  event id. Near-miss/flip/plain cards default to title|date + evidence hash, so an identical re-render
  that day is suppressed and a changed card still posts.
- Every payload sets `allowed_mentions: {parse: []}` — no card can ping @everyone/@here.
- Research cards (near-miss, flip) carry the footer "For research only. Not investment advice. Verify
  fills and manage your own risk." STRENGTHENING is 🟡 (watched activity), not 🟢. Green/red stays on
  cards for the engine's own submitted (paper) orders.
- Known limit: Discord webhooks accept no idempotency key, so a timeout *after* Discord accepted the
  post can still produce one duplicate on retry. Everything else is retried without loss or duplication.
- Tests: `test_notify_outbox.py` (stubbed HTTP: timeout, 429, 5xx, 404, dedupe, mention suppression).


## Handoff alignment, round 2 (2026-10-17) — everything else that maps onto Jakenew

Decision: Jakenew **keeps placing its own paper orders** (those are real submitted orders, so their
cards stay green/red). Everything else follows the flow handoff's evidence rules. Ruleset stamp:
`analysis/channels.py` `RULESET_VERSION = handoff-2026-10-17`, `SCHEMA_VERSION = jakenew-record-v2`.

**Exchange calendar (`data/exchange_calendar.py`, used by `data/market_utils.py`, `main.py`).** Rule-based
NYSE holidays (observed-day shifts, Good Friday, Juneteenth 2022+) and 1:00 pm ET early closes (Jul 3
when Jul 4 is Tue–Fri, day after Thanksgiving, Dec 24). Previously a holiday counted as a normal open day,
and on a half day the EOD flatten still fired at 14:55 CT, *after* the 12:00 CT close, so a 0DTE would not
be flattened. Now: holiday → `main.py` exits at launch; half day → close 12:00 CT, EOD flatten 11:55 CT,
entry cutoff 11:40 CT, and the late-0DTE theta ramp spans the real 210-minute session. One-off closures:
`EXTRA_MARKET_HOLIDAYS`. Next half days: **2026-11-27** and **2026-12-24**. Tests: `test_calendar.py`.

**Feed coverage (`analysis/coverage.py`, `COVERAGE_*`).** Fresh flow is `cum(b) − cum(a)`; after a feed
gap the next window lumps the whole gap into one read, which looks like a fake shock. A ticker with no usable
ingest for > `COVERAGE_GAP_S` (**60s** since 2026-10-19; was 30s, below the real cycle) or that **missed a
completed poll cycle** (fetch failed / empty / all dropped) has a coverage incident, measured on the ticker's own
data-receipt time. Once data resumes it stays DEGRADED for `COVERAGE_RECOVERY_S` (180s) and `_open_wave` rejects
new entries with `COVERAGE_DEGRADED`. Exits and management still run. Gaps ≥ `COVERAGE_NOTIFY_MIN_GAP_S` (60s)
post **one** 🔵 FEED GAP notice per cycle listing every affected ticker and the cause (which fetch failed, how
long the cycle waited). Backtest uses a 150s gap threshold for its 1-minute cadence.

**Missing history ≠ zero (`analysis/mass.py`).** The per-ticker abnormality z is 0 on an empty baseline.
That means "no evidence", not "measured normal", so the output now carries `baseline_n` and
`baseline_quality` (UNSEEDED until `MASS_BASELINE_MIN_SAMPLES`), and both go to the ledger.
A z of 0 never passes an abnormality gate, so there is no extra veto.

**DTE channels + provenance (`analysis/channels.py`).** Every ledger record and card carries the NY-calendar
DTE and its channel: `zero_dte` 0, `weekly` 1–7, `short_term` 8–30, `swing` 31–99, `long_dated` 100+
(multi-expiry → earliest live expiry). Ledger records also carry `schema_version`, `ruleset_version`,
`ny_session`, `coverage`, `catalyst_status`, `catalyst_event_mismatch`, `baseline_quality`,
`package_ratio` and `package_association`.

**Verified catalysts (`analysis/catalyst.py`, `CATALYST_FILE` = `catalysts.json`, optional).** An event
counts only if its source was published at or before the signal and the event is still in the future. A row
missing source URL, publication time, observed time or BMO/AMC timing is UNVERIFIED, and the card says so.
An expiry before the event (or on an AMC event day) is an EVENT_MISMATCH. With no file, cards say "no
verified calendar loaded". `REGIME_EVENT_DATES` still only scales caution. Catalysts are context only, not a gate.

**Package candidates (`analysis/packages.py`, `pkg-snapshot-v2`).** Leg sizes are reported as a reduced
whole-number ratio after rounding to `PKG_RATIO_LOT` (4,000 vs 7,000 → `4:7`, never 1:1). The co-print
partner is recorded. Association is `TIME_SIZE_ONLY` (the weakest grade: the snapshot feed has no condition
codes, venue or ms timestamps). `net_side` and `net_cashflow` are always UNKNOWN. Legs below 100 contracts
never qualify (`PKG_MIN_LEG_CONTRACTS` = 200).

**Retired labels** (old records keep their text; `channels.LEGACY_LABELS` maps them):
`OPPOSITE_SIDE_CAMPAIGN_CONFIRMED → …_SUSTAINED`, `REVERSAL_CLUSTER_CONFIRMED → …_SUSTAINED` (a restored
state is upgraded on read), `ATTENTION_CONFIRMED → ATTENTION_SUSTAINED`, `VERIFIED_DISTRIBUTION →
SUSTAINED_DISTRIBUTION`, `MAJORITY_EXITED → LIKELY_MAJORITY_EXITED`, campaign thesis "CAMPAIGN CONFIRMED" →
"CAMPAIGN QUALIFIED". Card text no longer says "institutional" or "verified distribution".

**Cards.** Entry (own paper order): "{side}-side premium leads… read as bullish/bearish flow *if* it is
fresh directional buying" plus the **best non-directional alternative** (`hypotheses.best_alternative`), the
NY time, DTE channel and one catalyst line. Near-miss (🟡 amber, research footer) follows the handoff
layout: facts, NY time + DTE channel, a working hypothesis with its best alternative, the **one next check**
(the largest route-score drag), and a catalyst line. No card can ping anyone.

**Trade-level parts** (print archive, condition codes, quote-at-print side reads, venue/ms packages, private
follows, 20-session series baselines) cannot run on the snapshot engine; they live in the separate tape
lane described next.
Tests: `test_handoff_alignment.py`, `test_calendar.py`, `test_notify_outbox.py`, `test_newspec.py`.

---

## Tape lane — trade-level options-flow research collector (2026-10-17)

A **separate process** (`tape_main.py`, `run_tape.bat`, package `tape/`) that runs beside the engine. It
never places orders and never touches `jakenew_state.json`. It answers four questions and keeps them
apart everywhere: **what printed**; **who likely took liquidity** (`LIKELY_TAKER_BUY` / `LIKELY_TAKER_SELL`
/ `UNKNOWN`); **open/close effect** (never known from the tape, only aggregate next-session OI
annotations); and **trade merit** (not decided, only a research outcome ledger).

**Verified provider facts (Alpaca, 2026-10-17):**
- The OPRA stream is msgpack. Authentication, explicit subscription and per-contract acknowledgements
  were checked live for 400 contracts.
- Historical option trades exist. Historical option **quotes do not** (404), so a print in a feed gap
  can never get a side.
- Trades carry **one condition letter**, an exchange code and a nanosecond time, but **no trade ID or
  sequence**.
- The contract master gives OI with `open_interest_date` and the multiplier. Daily bars give per-contract
  volume.

**Pipeline (`tape/pipeline.py`):** one deterministic processor for both live capture and replay.
- **Raw archive first** (`tape/store.py`): every original message goes to
  `tape_raw/<session>/events.jsonl` (append-only, crash-safe, gzipped at close) with a sequence number,
  receive time, source and checksum. The state DB is `jakenew_tape.db`. Every print row carries parser,
  condition-map and rule versions.
- **Conditions** (`tape/conditions.py`, pinned `alpaca-opra-cond-2026-10-17`, checked against real NVDA
  prints): tags describe mechanics only (ELECTRONIC, ISO, AUCTION, CROSS, FLOOR, COMPLEX, STOCK_TIED,
  LATE, CANCEL, UNKNOWN). Only `I` and `S` are side-eligible. On startup the live definitions are compared
  with the pin and any drift is logged.
- **Side** (`tape/side.py`): uses the last quote at or before the print, ≤500 ms old, bid > 0, ask > bid,
  width ≤ 25%, location ≥ 80% (buy) or ≤ 20% (sell). Anything else is UNKNOWN, with the reason stored.
  Spot must be ≤ 5 s old and at or before the print.
- **Dedup without trade IDs:** identical simultaneous fills are distinct prints. A backfill copy is
  dropped only when it matches a streamed copy, counting multiplicity. A cancel (`A/C/E/G`) marks its
  original CANCELLED and is kept as a CANCEL_RECORD; affected screens are rebuilt.
- **Mechanics tags:** relative block (≥ 100 contracts and ≥ 5× series median), rapid sweep candidate
  (≥ 250 contracts, ≥ 2 venues, ≤ 100 ms).
- **Screens** (earned screens stay earned; a later smaller print never removes one):
  - REL_VOLUME: ≥ 5× the 20-session median.
  - REL_PREMIUM: ≥ 2× the name's p95 print premium.
  - VOL_GT_OI: session volume above prior OI.
  - QUOTE_SIDE.
  - SHORT_DATED_OTM: 0–7 DTE with valid spot.
  - REPEATED: ≥ 3 prints, each ≥ max(10 contracts, 20% of the median).

  A UOA candidate needs two screens, including REL_VOLUME or REL_PREMIUM. Missing inputs are recorded,
  never zero-filled.
- **Working hypothesis** (amber): needs a healthy feed, ≥ 3 ordinary electronic prints and ≥ 500 contracts,
  volume > 3× prior OI, one side ≥ 60% of captured volume, UNKNOWN side ≤ 25%, no package link and no
  stock tie. The text is always conditional and names its alternatives ("put-writing is a conditional
  opening thesis; alternative: long puts sold to close, or a package/hedge leg"). There is no
  PROBABLE/CONFIRMED label and no single confidence number.
- **Observation dimensions** are kept separate: rarity, linkage, side thesis, OI annotation, revisions
  (THESIS_WEAKENED / INVALIDATED / CONVEXITY_CONTEXT_CHANGED / OI_ANNOTATION), event, urgency (DTE
  channel), executability and coverage. Each material change is a new version in
  `observation_versions`, and the original stays.
- **Campaigns:** a durable `campaign_id` per issuer/expiry/right/side. Several can coexist, and a new one
  never auto-closes an older one.
- **Packages** (`tape/packages.py`):
  - Windows: 1,000 ms event-time windows, ≤ 128 prints, 2–4 series of ≥ 100 contracts each, ratios
    reduced by GCD.
  - Exact small ratios: every part of the reduced ratio must be ≤ 10. Real NVDA data showed 1-second
    windows summing to 668:667 by coincidence.
  - Crowded windows are segmented by venue and tight timing, or the window abstains. One print belongs
    to at most one package.
  - Association grades run from A (complex tags, common venue, ≤ 10 ms) to D (time and size only).
    D-grade packages are stored but not posted.
  - Net side, cashflow and stock leg stay UNKNOWN. The leg-cashflow sum is shown only for opposite-side
    legs, labelled as conditional on a verified linkage.
- **OI** (`tape/oi.py`): interval bounds from `oi-recon-v1` using complete intervening volume.
  "Short-call buyback plausible" (sell-side build ≥ 65%, build ≥ 50% of volume, ≥ 75% retained,
  ≤ 14 days, buy print below that session's VWAP) is offered as an alternative only. POSSIBLE_ROLL
  lists every competing destination. 0DTE never gets a next-session OI annotation.
- **Cards** (`tape/cards.py`):
  - Layout: title; NY time, DTE and channel; status; facts; one conditional read with its alternative;
    one next check; one catalyst line; signal ID and version; disclaimer.
  - Colours: blue for observations, amber for hypotheses, revisions and watched activity. Green/red only
    for a user-verified fill in the private feed.
  - Five DTE channels; a package goes to the bucket of its earliest live expiry. Routine repeats are
    rate-limited per campaign, and material updates bypass the cooldown.
  - Samples: `docs/TAPE_CARD_SAMPLES.md` (synthetic).
- **Delivery:** through the existing durable outbox, using an alias per channel (`tape:zero_dte` …
  `tape:private`). Only the alias is stored, never the webhook token, and a 429 holds only its own
  channel. **OFF unless `TAPE_DISCORD_ENABLED=true`**; cards are always stored in the `cards` table.
- **Private follows** (`follow.py`): a local CLI, since there is no authenticated bot.
  - Commands: `add` (signed OCC legs, optional stop/target/catalyst), `fill` (`--verified`), `list`,
    `remove`. Only the owner can modify a watch.
  - Market prints on a watched leg produce a private amber card that is never assigned to the user.
  - P/L only with signed quantities and a recorded fill.
- **Baselines** (`tape/baseline.py`), run each morning by `tape_main.py`:
  - Series median: the previous 20 completed sessions from daily bars, ≥ 10 sampled sessions. Sessions
    before first observation are missing, not zero.
  - Name p95 print premium: pooled log-bucket histograms from captured sessions, or `--bootstrap`
    (bounded REST, about 6 minutes for 7 names × 20 sessions).
  - Prior OI: the latest vintage dated before the session **and fetched before the print** (point in
    time).
  - Same-day, future or > 7-day-old baselines are rejected. Quiet builds (≥ 100 contracts over
    5 sessions, each < 50) are kept for review.
- **Collector** (`tape/runtime.py`):
  - Connections: one OPRA connection plus one SIP spot connection, with explicit, acknowledged
    subscriptions to a bounded universe. Watched contracts come first, then nearest expiries and strikes
    round-robin up to `TAPE_MAX_CONTRACTS` (400 of 2,260 eligible on 2026-10-17); the denominator is
    logged.
  - Failures: stale feed (15 s), disconnect or queue overflow leads to `feed_down`, reconnect,
    `feed_up`, then a REST trade backfill of the gap and `backfill_done` with a completeness flag. Gap
    prints keep side UNKNOWN; their contracts are context only and a degradation card is posted.
  - Replay: `python tape_main.py --replay <session>` rebuilds state from the archive alone.
    `test_tape.py` proves a forced 30-second disconnect replays to the same versioned state.
- **Review:** `python tape_report.py [session …]` reports print statuses, every side-abstention reason,
  latency, incidents, leading-read abstentions, packages by grade, and the precommitted outcome (buy the
  ask at observation, sell the bid at +30/+120 min, fees). It shows sample size, independent campaign
  clusters and Wilson 95% intervals, and makes no hit-rate claim.

**Measured on real data** (NVDA+AAPL, 120 contracts, 2026-10-16 via REST):
- Throughput: 158,250 prints at 3,185 prints/s.
- Conditions: `I` 53%, `a` (auction) 33%, `f`/`g`/`j` complex 10%, `S` 4%. A third of all prints can
  never get a side by rule.
- Packages: 40 candidates, mostly A-grade exact 1:1 verticals.

**Configuration and deployment checklist**
1. `pip install -r requirements.txt` (adds `msgpack`, `websockets`).
2. Confirm the Alpaca plan's **OPRA quote-subscription limit** and connection count, then set
   `TAPE_MAX_CONTRACTS` ≤ the limit. A non-acknowledged contract is a SUBSCRIPTION_FAILED incident.
3. First run: `python tape_main.py --baseline-only --bootstrap` (fills the p95 history), then check the
   `BASELINE-JOB` log line.
4. Schedule `run_tape.bat` on weekdays at about 08:05 CT, alongside `Jakenew_DailyRun`. It exits on
   non-trading days and after the close (+5 min).
5. Before any Discord redistribution: obtain the provider's **written terms** for OPRA display,
   redistribution, retention and per-user display. Then set `DISCORD_WEBHOOK_ZERO_DTE / _WEEKLY /
   _SHORT_TERM / _SWING / _LONG_DATED` (and `_PRIVATE`) and `TAPE_DISCORD_ENABLED=true`. Keep webhooks in
   `.env`, not in code.
6. Optional verified catalysts: `catalysts.json` (see `analysis/catalyst.py` for the fields).
7. After each session: `python tape_report.py <session>`. Next morning the run attaches OI annotations
   automatically (`--annotate` does only that).
8. Freeze thresholds before forward paper observation. `RULE_VERSION` (`tape-v1-<hash>`) changes when
   any threshold changes and is stamped on every print row.

**Remaining unknowns**
- The account's actual OPRA quote-subscription entitlement and connection limit.
- Live intraday message rates: quote volume for 400 contracts has not been measured during a session
  yet.
- Whether Alpaca's stream ever re-sends prints after a reconnect.
- Corporate-action adjustment is flagged (root ≠ underlying or multiplier ≠ 100) but adjusted series are
  not specially reconciled.
- The handoff ZIP (its 43-tag list, 52 tests and fixtures) was never provided. The taxonomy and tests
  here implement every family the handoff names, but they are not that ZIP.

---

## Campaign-flow policy (Logic for Jake.txt, Oct-15 revision) — `campaign_flow/`

A separate policy built from the consolidated developer README. Its four decisions stay separate: **observe**
concentrated shocks, **qualify** the buy hypothesis (exact-contract low value band and verified clusters),
**propose** an entry, and **manage** each filled campaign. A score never authorizes an entry, a proposal is
never an execution, and a usable quote never establishes a fill. Every threshold is a configurable paper
default (`campaign_flow/settings.py`, env `CF_*`) folded into `RULE_VERSION`. None of them is calibrated.

**Data (snapshot adapter, `campaign_flow/pipeline.py`).** Each engine poll is recorded to
`cf_obs/<session>.jsonl`, together with every reference fetch, each stamped with the time it became
available. The pipeline only reads those observations, so a replay reproduces the live decisions.
- **Windows:** completed 60 s slots, bounded by the polls on either side, so every contract of a ticker shares
  the same window boundaries.
- **Bins:** the volume added between consecutive polls; the bins are disjoint and sum to the window volume.
- **Near-ask volume:** an interval's added volume counts as near-ask when its newest print is an ordinary
  electronic print at or above 80% of the way from bid to ask. This is a *proxy*: snapshots show only the
  newest print, not every trade.
- **Print count and largest print:** lower bounds.
- **Complex legs:** MIXED if any observed print is complex or stock-tied. Otherwise UNAVAILABLE, never SIMPLE.
- **Baseline:** the same contract's volume per window in the same time-of-day bucket of the prior session,
  from 1-min bars.
- **Value references:** prior-session 1-min closes plus today's observed prints, all on a trade-price basis.
- **Underlying direction:** the engine's own rule, the spot change over 30 s; a flat spot confirms neither
  side.
- **Coverage:** the listed strikes in the band must all be present, and >= 90% of quotes <= 30 s old.

**Rules, by handoff section**
- §3 **Exact-contract value gate:** compares only with earlier marks of the same series. Needs >= 20 marks,
  all strictly before the window start. Percentile = (marks below + 1/2 marks equal) / n.
  - <= 0.25 is LOW, the only band that earns buy attention.
  - Middle band: `PREMIUM_OUTSIDE_LOW_VALUE_BAND`.
  - >= 0.75: `HIGH_VALUE_FLOW_SELL_OR_CLOSE_POSSIBLE`.
  - Too little history: `EXACT_CONTRACT_VALUE_HISTORY_MISSING`.
- §4 **Shock:** a window <= 300 s with >= 50 contracts, >= 3 prints, >= 2x baseline and >= 60% near-ask. It
  also needs a concentrated shape: either the top bin >= 45% and top two bins >= 70%, or the largest print
  >= 35%. A flat shape is background. Premium must end higher than it started for the shock to count toward
  control; otherwise `FLOW_WITHOUT_PREMIUM_ACCEPTANCE_WATCH`.
- §5 **Clusters:** calls and puts are checked separately within each expiration. A cluster is either a pair of
  neighbouring qualifying strikes (gap <= 2.5% of spot) in two matching window slots, or one strike in three
  windows. Windows must end <= 420 s apart, the latest <= 300 s old, the snapshot <= 60 s old, with complete
  coverage.
  - BULLISH_CONTROL: calls clustered, puts not, plus bullish underlying.
  - BEARISH_CONTROL: the mirror.
  - Both sides clustered: CONTESTED.
- §6 **Board:** the strongest eligible event per side per ticker.
  - Score: 100 x (0.55 surprise + 0.30 shape + 0.15 recency) x relevance, where relevance runs 0.65-1 by
    strike distance in expected-move units.
  - Board order uses the raw score.
- §7 **Turnover resemblance:**
  - Match budget: min(previous volume, morning OI, OI build), or half strength without the earlier OI.
  - Only the part of a window that overlaps the budget counts.
  - For 0DTE, the earliest same-day cohort counts at half weight.
  - The board keeps raw and discounted scores side by side, with `LEADER_SCENARIO_DISAGREEMENT` and
    `SIDE_SCENARIO_DISAGREEMENT` labels.
  - Resemblance never vetoes a same-side entry.
- §8 **Entry:**
  - Requirements: verified one-sided control, a suitable contract and reserved capacity.
  - Contract checks: right matches the direction; the expiry outlives the planned end (SWING +1 day); the
    quote <= 30 s old; relative spread <= 0.30; ask size >= 1.
  - Reference budget: $2,000, at most 2 contracts per proposal.
  - Daily cap: **5** proposals per ticker per New York day (`CF_MAX_PROPOSALS_PER_TICKER_DAY`; the spec says 2,
    raised to 5 on 2026-10-25); cancelled proposals still count.
  - **Since 2026-11-01 (Mag 7 brief):** at most **one call and one put entry per day across the Mag 7**
    (`DAILY_CALL_PUT_ENTRY_CAP`), and the cluster must reach **CONFIRMED conviction**
    (`CONVICTION_NOT_CONFIRMED:<tier>`). See *Mag 7 adjustments brief* below.
  - The old 0.550 route score is only logged (`VERIFIED_CLUSTER_BELOW_SCORE_BOUNDARY`).
  - Horizon: INTRADAY by default; the planned end is 15:30 NY. OVERNIGHT is chosen only by the carry rule in
    *Mag 7 adjustments brief* (flow in the next expiration on a consolidated day).
  - A cluster selects contracts only in its own expiration.
- §9/§10 **OI reference:**
  - Before the cutoff, the contract master (OI with its as-of date) is fetched.
  - The nearest expiration is frozen once per session between open - 10 min and the open. A late run records
    MISSING and is never backfilled.
  - The official open (first SIP 1-min bar) is pinned.
  - Levels: the three largest OI nodes among the six nearest eligible strikes on each side of the fixed open.
  - Zones for clusters exist only in the journal; OI never gates entries or exits.
- §11/§12 **Management:**
  - **No exit** for premium dips, lower lows, board changes, pauses, vague exhaustion, OI touches or
    +60%/+150% gains. (Since 2026-11-01 one trailing stop exists: armed at +100%, exits after giving back 60% of
    the peak gain; see *Mag 7 adjustments brief*.)
  - **No default stop.** `CF_PREMIUM_LOSS_LIMIT` and `CF_UNDERLYING_INVALIDATION_PCT` are off unless set
    before entry.
  - **Full-exit requests, in priority order:**
    1. Overnight underlying gap at the first open after entry: favorable sells all; adverse by >= 1% exits;
       otherwise the carried position is reviewed at open + 15 min.
    2. Planned or expiry deadline: 15:30 NY, earlier on a half day.
    3. Precommitted risk limit.
    4. Trailing stop from the peak (+100% arm, 60% giveback).
    5. Confirmed opposite one-sided cluster with bearish/bullish underlying, using flow after this
       campaign's entry only. A turnover-matched cluster also needs independent unmatched follow-through.
       Since 2026-11-01 the opposite side must also be CONFIRMED with a score >= 1.2 x the entry bar, and the
       position must have been held >= 15 min.
- §13/§14 **Orders and lifecycle:**
  - An exit intent persists through unusable quotes (`EXIT_PENDING_EXECUTABLE_QUOTE`) and partial fills.
  - States: PROPOSED -> ACTIVE -> ENTRY_PENDING / CLOSED / CANCELLED. Fills update the weighted average entry;
    an unfilled remainder is cancelled after 90 s.
  - An opposite entry waits until the source campaign is fully CLOSED, then becomes a new campaign that
    references it. While an opposite campaign is open, only this rotation path may enter the other side.
  - Orders use idempotent client ids (`cf-<campaign>-E`, `-X<n>`), and every event runs exactly once.
- §15 **Cards:** ENTRY_PROPOSED / ENTRY_FILLED / EXIT_PROPOSED / EXIT_FILLED, mention-safe fields. Cards are
  published only in PAPER mode with `CF_DISCORD_ENABLED=true`; SIM fills are never published. Since 2026-11-01
  **only the FILLED cards are posted** (proposals stay in the journal) and the wording is neutral; see *Mag 7
  adjustments brief*. (`docs/CAMPAIGN_FLOW_CARD_SAMPLES.md` shows the earlier format.)
- §16 **Journal:** `jakenew_campaign_flow.db` (schema `cf-journal-1`; an unknown schema is refused) holds:
  - windows with every rejection reason, value provenance, the board, candidates and WATCH reasons
  - proposals, orders, fills and reconciliation exceptions
  - the OI chains, freeze and opening price
  - turnover memory and cohorts
  - cards and shadow marks for suppressed candidates (+5/+15/+30 min, close, next open), which are
    observations and never fills

**Restart:** the session log is replayed in memory-only rebuild mode (no decisions, orders or cards), then live
polls resume; re-delivered polls are rejected as duplicates.

**Integration decisions that the source left open:**
- Pair adjacency follows the reference (neighbouring qualifying strikes, no ATM gate).
- The near-ask tolerance, baseline estimator and sync rule are as above.
- A zero-price exit is allowed only as an explicit expiration write-off record.
- An opposite ordinary entry is blocked while an opposite campaign is open (rotation path only).

**Tests:**
- `test_campaign_flow.py`: 113 checks covering all 38 acceptance items.
- `test_campaign_flow_pipeline.py`: windows -> cluster -> proposal -> fill -> rotation -> close -> opposite
  entry; replay determinism; restart; partial fills; TTL cancel; no duplicate orders or cards.

**Known limits:**
- Snapshot polling sees only the newest print per poll, so near-ask, print counts and complex-leg status are
  proxies or lower bounds.
- The handoff's numeric thresholds are unvalidated.
- The October 15 review trades (AAPL 345C, GOOGL 350P, NVDA 215P, AMZN 252.5P, TSLA 360P, MSFT 537.5P) are
  in this engine's log for **2026-10-15**. `cf_report.py 2026-10-15` lists them: 5 of 6 exits used reasons
  this policy removes. No synchronized tape for that day exists to replay the new policy over it.

## Decision-time semantics, parallel fetch, ops reporting (2026-10-19)

**The bug.** On 2026-10-19 every campaign-flow candidate (162 evaluations, 34 unique) was WATCH with
`INCOMPLETE_TRADE_QUOTE_OR_EXPIRY_COVERAGE` + `NO_SUITABLE_CONTRACT` (`QUOTE_FUTURE_DATED`). Each poll was stamped
at the **cycle start**, before any ticker was fetched; tickers were then fetched one after another (~1.5 s each),
so 77% of quotes (154,771 / 200,076) carried a time later than their poll — median +6.3 s, max +32 s, growing
~1.5 s per fetch position. Not a clock, units or timezone problem: local clock +0.05 s vs NTP, Alpaca's HTTP
Date agrees within its 1 s resolution, and the leads are seconds, not hours. `python cf_replay.py <day>
--evidence 8` prints the per-candidate table (cycle start, quote time, lead, estimated receipt, decision).

**The fix.**
- `engine._ingest_all` fetches the Mag-7 **in parallel** (one worker per ticker; ~7.7 s → ~1.7 s, receipts
  within ~0.1 s of each other) and still processes them sequentially in `MAG7` order.
- Each ticker's poll is stamped at the **local receipt of its last response** (`timing.recv_ts`). The
  observation keeps `poll_start_ts`, `fetch_start_ts`, `recv_ts` and the server `Date`
  (`basis: LOCAL_RECEIPT`).
- Campaign-flow decides at that time. Quotes that are genuinely future-dated (leading the decision time by more
  than `CF_QUOTE_CLOCK_TOL_S`, 0.25 s) or stale (> 30 s) are still rejected. Any remaining future quotes are
  counted in the snapshot evidence and journaled as `QUOTE_TIMING`.
- **Replay** (`cf_replay.py`): polls recorded before the fix have no receipt time, so they are re-stamped at the
  newest quote/trade time in the poll + 1 s, capped below the next cycle start. Original stamps are kept;
  `--as-recorded` reproduces the live result as a control.

**Replay of 2026-10-19 (`cf_replay.py 2026-10-19 --both`).**
- The **control** (original stamps) reproduces live exactly: 162 evaluations, 34 unique, 0 pass coverage,
  0 proposals.
- The **re-stamped** replay gives 215 evaluations (60 unique). **196 of 206 WATCH now pass coverage**, and
  there are **9 proposals**.
- Where the WATCH evaluations stop first: coverage 10, contested clustering 12, underlying not confirmed 91,
  risk/caps 93. The caps are `DAILY_ENTRY_PROPOSAL_CAP` 185 and opposite campaign open 14. No contract-
  liquidity or expiry failures remain.
- 1049 extra rows are rotation re-checks of closed campaigns. The rotation path evaluates every window close
  even with no opposite cluster; that is journal noise worth trimming.
- Under the simulated broker, the 6 closed campaigns realized −$1,160. Three 0DTE campaigns never found a bid
  at the 14:30 deadline. That is one session with uncalibrated thresholds: not an edge claim either way.

**Feed gaps.** The 2026-10-19 cards showing 63 s across six tickers and 80 s for GOOGL were a single stall.
The GOOGL snapshot request failed after retries at 14:20:27, the sequential cycle waited on it, and GOOGL missed
that cycle entirely. Separately, 2352 "incidents" that day were normal 38–44 s cycles (the once-a-minute
multi-expiry reads) tripping a 30 s threshold. See *Feed coverage* above for the new rule.

**EOD summary.** With `CF_MODE` on, the EOD Discord summary now leads with the **campaign-flow** funnel from its
own journal (`campaign_flow/summary.py`): windows / invalid reasons → eligible / accepted shocks → candidate
evaluations (unique) → WATCH reasons and contract-level reasons → proposals → orders → fills → cards (published)
→ outbox. The legacy attrition line follows, labelled compute-only in PAPER mode; that is where the old
all-zero summary came from.

**Paper workflow test.** `test_cf_paper_e2e.py` runs synthetic, labelled test data through the real Runner
(PAPER), AlpacaPaperBroker, journal, cards and `notify` outbox. An Alpaca-paper REST double and a local
Discord-style webhook stand in for the outside world. It checks:
- proposal → order → fill → campaign → delivered card;
- a mid-session restart (rebuild from `cf_obs`);
- 30 re-delivered polls;
- repeated broker fill reads;
- a re-emitted card (no duplicate order, fill or post).

**Open adapter question (not changed):** 12,079 windows on 2026-10-19 were rejected `INVALID_LARGEST_PRINT`. The
newest print's size exceeded the window's cumulative-volume increase, which suggests the snapshot `dailyBar`
volume lags `latestTrade`.


## Mag 7 adjustments brief (2026-11-01) — `mag7-algo-adjustments-brief.pdf`, Oct 30 paper session

The owner's brief listed seven refinements. Each is handled as follows; items marked **[owner]** use a
documented default until the owner answers the brief's open questions.

1. **Overnight holds on any weekday** (`CF_OVERNIGHT_*`). Why only Tue/Thu before: the Mag 7 list Mon/Wed/Fri
   expirations, and the engine polls only the nearest one. Tue/Thu contracts are 1DTE, Mon/Wed/Fri contracts
   are 0DTE, and campaign-flow ran every trade INTRADAY anyway. Now, when the nearest expiration expires today,
   `engine._fetch_one` also fetches the **next expiration**, which joins the same `cf_obs` poll. A verified,
   CONFIRMED cluster **in that later expiration** becomes an **OVERNIGHT** proposal when:
   - it is >= 12:00 NY;
   - the day is consolidated (session high-low <= 2% of the open); **[owner: carry conditions]**
   - carried premium across positions stays <= $600 (`OVERNIGHT_PREMIUM_CAP`).

   Otherwise it is journaled as `OVERNIGHT_NOT_TAKEN` and not traded. Same-day flow keeps trading INTRADAY in
   its 0DTE contract, and Tue/Thu behaviour is unchanged. A 0DTE contract can never be picked for an overnight
   plan. Clusters now select contracts only in their own expiration.
   - **Review at the next open:** a favorable gap sells all (as before). An adverse gap >= 1% exits
     (`ADVERSE_OPEN_GAP_CARRY_REVIEW`). At open + 15 min, a carried position that is not in profit, and whose own
     side is not at least BUILDING, exits (`OVERNIGHT_OPEN_REVIEW_NO_CONTINUATION`). The expiry-day 15:30
     deadline still applies.
   - **Cards:** the entry card says "Overnight position (may be carried past the close; gap risk)". Next-day
     exit cards say "Carried overnight from <day>".
   - **Proof is forward only:** recorded `cf_obs` sessions before 2026-11-02 contain only the nearest expiration,
     so no replay of past data can show a Mon/Wed/Fri carry.
2. **Old-format alerts.** The "ENTER … / Exit plan / attention board / Jakenew Attention Engine · SHADOW" cards
   were this bot's **legacy engine**, which still posted while compute-only. The 10-30 GOOGL PUT 280 @ $1.29
   09:57 ET card matches its `[SHADOW] ENTER` log line. Every legacy post (entry/scale/exit/flip/coverage/
   near-miss/strengthening/legacy EOD) is now behind `LEGACY_DISCORD_ENABLED` (default **false**). Every
   main-webhook post goes out as **"Mag 7 Algo"** (`DISCORD_USERNAME`). Note: **Jakevolume's `.env` holds the
   same webhook URL**, and its `Jakevolume_DailyRun` task is enabled. That is a second process holding the
   credentials; rotating the webhook fixes both.
3. **No "awaiting fill" cards.** Only ENTRY_FILLED / EXIT_FILLED are published (`CF_PUBLISH_PROPOSED=false`).
   Proposals are journaled with `published=0`; a proposal that never fills posts nothing. The card shows the
   fill price, not the indicative quote.
   **Partial fills are never published (2026-11-04, user request: members see only Opened and Closed).**
   Every partial fill is still journaled as its own card, with `published=0` and `sheet.partial=true`.
   Members get one combined card per position instead (`Pipeline._sync_orders` / `_publish_open`):
   - **Opened** is posted once the entry order is complete: total contracts at the weighted average entry.
     If the unfilled remainder is cancelled, it is posted then, for the contracts actually bought.
   - **Closed** is posted only when the position is flat: total contracts at the weighted average exit.
     If an entry is still filling when the position goes flat, its Opened card is posted first.
   - A whole-order fill posts exactly as before: same card ids, one card per fill.
   - No "Reduced" card is ever posted.
4. **One call and one put entry per day** (`CF_MAX_ENTRIES_PER_RIGHT_DAY=1`, `CF_ENTRY_CAP_SCOPE=ALL`,
   reason `DAILY_CALL_PUT_ENTRY_CAP`). **[owner: across all names or per ticker]** Rules:
   - Every proposal that reserves or reached a fill counts. One cancelled unfilled frees its slot.
   - A stop-out does not reopen the slot.
   - A rotation entry uses the slot.
   - An overnight carry counts on the day it was opened.
   - Exits follow their entry.
5. **Conviction tiers** (`campaign_flow/conviction.py`, `CF_CONV_*`). A verified cluster says where flow
   concentrated. Conviction asks whether it looks institutional. It is computed per ticker and right, over the
   last 10 min, summed across all near-the-money strikes (|K/spot-1| <= 3%) and observed expirations:
   - size vs the same-time-of-day prior-session baseline (>= 3x);
   - per-window volume vs the side's median window earlier today (>= 2x; unscored until 5 windows exist);
   - persistence: consecutive latest windows >= 2x baseline (>= 3);
   - near-ask share (>= 0.25: the snapshot proxy runs 0.1-0.35 on real flow);
   - premium dominance over the other side (>= 0.6);
   - share of volume in windows whose option mid rose (>= 0.5).

   Each component scores min(1.5, value/threshold)/1.5, and the score is the mean x 100.
   - **CONFIRMED** = score >= 65 with the size, persistence and $250k premium gates.
   - **BUILDING** = score >= 45 with size >= 2x.
   - Otherwise **WEAK**.

   Entries need CONFIRMED (`CONVICTION_NOT_CONFIRMED:<tier>`). The inputs are journaled on every candidate and
   exit decision.
   - **Calibration (replay of 2026-10-30 TSLA):** the owner's good moments scored 66-93 (09:45-09:49 call
     flow; 11:05-11:12 put flow). The rejected ones scored 37-57 (the 13:22 "opposite call cluster"; the
     13:24-13:26 397.5C alert).
   - **[owner: more labelled examples]** The 14:30 clustering the owner pointed to is not in the data: the
     process stopped at 14:16 ET that day.
6. **Exits hold longer on weak opposite flow:**
   - **Opposite-cluster rotation:** needs the opposite side CONFIRMED with a score >= 65 x 1.2 = 78
     (hysteresis), and >= 15 min held (`CF_MIN_HOLD_S`). It logs `ROTATION_BELOW_EXIT_CONVICTION` /
     `ROTATION_WITHIN_MIN_HOLD` otherwise.
   - **Trailing stop:** in exchange, one is armed at +100% and exits after a 60% giveback of the peak gain
     (`TRAILING_STOP_FROM_PEAK`). That was calibrated on the 10-30 395C bid path, which dipped 4.35 -> 3.15
     before running to 8.55. A 50%/40% trail sold it at 10:03 for +51%.
7. **Wording.** Member cards changed as follows:
   - Titles are "Model opened / closed a simulated position". The "reduced" title is only on journaled partial
     cards, never posted (see 3).
   - "Simulated fill" replaces "Actual fill".
   - "Planned contracts" and "Exit plan" are removed.
   - Campaign ids are hidden (`CF_CARD_SHOW_CAMPAIGN_ID`).
   - The footer is "Education only · Paper simulation · Options can lose 100% · Not investment advice."
   - The return % stays in the journal (`CF_CARD_SHOW_RETURN=false`) pending attorney review. When enabled it
     is labelled "Simulated option return … (paper fills, fees excluded)".

   **Not code:** rotate the webhook URLs, since they appear in screenshots. Moving them to AWS Secrets Manager is
   an ops decision; the bot reads them from `.env`.

**Stopped-process reconciliation.** On 2026-10-30 the process stopped at 14:16 ET. Seven 10-30 campaigns (and an
AAPL 10-21 put pending since 10-21) were left ACTIVE in the journal, still reserving capacity. At each new
session, `Router.reconcile_prior_sessions` handles them:
- An earlier session's unfilled proposal is cancelled.
- A campaign whose contract already expired is closed with `CONTRACT_EXPIRED_WHILE_UNMANAGED`
  (`RECONCILIATION_EXCEPTION`, no card).
- A live overnight carry is left to management.
- Check the Alpaca paper account for any exercised ITM contracts from that day.

**Tests:** `test_mag7_brief.py` (synthetic data) covers all of the above. The base-spec suites pin the new gates
off.

## Mag 7 Algo alerts Google Sheet (2026-11-02) — `campaign_flow/alerts_sheet.py`

Every campaign-flow card published to Discord gets one row in its own Google spreadsheet, separate from the
legacy "Trading Log". It uses the same service account (`GOOGLE_SERVICE_ACCOUNT_FILE`), so share the sheet with
that account's email as Editor.

**Settings:**
- `ALERTS_SHEET_ENABLED`, off by default.
- `ALERTS_SPREADSHEET_ID`.
- `ALERTS_SHEET_TAB`, default `Alerts`.
- `ALERTS_SHEET_FROM`, default `2026-11-03`. It is the first New York session written.

**Columns:**
- Date and time (ET), ticker.
- Alert: Opened or Closed. The sheet mirrors what was posted, so partial fills never appear (see 3 above).
- Contract, side, expiry and horizon.
- Simulated fill, contracts, contracts still held, and average entry.
- Exit rows only: simulated return and P&L, written as sheet formulas.
- Exit reason and the entry conviction (tier and score).
- The exact posted card text and the card ID.

Return, P&L and conviction stay off member cards (brief item 7). The sheet is an operator log.

**Durable:**
- The journal is the source of truth. `_card` stores the fill fields with the journaled card, under the
  `sheet` key, and never sends them to Discord.
- Each sync appends, oldest first, the published cards whose card ID is not already in the sheet.
- A sync runs at start-up and after every published card, in a daemon thread on a read-only sqlite connection.
  If a sync fails, it retries with backoff of up to 10 minutes.
- A Google outage or a restart therefore never loses or duplicates a row.
- To run a sync by hand: `python -m campaign_flow.alerts_sheet`.
- Covered by `test_alerts_sheet.py`.

**Legacy Trading Log off (2026-11-02):** the live `.env` now sets `SHEETS_ENABLED=false`. The legacy engine is
compute-only, so its SHADOW trades no longer go to the shared "Trading Log" (`Jakenew_Trades` tab). The rows
already there stay. Members' alerts are only in the Mag 7 Algo alerts sheet above. Set `SHEETS_ENABLED=true`
again if the legacy engine ever owns trading.
