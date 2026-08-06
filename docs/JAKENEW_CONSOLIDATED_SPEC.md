# IMMEDIATE OPERATIONAL FOLLOW-UP

Please coordinate with Satish regarding the Alpaca/AWS deployment and determine why the trade
spreadsheet is not updating with executed trades.

Confirm:

- whether Alpaca trade and fill events are reaching AWS;
- whether the AWS process is still running;
- whether the spreadsheet-writing service is authenticated;
- whether the correct spreadsheet and worksheet are configured;
- whether rows are failing to append;
- whether API errors are being logged;
- whether paper-account fills and exits are both being recorded;
- whether timestamps, symbols, quantities, entry prices, exit prices and P&L are being written correctly;
- whether the problem is in Alpaca event ingestion, AWS processing or spreadsheet output;
- and what monitoring or retry logic should be added so failures are visible immediately.

---

# JAKENEW — CONSOLIDATED DEVELOPER SPECIFICATION

### CURRENT V3 LOGIC + REQUIRED ARCHITECTURAL UPDATES + RECENT LIVE-EVIDENCE FINDINGS

> Formatting note: the section headings below are numbered **sequentially (1–55)**. The source
> document had every heading collapsed to "1.", which made the specification look duplicated /
> truncated; the content is unchanged, only the numbering has been corrected.

## PURPOSE

The current v3 attention-wave architecture is a meaningful improvement over the earlier scanner. It
is successfully identifying where Mag-7 attention is moving, which ticker is receiving fresh premium,
and which side appears to control current activity.

However, the latest AAPL, NVDA, TSLA, GOOGL, META, MSFT and AMZN examples show that the system is
still too dependent on: instantaneous attention; current Mag-7 rank; compact volume shocks; immediate
premium response; nearest-expiration activity; session-low distance; rapidly adapting Z-scores; and
attention decay as a proxy for campaign death.

The system must now evolve from an attention-wave detector into a **multi-expiration, multi-archetype,
stateful, probabilistic institutional campaign tracker.**

The primary object is no longer an isolated print, one contract, one score spike or one moment of rank
leadership. The primary object is a persistent institutional campaign with: a beginning; an
accumulation phase; a selected side; a selected time horizon; one or more participating strikes; a
premium-response structure; a funded inventory phase; possible consolidation; possible self-sustaining
expansion; maturity; distribution; and a genuine end.

The engine should continue using the strongest current components of v3, but the decision
architecture, lifecycle and research logging must expand substantially.

---

## 1. CORE PHILOSOPHY

Jakenew is not an unusual-volume scanner. It is not trying to identify the contract with the most
volume. It is not trying to wait until a directional move is obvious. It is trying to identify the
earliest statistically favorable moment when a genuine institutional options campaign may be beginning
while convexity remains favorably priced.

The fundamental question: **"Is a statistically abnormal institutional campaign beginning, building or
remaining intact while enough convexity remains to justify the risk?"** Every component should support
that question.

The market is adaptive, sophisticated and adversarial. The engine must therefore measure observable
behavior rather than tell unsupported stories about intent. Do not encode assumptions such as:
institutions are buying/selling; market makers are hedging; retail is being shaken out; a print is an
opening/closing trade; a call print is bullish; a put print is bearish.

The engine can only measure observable evidence: volume arrived; where it arrived; premium changed; IV
changed; spot changed; control changed; strikes synchronized; expirations agreed or conflicted;
response persisted; the campaign recovered; flow became more or less efficient; opposite-side evidence
strengthened; distribution evidence increased.

