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
| **8:35 → 2:55 PM** | Full-speed. The loop runs every **~5 seconds**, scoring over rolling **30s / 60s / 180s** windows. |
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
  visibility and collects live evidence on whether 0.50–0.54 events convert.
- **Items 3/6 — EOD attrition report.** `ATTRITION-REPORT` logs (+ Discord) the entry funnel
  **ACTIVE_EVENT(evaluated) → QUALIFIED_CAMPAIGN(no-veto) → ENTRY_READY → ENTERED**, plus hard-veto
  counts by family and near-miss counts by route — so we see exactly where candidates are lost.

**Deliberately NOT changed (per the brief):** the execution threshold (item 9), and the route-score
*math* — the audit's point that a route named `CROSS_STRIKE` doesn't actually *score* cross-strike
synchronization (routes share the same 7 ingredients — rank/notional/control/response/abn/persist/cheap
— with only different weights) is **documented as a real gap** but not rewired, because that would
change execution. That, plus the **forward-outcome replay** (score-bucket MFE/MAE by archetype + the
hard-veto false-positive study) is the evidence-based next phase — the near-miss stream + attrition
report are the instruments that make it possible.

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
- **T+1 OI confirmation (`analysis/oi_confirm.py`, `OI_CONFIRM_ENABLED`, default OFF).** Stores each
  campaign's fingerprint and a next-day classifier (NEW_POSITION_CONFIRMED / PARTIALLY / LIKELY_
  CLOSING_CHURN / INCONCLUSIVE) — whether today's volume became real open interest. Needs Schwab OI
  (currently off). Tests: `test_newspec.py` (14 checks). **18 test files green.**

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
| `STOP_LOSS_PCT` | 0.40 | hard stop-loss (risk backstop) |
| `ENTRY_CUTOFF_BUFFER_MIN` | 15 | no new entries within this many min of the flatten |
| `FAST_POLL_SECONDS` | 5 | loop cadence |
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