The system should speak probabilistically ("accumulation probability increased", "continuation
evidence improved", "distribution probability remains low", "current evidence is insufficient") and
avoid categorical claims the data cannot support.

## 2. PRESERVE THE STRONG PARTS OF CURRENT V3

Keep these as supporting layers rather than universal definitions: fresh-premium mass; ticker attention
share; call/put control; fast and slow EWMAs; impulse; robust Z-scores; velocity; acceleration; strike
relevance; option price response; event price; distribution probability; expected-value entry logic;
DTE-sensitive timing; one wave producing one primary entry; duplicate-order protection; bounded limit
orders; paper execution; 1% position sizing; EOD flattening; hard-risk stop; detailed logging;
out-of-sample validation; no move to real capital until the edge is proven.

They are useful components. They should not independently define campaign birth, health or death.

## 3. THE CURRENT SYSTEM'S BIGGEST STRENGTH

The attention-ranking engine has become good at detecting where the market's current activity is
moving (AAPL, META, TSLA, AMZN, GOOGL, NVDA, MSFT). The ranking layer is one of the strongest parts of
the system. The next problem is that the engine often confuses "this ticker is no longer receiving the
most current flow" with "the prior campaign is over." Those are not equivalent. Attention is fast;
campaign conviction must be stateful.

## 4. SEPARATE ATTENTION SCORE FROM CAMPAIGN CONFIDENCE

Add two explicitly different variables.

**AttentionScore** — "What is receiving the most current activity right now?" Fast, reactive, short
memory, useful for event discovery, can change sharply every poll (99→30 within minutes is legitimate).

**CampaignConfidence** — "How strong is the accumulated evidence that this campaign remains valid?"
Stateful, slower, persistent, based on cumulative evidence; should not collapse because another ticker
briefly becomes rank #1; should decay only when campaign-specific evidence deteriorates.

CampaignConfidence updates from: cumulative campaign evidence; archetype; premium-response structure;
delayed response; resilience; self-sustainability; control stability; strike leadership; strike
synchronization; expiration preference; expiry agreement/conflict; local value extension; remaining
convexity; distribution probability; opposite-side evidence; spot confirmation; IV structure; recovery
after adversity; actual premium progression; campaign stage.

A ticker may lose attention rank while its campaign remains healthy. That should not trigger an
automatic exit.

## 5. ADD PERSISTENT ATTENTION AND ATTENTION MEMORY

Current attention is too instantaneous. Add: **PersistentAttention** (integral of AttentionShare over
the campaign window); **RankDuration** (time in top 1/2/3); **AttentionDecayRate**; **AttentionStability**;
**ResidualAttention** (campaign memory from previously accumulated flow); **QualityAdjustedAttention** =
AttentionShare × AccumulationProbability × CampaignConfidence × RemainingConvexity.

Fresh premium does not simply disappear: Fresh Premium → Accumulated Inventory → Residual Campaign
Ownership → Expansion / Holding / Distribution → End. Maintain campaign memory after the original
buying burst has passed.

## 6. DO NOT REQUIRE UNIVERSAL RANK #1

Rank #1 + a lead over rank #2 may be useful for the fastest shock events but should not be a universal
hard requirement. A persistent rank-2 campaign may be much higher quality than a noisy rank-1 event.
Research/compare absolute rank, persistent rank, integrated attention share, quality-adjusted
attention, campaign confidence, rank duration, lead quality, response quality, remaining convexity and
distribution probability. Entry logic by archetype: SHOCK_ACCUMULATION may weight current rank
heavily; PERSISTENT_ACCUMULATION weights persistence/quality; FORWARD_POSITIONING weights
expiry-specific concentration; SELF_SUSTAINING_EXPANSION may make current rank largely irrelevant once
funded. Do not remove rank — stop treating rank #1 as universally synonymous with the best campaign.

## 7. MULTI-EXPIRATION SCANNING IS REQUIRED

Nearest-expiration only is insufficient. On a Wednesday a thesis may be expressed through Wednesday
0DTE, Friday 2DTE, both, or a later weekly (the NVDA Friday-call case). Scan multiple relevant
expirations simultaneously — minimum: current 0DTE (when available), nearest non-zero, current weekly
Friday, optionally the following weekly for research. Per ticker/side/expiration compute: ExpiryMass,
ExpiryAttentionShare, ExpiryControl, ExpiryVelocity/Acceleration/Impulse, ExpiryZScore,
ExpiryResponseEfficiency, ExpiryCampaignState/Confidence, ExpiryDistribution/Continuation Probability,
ExpiryRemainingConvexity, ExpiryMigration, ExpiryPersistentAttention. Classify: SAME_DAY_IMPULSE,
SAME_DAY_ACCUMULATION, FORWARD_POSITIONING, EXPIRY_MIGRATION, MULTI_EXPIRY_CONFIRMATION, EXPIRY_CONFLICT,
STALE_LONGER_DATED_FLOW, SAME_SIDE_MULTI_EXPIRY_CONTROL, NEAR_TERM_PUT_FORWARD_CALL,
NEAR_TERM_CALL_FORWARD_PUT, EXPIRY_CONTEST, FORWARD_SIDE_BUILDING. Do not force all expirations into one
ticker-level pool before understanding their structure.

## 8. CONTROL MUST BE HIERARCHICAL AND EXPIRY-AWARE

Ticker-level control is too coarse. Add the hierarchy: ContractControl → StrikeClusterControl →
ExpiryControl → TickerControl → Mag7AttentionControl. Example: NVDA 0DTE = PUT_CONTROL, Friday =
CALL_CONTROL, ticker aggregate = CONTESTED_ACROSS_EXPIRIES — materially different from calling NVDA
bullish/bearish. Preserve 0DTE/Friday/next-week call & put mass separately, then evaluate same-side
agreement, opposite-side conflict, expiration migration, immediate vs deferred thesis, whether
near-term flow may be hedging a later campaign, and whether one side is gaining control further out.

## 9. CAMPAIGN ARCHETYPES

The engine over-rewards compact shocks. Not every valid campaign begins the same way. Support at least:

- **A. SHOCK_ACCUMULATION** — dormant → compact abnormal burst → fast premium response → volume fades →
  premium keeps expanding. High compactness/dominant-bar share, short burst, high initial abnormality,
  rapid response, fast activation.
- **B. PERSISTENT_ACCUMULATION** — no single overwhelming bar → repeated moderate participation →
  premium bases → higher lows → survives pauses → premium accelerates later. Lower single-bar
  dominance, stronger persistence, delayed response, rising resilience.
- **C. FORWARD_POSITIONING** — limited immediate spot movement → meaningful later-expiration
  participation → premium firm/gradually improving → later expiry receives increasing attention →
  time-horizon preference visible.
- **D. SELF_SUSTAINING_ACCUMULATION / EXPANSION** — large early accumulation near value → funded →
  volume declines → premium keeps rising → spot/IV still confirms → no meaningful distribution (the
  AAPL example). A falling volume rate after the build is not automatically decay.
- **E. SHAKEOUT_AND_RECOVERY** — abnormal participation → temporary drawdown/volatility → control
  intact → participation remains → premium recovers → expansion. Measure the observable recovery
  structure; do not encode a "stopping out retail" narrative.
- **F. STAIR_STEP_ACCUMULATION** — moderate participation → base → step higher → pause → another cluster
  → another step.
- **G. IMPULSE_REPRICING** — premium reprices before peak volume arrives → additional participation
  follows → trend strengthens.
- **H. CROSS_EXPIRY_ACCUMULATION** — same side develops across multiple expirations; near-term and
  forward horizons agree.
- **I. STRIKE_MIGRATION** — leadership moves across adjacent strikes as spot changes.
- **J. DISTRIBUTION / EXIT CAMPAIGN** — large volume after substantial extension → response efficiency
  collapses → premium stalls/gives back → IV weakens → opposite-side activity may strengthen.

Classify the developing archetype first, then apply archetype-specific expectations. Do not force every
winning campaign to resemble a compact TSLA shock.

## 10. CAMPAIGN LIFECYCLE MUST BE EXPANDED

DORMANT → FORMING → ACTIVE → MATURE → DECAYING → ENDED is too coarse. Recommended:

DORMANT → WATCH → AWAKENING → FORMING → BUILDING → FUNDED → EXPANDING → STABILIZING → SELF_SUSTAINING →
REACCELERATING → MATURE → DISTRIBUTING → ENDED.

Additional transition states: FAILED_FORMATION, HEALTHY_PULLBACK, SHAKEOUT_RECOVERY, EXPIRY_MIGRATION,
STRIKE_MIGRATION, CONTROL_CONTEST, ROTATING, THESIS_INVALIDATED.

Distinguish campaign birth; active inventory building; already funded; volume cooling; premium
stabilization; healthy consolidation; self-sustaining expansion; reacceleration; genuine deterioration;
distribution; actual end. A falling Z-score or lower attention score cannot independently move the
campaign to DECAYING — a major burst naturally becomes less abnormal with time; that is not failure.

## 11. ADD WATCH AND BUILDING STATES BEFORE ENTRY

The gap between "nothing" and "ENTER" is too large. Add internal states:

- **WATCH** — first abnormal activity; early fresh-premium velocity; one/two unusual prints; still near
  local value; no strong distribution evidence.
- **BUILDING** — repeated participation; attention rising; control emerging; strike leadership forming;
  premium firming/basing/recovering; still below final entry confidence.
- **ACCUMULATION / ENTRY ELIGIBLE** — expected asymmetric value positive; enough evidence to act;
  remaining convexity attractive.

Track time from: first abnormal print; first sustained accumulation; first meaningful control; first
top-3 rank; first top-1 rank; entry-eligible moment; actual alert; actual fill. This reveals confidence
lag.

## 12. DETECTION LATENCY MUST BECOME A PRIMARY METRIC

For every campaign log: FirstAbnormalPrintTime, FirstSustainedAccumulationTime,
FirstControlEmergenceTime, FirstCampaignWatchTime, FirstBuildingTime, FirstEntryEligibleTime, AlertTime,
FillTime. Then compute: DetectionLatency = AlertTime − FirstSustainedAccumulationTime; DecisionLatency
= AlertTime − FirstEntryEligibleTime; ExecutionLatency = FillTime − AlertTime; PremiumDrift =
AlertPremium / InitialAccumulationPremium; ConvexityConsumedBeforeAlert (fraction of eventual MFE
realized before entry); MissedAsymmetry (early-eligible vs executed price). The optimization target is
not "fire earlier at any cost" — it is **reduce detection latency while preserving or improving
out-of-sample precision and expected value.**

## 13. ADD EARLY ACCUMULATION SCORE

Create a separate early-phase score rather than simply lowering the full confirmation threshold.
EarlyAccumulationScore should incorporate: fresh-premium velocity; initial participation proof; low
current extension; local-value proximity; repeated prints; rising attention; emerging control;
favorable volume geometry; positive/firming/recovering premium response; absence of strong distribution
evidence; strike synchronization; expiry-specific concentration; remaining convexity; campaign
resilience; early response efficiency. Optimize it for the earliest favorable phase; it should not be
identical to mature CampaignConfidence.

## 14. DTE-SENSITIVE ENTRY ROUTES

Timing is central. **0DTE**: speed matters; short confirmation windows; convexity disappears rapidly;
early entries with controlled uncertainty may dominate late high-certainty entries. **1DTE**: more
confirmation acceptable; longer build tolerated; delayed response more acceptable. **2DTE+**: forward
positioning and persistent accumulation more relevant; confirmation can rely more on persistence,
cross-expiry structure and gradual premium response.

Support at least two early entry routes. **FAST EARLY ROUTE** when abnormality is exceptional,
participation proof meaningful, strike near local value, volume shape favorable, control emerging, no
prior extension, premium firming/recovering, distribution low, convexity high (0DTE: entry within
~30–90s). **PERSISTENT EARLY ROUTE** when no single giant shock, repeated moderate participation,
premium basing / higher lows, control survives pauses, delayed positive response developing, resilience
rising, contract favorably priced, breakout has not consumed the opportunity. Do not require spot
confirmation so strong that the move must already be obvious before entry.

## 15. IMMEDIATE PREMIUM RESPONSE MUST NOT BE MANDATORY

Treating rapid premium expansion as the canonical accumulation proof misses valid campaigns involving
consolidation, temporary adverse movement, volatility, two-sided discovery, delayed expansion, shakeout
and recovery, and persistent base formation. Add response windows: 15/30/60/90/120/180/300s (and longer
for later DTE). Track: ImmediateResponse, DelayedResponse, MaximumFavorableResponse,
MaximumAdverseResponse, RecoveryTime, RecoveryFraction, AreaUnderPremiumResponseCurve,
HigherLowProgression, ResponseAfterConsolidation, ResponseAfterReacceleration, PostVolumeResponse.
Classify: IMMEDIATE_POSITIVE_RESPONSE, DELAYED_POSITIVE_RESPONSE, CONSTRUCTIVE_CONSOLIDATION,
SHAKEOUT_AND_RECOVERY, FAILED_RESPONSE, NEGATIVE_RESPONSE, DISTRIBUTION_RESPONSE. A temporary pullback
must not automatically invalidate the campaign when control remains, participation remains, recovery
occurs, higher lows form, IV firm/recovers, spot improves, distribution stays low.

## 16. ADD CAMPAIGN RESILIENCE

CampaignResilience answers "Does the campaign survive adversity?" Inputs: control retained through
pullback; attention retained; abnormal-participation survival; recovery speed; % of drawdown recovered;
reacceleration after the pause; higher low relative to event low; adjacent-strike participation intact;
IV firm/recovering; spot recovering; premium reclaiming event VWAP/value; absence of a coherent
opposite-side replacement. Conceptually: PersistenceDuringAdversity × RecoverySpeed × RecoveryFraction
× ControlRetention × Reacceleration × HigherLowQuality − FailureDepth − FailureDuration −
OppositeSideEvidence. Critical for distinguishing a healthy consolidation / temporary shakeout from a
genuine failed event.

## 17. ADD CAMPAIGN SELF-SUSTAINABILITY

CampaignSelfSustainability answers "Can premium continue progressing after the major buying burst has
faded?" Strong: initial accumulation strong AND recent volume below peak AND premium velocity still
positive AND spot/IV still confirms AND higher lows intact AND distribution low. Weak: volume fades AND
premium immediately fails AND control disappears AND opposite-side evidence rises. Key positive
relationship: VolumeVelocity falling while PremiumVelocity remains positive and spot/IV constructive →
transition BUILDING → FUNDED → SELF_SUSTAINING → EXPANDING (not ACTIVE → DECAYING). Distinguish "volume
disappeared because the campaign failed" from "volume declined because the campaign was already funded."

## 18. STABILIZATION IS NOT EXHAUSTION

Recent alerts repeatedly exited after 1–3 minutes for STATISTICAL_EXHAUSTION even though the ticker
still retained call control, remained relevant, faced no strong opposite-side campaign, and premium had
not materially failed — current attention had merely cooled. Distinguish three conditions:
**A. ROTATION** (a stronger external campaign emerges AND the current one materially weakens);
**B. TRUE EXHAUSTION** (loss of premium progression, control, persistence, resilience, IV/spot support
— without recovery); **C. STABILIZATION** (current flow cools BUT the prior campaign remains
structurally intact). Add STABILIZING and HEALTHY_PULLBACK states. Do not exit solely because the score
fell from 99 to 30.

## 19. USE SCORE DERIVATIVES

Do not evaluate only the current score. Track: ScoreVelocity, ScoreAcceleration, AttentionVelocity,
AttentionAcceleration, PremiumVelocity, PremiumAcceleration, ControlVelocity,
DistributionProbabilityVelocity, CampaignConfidenceVelocity. Example: Score 40 / velocity −4 /
acceleration +2 = still falling but decelerating (possible stabilization) vs Score 40 / velocity −12 /
acceleration −9 = evidence collapsing faster. CampaignConfidence should react to the direction and
curvature of evidence, not only its level.

## 20. RESPONSE EFFICIENCY MUST BE PHASE-AWARE

Add: Efficiency15s/30s/60s/90s/120s/180s/5m, PeakEfficiency, DelayedEfficiency, EfficiencyRecovery,
EfficiencyDecay, PostVolumeEfficiency. PostVolumeEfficiency ≈ premium progress after the primary
accumulation burst / remaining incremental volume — AAPL-style self-sustaining campaigns should score
highly. Low immediate efficiency should not automatically imply distribution when delayed efficiency
later improves.

## 21. "DISTANCE FROM SESSION LOW" IS TOO CRUDE

`mark <= 1.5 × session low` is vulnerable to bad opening prints, stale quotes, illiquid lows, wide
spreads, structural extension despite apparent session-low proximity, different value processes by
expiration, and later-forming campaigns whose correct reference is local not session-wide. Track:
session low; valid quoted low; local pre-event value; quiet-period median; event low; event VWAP;
campaign-start premium; campaign-value estimate; current distance from campaign value; extension from
local base; peak extension; peak giveback; spread-adjusted low; liquidity-qualified low. Prefer
CurrentExtension = CurrentMark / LocalPreEventValue; EventExtension = EventPeak / LocalPreEventValue;
CampaignExtension = CurrentMark / CampaignStartPremium. The session-low multiple may remain as context,
not the sole cheapness test.

## 22. STRIKE LEADERSHIP AND MIGRATION

Adjacent strikes can have different roles. Track: leading strike; confirming strikes; lagging strikes;
strike activation time; strike response efficiency; strike contribution; strike-specific control;
strike-specific campaign state; ATM migration; leadership transfer; cross-strike synchronization; strike
progression relative to spot. Patterns: ATM leading OTM following; OTM anticipation then ATM migration;
adjacent-strike staircase; leadership migrating with spot; one strike independently dominant; broad
strike ladder; false chain aggregation; distributed ticker-level campaign. A chain remains "a
synchronized shape, not a sum of mediocre strikes" — but synchronization does not require identical
timing or size.

## 23. AMZN DISTRIBUTED-STRIKE BLIND SPOT

The AMZN screenshots showed substantial call-side volume distributed across a ladder (~237.5, 240,
242.5, 245, 247.5, 250, 252.5, 255, 257.5; 250 & 255 especially active) — not isolated to one contract.
Separate the **ticker-level question** ("is capital concentrating in AMZN calls across the strike
surface?") from the **contract-selection question** ("which strike best expresses the campaign?").
Answer the ticker-level question first; do not reject a strong ticker-wide campaign merely because no
single strike satisfies a narrow dominant-strike pattern. Add surface measures: LadderMass,
LadderParticipationBreadth, StrikeConcentration, StrikeDispersion, WeightedStrikeCenter, StrikeMomentum,
StrikeSynchronization, BreadthAdjustedCampaignStrength, SurfaceDirectionality, SurfaceResponseQuality.
Classify: SINGLE_STRIKE_DOMINANT, TWO_STRIKE_COORDINATED, ADJACENT_STRIKE_LADDER,
BROAD_SURFACE_ACCUMULATION, DISTRIBUTED_BACKGROUND, STALE_SURFACE_VOLUME, POSSIBLE_SPREAD_COMPLEX. Broad
participation can represent a meaningful ticker-level campaign.

## 24. CHAIN THRESHOLDS REQUIRE RESEARCH

The 1.5× chain multiplier may be too permissive for a precision-first engine. Research starting points
(not permanent truths): **single-strike dominant** ≈ 1,000–1,250 fresh contracts / ≈ $100k–$150k fresh
premium; selected contract independently proves the event. **Coordinated chain** ≈ 2,500–3,000 combined
fresh contracts / ≈ $250k–$300k combined premium; ≥2 meaningful independent strikes; selected contract
meets an independent material floor; synchronized/logically-progressive timing; compatible premium
response; no stale opening-volume combination. Thresholds must vary by ticker, DTE, time of day, option
price, typical liquidity, event/earnings regime, strike distance, spread width. A coordinated chain
should face a materially higher evidentiary burden than a single independently strong contract.

## 25. INITIAL PARTICIPATION VERSUS ONGOING PARTICIPATION

Do not require constant high volume after entry. Differentiate InitialParticipationProof (enough
activity to establish a campaign) from OngoingParticipationRequirement (can be much lower once funded).
Test participation over 15s/30s/60s/rolling-3min/archetype-specific windows. This resolves the apparent
contradiction: entry requires meaningful proof; a strong campaign may later continue while volume fades.

## 26. EXPIRATION MIGRATION

Track how capital moves across expirations (e.g. 10:00 0DTE 95%/Fri 5% → 11:00 70%/30% → 12:00
40%/60%). Add: ExpiryShareSlope, NearToForwardMigrationRate, SameSideMigration, OppositeSideMigration,
ExpiryLeadershipDuration, DeferredCampaignStrength, TimeHorizonPreference. Interpretations: same-day
urgency; forward positioning; near-term hedge against longer-term exposure; decaying immediate thesis;
strengthening deferred thesis. Do not collapse these into one ticker control variable.

## 27. EARNINGS AND EVENT REGIME

AMZN's after-hours move highlights an event-regime blind spot. Earnings sessions differ: IV elevated;
premiums expensive; flow distributed across strikes; spreads/combinations more common; positions may be
established well before the event; same-day fresh volume less informative; directional exposure embedded
in complex structures; ticker-level evidence may matter more than one contract. Add an EventRegime
layer: NORMAL_SESSION, PRE_EARNINGS, EARNINGS_DAY, POST_EARNINGS, MACRO_EVENT, INDEX_REBALANCE,
UNKNOWN_EVENT. Research whether thresholds should vary by regime. For missed AMZN-style moves the engine
should answer: was abnormal ticker-level fresh premium present; when did it begin; which strikes /
expirations contributed; concentrated or distributed; did AMZN rank top 1/2/3; was it rejected by
strike-selection logic; was IV too elevated; did the flow occur earlier in the week; was the campaign
already funded; was the move genuinely invisible. Do not assume an after-hours move proves same-day
informed buying — use the miss as a diagnostic.

## 28. CAMPAIGN REPLAY

Campaign replay should be a next major research tool: for every ticker, reconstruct the campaign minute
by minute / poll by poll. Show side by side: engine state; attention score; campaign confidence; option
premium; option volume; IV; underlying price; control; strike leadership; expiry preference;
distribution probability; continuation probability; decision reason; actual alerts; actual fills;
eventual MFE and MAE. If the replay and chart do not tell the same story, the model's failure becomes
identifiable.

## 29. CURRENT EXIT LOGIC IS THE LARGEST WEAKNESS

Many recent exits fired after ~1–6 minutes for STATISTICAL_EXHAUSTION / ROTATION / CONTROL_TRANSFER
while the ticker still retained the original side control, no clear opposite-side campaign had replaced
it, premium had not materially failed, the score had simply fallen from an extreme, the ticker remained
top 3–5, and the campaign may have been stabilizing. The exit layer is too reactive to current
attention; it must be much more campaign-specific.

## 30. ROTATION MUST NOT BE SUFFICIENT BY ITSELF

A new ticker becoming rank #1 is not enough to close a healthy existing campaign. Require:
NewCampaignStronger AND CurrentCampaignMateriallyDeteriorating AND CurrentPremiumStructureWeakening
AND/OR OppositeSideCampaignStrengthening. A healthy campaign should not be abandoned merely because
another ticker briefly produces a larger print. Trust rotation more than statistical exhaustion only
when rotation is persistent and the current campaign is genuinely weakening.

## 31. STATISTICAL EXHAUSTION MUST BE REDEFINED

Current exhaustion is too sensitive to falling Z-score, lower velocity, declining attention share, and
lower rank — all natural after a successful accumulation burst. True exhaustion should require multiple
coherent signs: campaign confidence materially declining; premium failing to progress; recovery
attempts failing; resilience collapsing; control weakening/transferring; IV rolling over; spot no
longer confirming; distribution probability rising; no higher-low structure; no reacceleration;
opposite-side evidence strengthening; expiry support weakening; strike support dissolving. Do not define
exhaustion as "less fresh flow than before."

## 32. ADD STABILIZING AND ACTIVE_AGAIN

Recommended sequences: ACTIVE → STABILIZING → ACTIVE_AGAIN, or ACTIVE → STABILIZING → SELF_SUSTAINING,
or ACTIVE → STABILIZING → DISTRIBUTING. Stabilizing should require observation before exit. Ask: did the
decline in attention slow; did premium hold its base; did control remain; did IV remain firm; did spot
remain constructive; did the campaign preserve a higher low; did a second burst emerge; did opposite-
side evidence remain weak. This should eliminate many one-minute scratch exits.

## 33. EXIT DISTRIBUTION FINGERPRINTS

Valid distribution evidence: equal/greater contract volume arriving at much higher premium; premium
extended many multiples from campaign value; response efficiency collapsing; large notional with little
price progress; repeated volume failing to make new highs; heavy ATM/OTM call volume near highs after a
run; premium giveback increasing; IV flattening/declining; spot failing to confirm; coherent
opposite-side clustering; persistent control transfer; volume shifting from earlier profitable strikes
into late chasing strikes; peak-volume timing moving late. Principle: 1,000 @ $1.00 and 1,000 @ $6.00
are economically different — later volume at significantly higher premium deserves more skepticism.

## 34. WATCH/REDUCE MAY BE TOO EAGER

A 15% premium giveback can be normal in 0DTE. WATCH/REDUCE should incorporate campaign stage,
resilience, self-sustainability, MFE already achieved, premium higher-low structure, IV structure, spot
structure, whether control remains, whether the giveback is statistically normal for the archetype/DTE,
and whether distribution evidence is coherent across multiple dimensions. Do not trim merely because a
single heuristic threshold crossed, the premium gave back 15%, or current attention dropped.

## 35. PROFIT TARGETS CONFLICT WITH THE STATED OBJECTIVE

Selling half at +60% and the rest at +150% mechanically prevents participation in +300/+500/+1,000%+
campaigns. Research the profit-management layer separately: partial profit at an initial objective;
retain a runner; runner remains while CampaignConfidence is intact; manage the runner by campaign stage,
distribution evidence, structural target, strike target, underlying support/resistance, expiry-aware
trailing logic, IV behavior, opposite-side emergence. Do not change live production blindly — but
acknowledge the contradiction: the system cannot target extraordinary convexity while guaranteeing full
liquidation at +150%.

## 36. THE HARD STOP IS A BACKSTOP, NOT AN ENTRY EDGE

The −40% stop can remain a paper-risk backstop. Track separately: thesis exit; control-transfer exit;
campaign-distribution exit; liquidity exit; hard-risk stop; execution slippage; EOD flatten. Analyze:
MAE before eventual winner; MAE by archetype/DTE; MAE before delayed expansion; stop-out-then-recovery
frequency; stop-out during healthy shakeouts; typical premium volatility by contract price; spread
effects. The strategic goal is better campaign recognition, not repeated reliance on the hard stop.

## 37. ALERT FREQUENCY AND CAMPAIGN DUPLICATION

Preference: ≈ one call campaign alert per ticker per day; one put campaign alert per ticker per day;
very few high-quality alerts; no repeated alerts for residual activity inside the same campaign.
Implement one primary CALL and one primary PUT campaign per ticker per day unless an objectively
distinct second campaign forms after the first has completely ended (prior state = ENDED; meaningful
refractory completed; new event baseline; new accumulation structure; new abnormality vs post-campaign
activity; renewed participation proof; renewed value; not residual/continuation). Operational default
strict: MAX_PRIMARY_CALL_ALERTS_PER_TICKER_PER_DAY = 1; MAX_PRIMARY_PUT_ALERTS_PER_TICKER_PER_DAY = 1.
Research mode still tracks later campaigns and logs whether they would have qualified. No repeated
same-side alerts from score re-crossing, rank returning, residual volume, a minor reacceleration inside
the same wave, or contract reselection inside the same campaign.

## 38. ONE POSITION AT A TIME SHOULD NOT LIMIT RESEARCH

Execution can remain one position at a time for safety, but research tracking must remain independent:
best campaign; second-best; all active campaigns; all rejected campaigns; missed campaigns due to
capacity; hypothetical results if capacity existed; side and expiration conflicts. Execution constraints
should not erase model visibility.

## 39. MORNING BIAS IS A PRIOR, NOT A VERDICT

Morning bias can influence the starting probability but must update rapidly. Track: BIAS_ALIGNED,
BIAS_CHALLENGED, BIAS_INVALIDATED, BIAS_REVERSED. A bearish morning bias can be invalidated by coherent
call accumulation (and vice-versa). Do not let prior bias overpower current campaign evidence.

## 40. BAYESIAN TERMINOLOGY MUST BE HONEST

Calling the system Bayesian is only valid if priors are empirically estimated; feature likelihood
ratios measured; posteriors calibrated; outcomes labeled; Brier score and log loss measured; reliability
curves produced; posterior deciles correspond to realized continuation rates; calibration stable
out-of-sample. Until that exists, use honest terminology: Bayesian-inspired score / heuristic posterior
proxy / probabilistic campaign score. A 0.55 threshold has no rigorous probabilistic meaning without
demonstrated calibration. Required validation: calibration plot; Brier; log loss; posterior deciles vs
realized continuation; stability by ticker/DTE/time-of-day/archetype; out-of-sample stability.

## 41. EWMA AND Z-SCORES ARE FEATURES, NOT DEFINITIONS

Keep fast/slow EWMA, impulse, robust Z, median/MAD, velocity, acceleration. Add: time-of-day
percentiles; contract-relative percentiles; ticker-relative percentiles; empirical quantile ranks;
frozen event baselines; event-conditioned distributions; campaign survival curves. A persistent
campaign will raise its adaptive baseline — that should not erase the campaign. Use frozen
campaign-start references for campaign-health evaluation; adaptive baselines remain useful for
discovering new events.

## 42. CAMPAIGN DIMENSIONS MUST BE STORED SEPARATELY

Maintain independent dimensions before combining them into a verdict: Attention; Persistent Attention;
Control; Abnormality; Structure (shock/persistent/forward/self-sustaining/distributed/mixed);
Efficiency; Persistence; Resilience; Self-Sustainability; Strike Leadership; Expiry Preference;
Freshness; Remaining Convexity; Distribution Probability; Continuation Probability; Campaign Confidence.
Do not compress these too early — store and inspect them independently.

## 43. NEW CAMPAIGN VERDICT

The engine should ask, not "Did volume shock, premium rise and ticker rank #1?", but: (1) what archetype
is emerging; (2) which expiration expresses it; (3) which strike/surface is leading; (4) is
participation initial, persistent or already funded; (5) is premium responding immediately, after
consolidation, or not at all; (6) did the campaign survive adversity; (7) is premium becoming
self-sustaining after volume fades; (8) is current volume accumulation, continuation, distribution or
stale; (9) how much convexity remains; (10) is the horizon same-day or forward; (11) is control
consistent across strikes and expirations; (12) what evidence would genuinely prove the campaign ended;
(13) is current expected value positive at this exact moment. Conceptual entry value:
ExpectedEntryValue = P(continuation) × RemainingConvexity × CampaignQuality − P(false or distribution) ×
ExpectedLoss − ExecutionCost − DetectionLatencyPenalty. The optimum is the earliest moment expected
asymmetric value becomes sufficiently positive — not maximum certainty.

## 44. REQUIRED RESEARCH LOGGING

For every candidate (including rejected ones) archive: campaign_id; ticker; side; expiration; DTE;
strike; moneyness; event start; first abnormal print; first sustained accumulation; first control
emergence; first WATCH; first BUILDING; first entry-eligible moment; alert time; fill time; archetype;
lifecycle state; event volume by interval; premium notional; delta-adjusted notional; IV; option
premium; underlying price; bid/mid/ask; spread; quote age; estimated aggressor side; ticker attention
rank/share; expiry attention rank/share; persistent attention; rank duration; control by strike; control
by expiry; event price; local pre-event value; campaign-start premium; session low; valid quoted low;
event low; event VWAP; current/peak extension; peak giveback; response efficiency by horizon; delayed
response; maximum adverse response; recovery time/fraction; resilience; self-sustainability; strike
synchronization/leadership/migration; expiry migration; distribution probability; continuation
probability; campaign confidence; remaining convexity; detection latency; premium drift before alert;
MFE; MAE; realized outcome after 15s/30s/1m/2m/3m/5m/10m/20m/60m/EOD; rejection reason; exit reason;
eventual best contract; whether capacity prevented execution; hypothetical result if executed; whether
another expiration/strike was superior. Without this archive, development stays dependent on selected
screenshots and hindsight.

## 45. CAMPAIGN REPLAY OUTPUT

Create a replay report per detected or missed campaign with: TIME, TICKER, SIDE, EXPIRY, LEADING STRIKE,
ATTENTION SCORE, PERSISTENT ATTENTION, CAMPAIGN CONFIDENCE, CONTROL, ARCHETYPE, LIFECYCLE STATE, PREMIUM,
FRESH VOLUME, IV, SPOT, DISTRIBUTION PROBABILITY, CONTINUATION PROBABILITY, REMAINING CONVEXITY, ENGINE
ACTION, REASON — allowing direct comparison between model interpretation, option chart, underlying
chart, actual flow and eventual outcome.

## 46. DIAGNOSTIC QUESTIONS FOR MISSED EVENTS

For every missed winner (AMZN, the earlier NVDA setup) produce an automatic diagnostic: did the ticker
ever qualify at the aggregate level; did any expiration qualify; did any strike qualify; was evidence
distributed across too many strikes; did rank #1 block a rank-2/3 campaign; did the nearest-expiration
limitation hide a forward campaign; did the session-low gate reject a valid local-value setup; did the
engine wait for too much premium confirmation; did control fail to cross a fixed threshold; did the
Bayesian proxy fail; did the event occur before the active scan window; was it misclassified as stale
opening volume; was it categorized as distribution; did one-position capacity block execution; was it
actually undetectable with available data; did the system identify it but alert late. This turns misses
into reproducible research.

## 47. INTERPRETATION OF THE RECENT NVDA EXAMPLES

Morning example: meaningful volume developed ~9:32–9:46 ET; premiums remained attractive; the volume
shape was progressive not one isolated print; the contracts later expanded materially; the engine did
not produce the desired early alert — suggesting confidence lag, over-reliance on rank #1 / compact
shock, insufficient persistent-accumulation logic, slow control confirmation, insufficient early
accumulation scoring. Later example: the engine DID alert NVDA 195C ~3:08 ET at an attractive price, but
the major flow began before final conviction. Separately log when evidence began, when the campaign
became entry-eligible, and when it alerted. A reasonable entry price does not eliminate detection latency.

## 48. INTERPRETATION OF THE RECENT AAPL EXAMPLES

The AAPL examples demonstrate self-sustaining behavior: large initial accumulation near attractive
premium; volume later declined; premium continued appreciating; the move no longer required continuous
aggressive flow. Model this as BUILDING → FUNDED → SELF_SUSTAINING → EXPANDING, not ACTIVE →
STATISTICAL_EXHAUSTION. The key positive feature is not constant volume — it is continued premium
progress after the buying burst fades.

## 49. INTERPRETATION OF THE TSLA EXAMPLES

TSLA provides examples of compact shock accumulation; adjacent-strike participation; premium expansion
following concentrated flow; later volume potentially appearing at significantly higher premium; and a
possible transition from accumulation into distribution/maturity. TSLA supports retaining a
shock-accumulation archetype — it does not justify forcing every campaign into that archetype.

## 50. INTERPRETATION OF CALL-SIDE VOLUME

Large call volume is not automatically bullish (opening/closing longs, call selling, covered calls,
spreads, rolls, hedging, profit-taking, liquidity provision are all possible). Use quote location;
premium response; IV response; spot response; strike relationships; expiration structure; control
persistence; opposite-side evidence; event maturity; distribution probability. Replace "Buying the
convexity" with measured language ("CALL campaign detected" / "Bullish call-side accumulation
probability elevated") unless aggressor and behavioral evidence strongly support it.

## 51. PROPOSED MODULE ARCHITECTURE

- `analysis/mass.py` — contract mass; strike relevance; fresh premium; expiry-specific mass;
  ticker-level mass; delta-adjusted notional.
- `analysis/flow.py` — volume intervals; aggressor estimation; quote location; fresh-volume tracking;
  opening-volume handling.
- `analysis/control.py` — ContractControl; StrikeClusterControl; ExpiryControl; TickerControl;
  cross-expiry conflict.
- `analysis/attention.py` — current attention; persistent attention; rank duration; quality-adjusted
  attention; attention memory.
- `analysis/archetype.py` — the archetypes in §9.
- `analysis/waves.py` (or `campaign_state.py`) — persistent campaign objects; IDs; expanded lifecycle;
  same-side alert suppression; campaign memory; true ending logic.
- `analysis/response.py` — multi-horizon response; response efficiency; delayed response; recovery;
  response classification.
- `analysis/resilience.py` — adversity survival; recovery speed/fraction; control retention;
  reacceleration.
- `analysis/sustainability.py` — post-volume premium continuation; funded-campaign detection;
  self-sustaining expansion.
- `analysis/expiry.py` — expiration preference; migration; cross-expiry agreement; forward positioning.
- `analysis/strikes.py` — strike leadership; chain structure; strike ladder; surface aggregation;
  strike migration.
- `analysis/distribution.py` — phase-aware distribution probability; high-premium exit flow; efficiency
  collapse; late-volume skepticism.
- `analysis/campaign.py` — campaign confidence; continuation probability; expected value; entry
  eligibility; evidence narrative.
- `analysis/replay.py` — minute-by-minute reconstruction; missed-event diagnostics; alert-vs-chart
  comparison.
- `engine.py` — orchestration; candidate ranking; independent campaign tracking; capacity decisions.
- `execution.py` — bounded limits; duplicate protection; one-position execution; campaign-aware position
  management; runner research.
- `backtest.py` — replay real option data; multi-expiration support; archetype labels; out-of-sample
  validation; calibration; latency metrics; MAE/MFE analysis.

## 52. PROPOSED ALERT CONTENT

**ENTRY ALERT** — ticker; side; strike; expiration; DTE; archetype; lifecycle state; entry price; local
campaign value; current extension; current attention; persistent attention; campaign confidence; control
by expiration; leading strike; confirming strikes; expiry preference; response type; resilience;
self-sustainability; distribution probability; continuation probability; remaining convexity; detection
latency; concise thesis; exact risk plan. (Example: ENTER NVDA CALL 195 7/31 — Archetype
PERSISTENT_ACCUMULATION, State BUILDING, Friday forward campaign, leading 195C / confirming 192.5C,
current attention 58%, persistent attention elevated 10m, campaign confidence 0.72 proxy, response
DELAYED_POSITIVE_RESPONSE, resilience rising, distribution low, extension 1.18x, detection latency
2m10s.)

**EXIT ALERT** — exit price; P&L; hold time; lifecycle state at exit; campaign confidence before/after;
exact evidence of failure; opposite-side evidence; distribution evidence; and whether the exit was
thesis death / distribution / control transfer / hard stop / liquidity / objective / EOD. Do not use
"statistical exhaustion" unless genuine multi-variable exhaustion is present.

## 53. RESEARCH PRIORITIES

1. **Fix premature exits** — separate cooling from exhaustion; add campaign memory; add STABILIZING;
   require campaign-specific deterioration; stop exiting merely because rank/attention falls.
2. **Reduce detection latency** — WATCH; BUILDING; EarlyAccumulationScore; entry-eligible timestamp;
   latency logging; fast and persistent early routes.
3. **Add multi-expiration tracking** — 0DTE; nearest non-zero; Friday; following weekly research; expiry
   control and migration.
4. **Add multi-archetype classification** — shock; persistent; forward; self-sustaining; shakeout and
   recovery; stair-step.
5. **Add distributed strike-surface aggregation** — ticker-level campaign first; representative contract
   second; AMZN ladder analysis.
6. **Build campaign replay and candidate archive.**
7. **Revalidate profit-taking and hard-stop logic.**
8. **Calibrate probabilistic outputs honestly.**

## 54. VALIDATION REQUIREMENTS

No threshold should be accepted because it fits one screenshot. Validate across: multiple weeks;
multiple tickers; multiple DTEs; opening; midday; late-day; earnings; non-earnings; bullish; bearish;
shock; persistent; forward; self-sustaining; high-IV; low-IV. Report: entries/day; win rate; average
return; median return; expectancy; MFE; MAE; detection latency; premium drift; false-positive rate;
missed-winner rate; premature-exit rate; stop-out-then-recovery rate; results by archetype/DTE/ticker/
time-of-day/event-regime; capacity-missed results; calibration metrics. The most recent tuned period
cannot be treated as proof — out-of-sample stability is required.

## 55. FINAL OBJECTIVE

Jakenew should identify the earliest statistically favorable phase when: capital is concentrating; a
side is becoming behaviorally dominant; the chosen expiration reveals the campaign's time horizon; the
strike or strike surface is coherent; participation is initial, persistent or already funded; premium is
favorably priced relative to local campaign value; response is immediate, delayed or constructively
consolidating; the campaign survives adversity; self-sustaining expansion is possible; distribution
evidence remains low; enough convexity remains; and expected asymmetric value exceeds false-signal risk.

The engine must then hold the campaign while its structure remains healthy, and exit when premium
structure genuinely fails; control genuinely transfers; distribution becomes coherent; opposite-side
evidence becomes dominant; resilience collapses; the campaign reaches a tested structural objective;
hard-risk containment is required; or EOD rules require flattening.

Do not force every opportunity to resemble a compact 0DTE shock. Institutional commitment may appear
through immediate same-day shocks; persistent accumulation; delayed expansion; shakeout and recovery;
self-sustaining appreciation after volume fades; adjacent-strike progression; broad strike-surface
accumulation; expiry migration; forward positioning; cross-expiry confirmation.

The current attention engine is useful. The next version must add campaign memory, archetype awareness,
multi-expiration structure, strike-surface aggregation, early detection, resilience, self-sustainability
and materially stronger exit logic.

**That is the required direction for the next Jakenew architecture.**
