"""
Attention-wave state machine (spec §9-17) — one wave = one entry.

A single institutional attention campaign is one persistent Wave object per (ticker, side) with
a unique wave_id, moving through DORMANT → FORMING → ACTIVE → MATURE → DECAYING → ENDED. A wave
issues at most ONE primary entry (when it first reaches ACTIVE while leading Mag-7 attention);
every later elevated minute is a wave *update*, not a new trade. Leadership only rotates with
hysteresis (§12); an open position exits only on a confirmed same-ticker control transfer (§13),
a confirmed rotation, statistical exhaustion (§14), or a structural/EOD stop (from the engine).

`WaveEngine.evaluate()` is called once per poll with the ranked per-ticker metrics and the set
of currently-held (ticker, side) positions; it returns the entries to open and exits to close,
plus the transition log. It holds no I/O.
"""
import config
from analysis import hold

# STABILIZING (Phase 1) is a cooling-but-structurally-intact state between ACTIVE and any genuine
# end — reached only when STABILIZE_ENABLED. FUNDED / SELF_SUSTAINING / REACCELERATING (follow-up
# §7) are labelled only under CAMPAIGN_CONFIDENCE_ENABLED. With those flags off no wave ever enters
# them, so their presence in the tuple is inert and the validated behaviour is preserved exactly.
_STATES = ('DORMANT', 'FORMING', 'ACTIVE', 'FUNDED', 'SELF_SUSTAINING', 'REACCELERATING',
           'MATURE', 'STABILIZING', 'DECAYING', 'ENDED')


class Wave:
    __slots__ = ('ticker', 'side', 'wave_id', 'state', 'start_ts', 'last_ts', 'active_ts',
                 'peak_mass', 'peak_share', 'peak_z', 'peak_vel', 'cum_mass', 'entry_issued',
                 'forming_evals', 'active_evals', 'flip_evals', 'exhaust_evals', 'end_reason',
                 'dte', 'reduced', 'stabilize_ts', 'confidence')

    def __init__(self, ticker, side, wave_id, ts, dte=None):
        self.ticker, self.side, self.wave_id = ticker, side, wave_id
        self.state = 'FORMING'
        self.start_ts = self.last_ts = ts
        self.active_ts = None
        self.peak_mass = self.peak_share = self.peak_z = self.peak_vel = 0.0
        self.cum_mass = 0.0
        self.entry_issued = False
        self.forming_evals = self.active_evals = self.flip_evals = self.exhaust_evals = 0
        self.end_reason = None
        self.dte = dte              # days-to-expiry → DTE-sensitive confirmation/hold windows
        self.reduced = False        # a deterioration-driven partial exit already taken
        self.stabilize_ts = None    # when the wave entered STABILIZING (campaign-memory timeout)
        self.confidence = None      # follow-up §4-7: stateful CampaignConfidence (set on first hold)

    def go_active(self, ts):
        self.state = 'ACTIVE'
        if self.active_ts is None:
            self.active_ts = ts


class WaveEngine:

    def __init__(self):
        self.waves = {}          # (ticker, side) -> Wave (current / most recent)
        self.refractory = {}     # (ticker, side) -> {'until': ts, 'post_min': fast_mass}
        self._prev_share = {}    # ticker -> last poll's attention share
        self._rot_evals = 0      # consecutive polls a challenger has led the incumbent
        self._seq = 0
        self.early = {}          # Phase 2: (ticker,side) -> early-detection marks (WATCH/BUILDING)

    def new_session(self):
        self.waves.clear(); self.refractory.clear(); self._prev_share.clear()
        self._rot_evals = 0; self._seq = 0; self.early.clear()

    # ── Phase 2: early-detection tracking (spec §12-14 — WATCH/BUILDING + latency) ─
    def _track_early(self, key, m, ctrl, now, log):
        """Observation-only: record the first abnormal print (WATCH), the emergence of control,
        and sustained participation (BUILDING) BEFORE the FORMING birth threshold, so the engine
        can later report how early the evidence began. Never affects entry/exit decisions."""
        participation = m['mass_z'] >= config.EARLY_WATCH_Z and ctrl >= config.EARLY_WATCH_CONTROL
        e = self.early.get(key)
        if e is None:
            if participation:
                self.early[key] = {'first_abnormal_ts': now, 'watch_ts': now, 'building_ts': None,
                                   'control_ts': now if ctrl >= config.EARLY_CONTROL_MIN else None,
                                   'build_evals': 1, 'state': 'WATCH'}
                log.append(f"{key[0]}-{key[1][0]} WATCH early (z={m['mass_z']:.1f} ctrl={ctrl:.2f})")
            return
        if ctrl >= config.EARLY_CONTROL_MIN and e['control_ts'] is None:
            e['control_ts'] = now
        if participation:
            e['build_evals'] += 1
            if (e['building_ts'] is None and e['build_evals'] >= config.EARLY_BUILD_EVALS
                    and ctrl >= config.EARLY_CONTROL_MIN):
                e['building_ts'] = now; e['state'] = 'BUILDING'
                log.append(f"{key[0]}-{key[1][0]} BUILDING early "
                           f"(evals={e['build_evals']} ctrl={ctrl:.2f})")
        else:
            e['build_evals'] = 0

    def early_marks(self, ticker, side) -> dict:
        return self.early.get((ticker, side)) or {}

    # ── helpers ────────────────────────────────────────────────────────────────

    def _side_ctrl(self, m, side):
        return m['call_control'] if side == 'CALL' else m['put_control']

    def _side_vel(self, m, side):
        return m['call_velocity'] if side == 'CALL' else m['put_velocity']

    def _side_acc(self, m, side):
        return m['call_acceleration'] if side == 'CALL' else m['put_acceleration']

    def _lead_ok(self, m):
        return (m['attention_share'] >= config.WAVE_LEAD_SHARE
                and (m['mass_z'] >= config.WAVE_LEAD_Z_STRONG
                     or (m['mass_z'] >= config.WAVE_LEAD_Z_MID and m['impulse'] >= config.WAVE_LEAD_IMPULSE
                         and m['velocity'] > 0 and m['acceleration'] > 0)))

    def _in_refractory(self, key, m, ts):
        r = self.refractory.get(key)
        if not r:
            return False
        if _mins(ts, r['until']) >= 0:                    # timer elapsed
            return False
        # Exceptional-renewal override (§15): fresh, far larger, after a measurable reset.
        renew = (m['mass_z'] >= config.WAVE_RENEW_Z
                 or (r.get('post_min') and m['fast_mass'] >= config.WAVE_RENEW_FASTMASS_MULT * r['post_min']
                     and m['mass_z'] >= config.WAVE_RENEW_MIN_Z))
        return not renew

    # ── main ────────────────────────────────────────────────────────────────────

    def evaluate(self, ranked: list, metrics: dict, held: set, now, *, market_ok: bool = True,
                 dte_by: dict = None, health_by: dict = None) -> dict:
        enter, exits, log = [], [], []
        held_tickers = {t for (t, s) in held}
        dte_by = dte_by or {}
        health_by = health_by or {}          # Phase 1: (ticker,side)->campaign-health read (flag-gated)

        # 1) advance every ticker's dominant-side wave (birth / growth / decay).
        for m in ranked:
            t = m['symbol']
            side = m.get('dominant_side')
            share = m.get('attention_share', 0.0)
            prev_share = self._prev_share.get(t, 0.0)
            share_rising = share >= prev_share
            self._prev_share[t] = share
            key = (t, side) if side else None

            # update refractory post-wave minimum tracking
            for rk, r in self.refractory.items():
                if rk[0] == t:
                    r['post_min'] = min(r.get('post_min', m['fast_mass']), m['fast_mass'])

            if not side:
                continue
            w = self.waves.get(key)
            ctrl = self._side_ctrl(m, side)
            side_vel = self._side_vel(m, side)
            side_acc = self._side_acc(m, side)

            if config.EARLY_DETECT_ENABLED:            # Phase 2: pre-birth observation (no I/O)
                self._track_early(key, m, ctrl, now, log)

            # (re)birth
            if w is None or w.state == 'ENDED':
                forming = (m['mass_z'] >= config.WAVE_FORMING_Z and share_rising
                           and ctrl >= config.WAVE_FORMING_CONTROL and side_vel > 0)
                if forming and not self._in_refractory(key, m, now):
                    self._seq += 1
                    w = Wave(t, side, f"{t}-{side[0]}-{self._seq}", now, dte=dte_by.get(t))
                    self.waves[key] = w
                    log.append(f"{w.wave_id} DORMANT->FORMING (z={m['mass_z']} ctrl={ctrl:.2f} "
                               f"dte={w.dte})")
                else:
                    continue

            # peaks / cumulative
            w.last_ts = now
            w.peak_mass = max(w.peak_mass, m['fast_mass'])
            w.peak_share = max(w.peak_share, share)
            w.peak_z = max(w.peak_z, m['mass_z'])
            w.peak_vel = max(w.peak_vel, m['velocity'])
            w.cum_mass += m['ticker_mass']
            new_high = m['fast_mass'] >= w.peak_mass

            active_normal = (share >= config.WAVE_ACTIVE_SHARE and ctrl >= config.WAVE_ACTIVE_CONTROL
                             and m['mass_z'] >= config.WAVE_ACTIVE_Z and side_vel > 0)
            # v3-canonicalization item 3: EXCEPTIONAL ABSOLUTE route — a genuine campaign whose Mag-7
            # pool share is DILUTED by other simultaneous excellent campaigns can still activate on
            # absolute abnormality + control + information concentration. Absolute quality > rel. rank.
            active_absolute = (config.ABSOLUTE_ROUTE_ENABLED and m['mass_z'] >= config.WAVE_ABSOLUTE_Z
                               and ctrl >= config.WAVE_ACTIVE_CONTROL and side_vel > 0
                               and m.get('info_share', 0.0) >= config.WAVE_ABSOLUTE_INFO_SHARE)
            active_normal = active_normal or active_absolute
            active_immediate = (m['mass_z'] >= config.WAVE_IMMEDIATE_Z and share >= config.WAVE_IMMEDIATE_SHARE
                                and ctrl >= config.WAVE_IMMEDIATE_CONTROL and side_vel > 0 and side_acc > 0)

            if w.state == 'FORMING':
                tim = config.dte_timing(w.dte)          # DTE-sensitive confirmation window
                if active_immediate:
                    w.go_active(now); log.append(f"{w.wave_id} FORMING->ACTIVE immediate")
                elif active_normal:
                    w.active_evals += 1
                    if w.active_evals >= tim['active_confirm']:
                        w.go_active(now)
                        log.append(f"{w.wave_id} FORMING->ACTIVE confirmed "
                                   f"({w.active_evals}/{tim['active_confirm']})")
                else:
                    w.active_evals = 0
                # Still FORMING after this eval → apply the MAXIMUM confirmation window
                # (DTE-sensitive) and the z-collapse fizzle. Beyond the window the thesis has
                # not confirmed in time → FAILED_FORMATION (spec's downgrade route).
                if w.state == 'FORMING':
                    age_s = _mins(now, w.start_ts) * 60.0
                    if tim['max_forming_s'] is not None and age_s > tim['max_forming_s']:
                        w.state = 'ENDED'; w.end_reason = 'FAILED_FORMATION'
                        self._end(key, w, m, now)
                        log.append(f"{w.wave_id} FORMING->ENDED failed-formation "
                                   f"({age_s:.0f}s > {tim['max_forming_s']:.0f}s)")
                    elif m['mass_z'] < config.WAVE_END_Z and side_vel <= 0:
                        w.state = 'ENDED'; w.end_reason = 'FIZZLED'
                        self._end(key, w, m, now); log.append(f"{w.wave_id} FORMING->ENDED fizzled")
            elif w.state in ('ACTIVE', 'MATURE', 'STABILIZING', 'DECAYING'):
                if config.STABILIZE_ENABLED:
                    # Phase 1 path: cooling ≠ death. A structurally-intact wave moves to
                    # STABILIZING (campaign memory) rather than accruing exhaustion.
                    self._advance_stateful(w, m, share, share_rising, new_high, active_normal,
                                           health_by.get(key), now, log)
                else:
                    # ── validated 6-state path (unchanged when the flag is off) ──
                    # recovery from DECAYING keeps the same wave_id (no new entry)
                    if w.state != 'ACTIVE' and active_normal:
                        w.go_active(now); w.exhaust_evals = 0
                        log.append(f"{w.wave_id} ->ACTIVE recovered")
                    elif w.state == 'ACTIVE' and (m['acceleration'] < 0 or not new_high):
                        w.state = 'MATURE'; log.append(f"{w.wave_id} ACTIVE->MATURE")
                    elif w.state == 'MATURE' and (not share_rising or m['velocity'] < 0 or m['rank'] > 1):
                        w.state = 'DECAYING'; log.append(f"{w.wave_id} MATURE->DECAYING")
                    # statistical exhaustion (§14 D)
                    if (m['mass_z'] < config.WAVE_END_Z and m['velocity'] <= 0
                            and share < config.WAVE_END_SHARE):
                        w.exhaust_evals += 1
                    else:
                        w.exhaust_evals = 0

        # 2) EXITS for held positions. A young wave (< min-hold) is protected from thesis-exits
        #    unless the reversal is OVERWHELMING — this is what stops the 1-2 minute round-trips.
        incumbent = next(iter(held_tickers), None)
        rot = self._rotation(ranked, metrics, incumbent)
        for (t, side) in list(held):
            m = metrics.get(t)
            w = self.waves.get((t, side))
            reason = None
            min_hold_s = config.dte_timing(w.dte)['min_hold_s'] if w else config.WAVE_MIN_HOLD_SECONDS
            # v3-review item 13/20: when REVERSAL_ENABLED, the ReversalCluster machine (engine.
            # _manage_reversal) owns ALL non-risk opposite-side exits. A raw control ratio may NOT
            # independently flatten a position here — only a qualified reversal event, hard risk, EOD,
            # or profit management. This kills the "raw flip round-trip" the review flagged.
            raw_flip_ok = not (config.RAW_FLIP_EXIT_DISABLED and config.REVERSAL_ENABLED)
            if m and raw_flip_ok and self._overwhelming_flip(m, side):
                reason = 'CONTROL_FLIP_OVERWHELMING'
            elif w and w.active_ts is not None and _mins(now, w.active_ts) * 60 < min_hold_s:
                reason = None                                   # protect the young wave from noise
            elif config.CAMPAIGN_CONFIDENCE_ENABLED:
                # Follow-up §4-7: campaign-based exit. Rotation is a confidence PENALTY, not a
                # command; the position leaves only when accumulated confidence erodes below the
                # threshold (or a verified deterioration drives it there). Supersedes the STABILIZE
                # / rotation / exhaustion tiers below.
                reason = self._confidence_exit(t, side, w, m, health_by.get((t, side)), rot, now, log)
            elif m:
                if self._control_transfer(m, side, w):
                    reason = 'CONTROL_TRANSFER'
                elif w and w.exhaust_evals >= config.WAVE_END_EVALS:
                    # Phase 1: with STABILIZE_ENABLED, exhaust_evals only accrues on genuine
                    # multi-signal deterioration (see _advance_stateful) or after a stabilizing
                    # wave has faded past its window — so cooling alone no longer exits.
                    reason = 'STATISTICAL_EXHAUSTION'
                elif (rot and rot['ticker'] != t and rot['confirmed']
                      and w and w.state in ('MATURE', 'DECAYING')
                      and (not config.STABILIZE_ENABLED or not config.ROTATION_REQUIRE_INCUMBENT_WEAK
                           or self._campaign_deteriorating(m, side, w, health_by.get((t, side))))):
                    # Rotate out only if OUR OWN wave is already fading — never abandon a still-
                    # ACTIVE/STABILIZING, healthy incumbent just because another ticker scored
                    # higher (§12/§17/§31). A STABILIZING incumbent is intact and never rotates out.
                    reason = 'ROTATION'
            if reason:
                exits.append({'ticker': t, 'side': side, 'reason': reason,
                              'wave_id': w.wave_id if w else None})
                if w:
                    w.state = 'ENDED'; w.end_reason = reason
                    self._end((t, side), w, metrics.get(t), now)
                    log.append(f"{w.wave_id} EXIT {reason}")

        # 3) ENTRIES — a wave newly ACTIVE, leading attention, one entry, slot available.
        exiting = {e['ticker'] for e in exits}
        slots = config.MAX_PRIMARY_POSITIONS - (len(held) - len(exits))
        if market_ok and slots > 0:
            for m in ranked:
                t = m['symbol']
                side = m.get('dominant_side')
                if not side:
                    continue
                w = self.waves.get((t, side))
                # Enter EARLY — a FORMING wave qualifies (volume-leading-price, §2), not only a
                # fully-ACTIVE one at z=8. The value gate (engine: mark <= 1.5x session low) is what
                # keeps this from buying after the pop; here we just allow the earlier state.
                if not w or w.state not in ('FORMING', 'ACTIVE') or w.entry_issued:
                    continue
                if (t, side) in held:
                    continue
                # v3-review items 1-2: multiple independent Mag-7 campaigns may coexist. Under
                # MULTI_CAMPAIGN a held incumbent no longer blocks an independent challenger — the slot
                # cap (MAX_PRIMARY_POSITIONS) and the per-candidate portfolio-correlation gate govern
                # concurrency instead of a winner-take-all tournament. (Legacy single-slot behaviour is
                # preserved when MULTI_CAMPAIGN is off: incumbent blocks unless it is rotating out.)
                if not config.MULTI_CAMPAIGN_ENABLED:
                    if held and t not in exiting and not (rot and rot['ticker'] == t and rot['confirmed']):
                        continue
                # Rank/lead requirement. Under ENTRY_ROUTES, absolute campaign quality can qualify a
                # NON-leader (the MSFT 495C false-negative): propose any top-ROUTE_MAX_RANK candidate
                # and let _open_wave's route asymmetry score + hard vetoes be the real gate. Otherwise
                # keep the strict rank-1 + lead-margin discipline (spec §18: sit out a contested pool).
                if config.ENTRY_ROUTES_ENABLED:
                    if m['rank'] > config.ROUTE_MAX_RANK:
                        continue
                else:
                    if m['rank'] != 1 or not self._lead_ok(m):
                        continue
                    margin = m['attention_score'] - (ranked[1]['attention_score'] if len(ranked) > 1 else 0.0)
                    if margin < config.WAVE_LEAD_MARGIN:
                        continue
                if self._in_refractory((t, side), m, now):
                    continue
                # Proposed — the engine sets entry_issued only after the §16 contract gates pass,
                # so a temporarily unquotable contract does not burn the wave's one entry.
                enter.append({'ticker': t, 'side': side, 'wave': w, 'metric': m,
                              'wave_id': w.wave_id, 'event_class': m.get(side.lower(), {}).get('class')})
                slots -= 1
                if slots <= 0:
                    break

        return {'enter': enter, 'exit': exits, 'log': log, 'rotation': rot}

    # ── sub-decisions ────────────────────────────────────────────────────────────

    def _opp(self, m, side):
        if side == 'CALL':
            return (m['put_control'], m['put_z'], m['put_velocity'], m['put_acceleration'], m['call_velocity'])
        return (m['call_control'], m['call_z'], m['call_velocity'], m['call_acceleration'], m['put_velocity'])

    def _overwhelming_flip(self, m, side) -> bool:
        """Rare, very-high bar that may bypass the min-hold: opposite side seizes control hard."""
        opp_ctrl, opp_z, opp_vel, opp_acc, our_vel = self._opp(m, side)
        return (opp_ctrl >= config.WAVE_FLIP_OVERWHELM_CONTROL and opp_z >= config.WAVE_FLIP_OVERWHELM_Z
                and opp_vel > 0 and opp_acc > 0 and our_vel < 0)

    def _control_transfer(self, m, side, w) -> bool:
        """§13 — opposite ACTIVATION is not opposite CONTROL. Confirmed *persistent* transfer only."""
        opp_ctrl, opp_z, opp_vel, opp_acc, our_vel = self._opp(m, side)
        persist = (opp_ctrl >= config.WAVE_FLIP_PERSIST_CONTROL and opp_z >= config.WAVE_FLIP_PERSIST_Z
                   and m['signed_control'] * (1 if side == 'CALL' else -1) < 0 and our_vel <= 0)
        if w is not None:
            w.flip_evals = w.flip_evals + 1 if persist else 0
            return w.flip_evals >= config.WAVE_FLIP_PERSIST_EVALS
        return False

    # ── Phase 1: campaign memory / stabilization (spec §19-21, §31-32) ────────────
    def _campaign_intact(self, h) -> bool:
        """A campaign is structurally intact — cooling, not dying — while it retains control,
        faces no strong opposite-side campaign, is not distributing, and premium is progressing
        or recovering. Missing evidence is treated as intact (Phase 1: cooling is not death)."""
        if not h:
            return True
        return (h.get('control_ok', True) and not h.get('opp_strong', False)
                and not h.get('dist_high', False)
                and (h.get('progressing', True) or h.get('recovering', False)))

    def _campaign_deteriorating(self, m, side, w, h) -> bool:
        """Coherent multi-signal deterioration (spec §32) — never a lone falling Z or lost rank."""
        return not self._campaign_intact(h)

    def _advance_stateful(self, w, m, share, share_rising, new_high, active_normal, h, now, log):
        """STABILIZE_ENABLED path. Cooling ≠ death: a structurally-intact wave moves to
        STABILIZING and keeps its campaign memory; only genuine multi-signal deterioration (or a
        stabilizing wave that has faded far past its window) accrues exhaustion. Recovery /
        reacceleration returns it to ACTIVE with the SAME wave_id (never a new entry)."""
        if active_normal:
            if w.state != 'ACTIVE':
                log.append(f"{w.wave_id} {w.state}->ACTIVE recovered")
            w.go_active(now); w.exhaust_evals = 0; w.stabilize_ts = None
            return
        if self._campaign_intact(h):
            if w.state != 'STABILIZING':
                log.append(f"{w.wave_id} {w.state}->STABILIZING (cooling, campaign intact)")
                w.state = 'STABILIZING'; w.stabilize_ts = now
            w.exhaust_evals = 0
            if (config.WAVE_STABILIZE_MAX_S and w.stabilize_ts is not None
                    and _mins(now, w.stabilize_ts) * 60 > config.WAVE_STABILIZE_MAX_S):
                w.exhaust_evals += 1        # faded out — begin genuine end counting
            return
        # unhealthy → the deterioration ladder (same transitions as the validated path)
        if w.state == 'ACTIVE' and (m['acceleration'] < 0 or not new_high):
            w.state = 'MATURE'; log.append(f"{w.wave_id} ACTIVE->MATURE")
        elif w.state in ('MATURE', 'STABILIZING') and (not share_rising or m['velocity'] < 0
                                                       or m['rank'] > 1):
            prev = w.state; w.state = 'DECAYING'; log.append(f"{w.wave_id} {prev}->DECAYING")
        if (m['mass_z'] < config.WAVE_END_Z and m['velocity'] <= 0 and share < config.WAVE_END_SHARE):
            w.exhaust_evals += 1
        else:
            w.exhaust_evals = 0

    # ── Follow-up §4-7: campaign-based hold / confidence exit ─────────────────────
    def _confidence_exit(self, t, side, w, m, health, rot, now, log):
        """Update CampaignConfidence from the health read (rotation = penalty, not command) and
        return a §20 exit label only when confidence erodes below HOLD_EXIT_THRESHOLD."""
        if w is None:
            return None
        if w.confidence is None:
            w.confidence = config.CONF_INIT
        f = dict(health or {})
        if m is not None:                              # a revived wave earns confidence back
            ctrl = self._side_ctrl(m, side)
            f['active'] = ((m.get('attention_share', 0.0) >= config.WAVE_ACTIVE_SHARE
                            and ctrl >= config.WAVE_ACTIVE_CONTROL
                            and m.get('mass_z', 0.0) >= config.WAVE_ACTIVE_Z
                            and self._side_vel(m, side) > 0)
                           # item 3: absolute-event route — share-diluted but exceptional campaign
                           or (config.ABSOLUTE_ROUTE_ENABLED
                               and m.get('mass_z', 0.0) >= config.WAVE_ABSOLUTE_Z
                               and ctrl >= config.WAVE_ACTIVE_CONTROL
                               and m.get('info_share', 0.0) >= config.WAVE_ABSOLUTE_INFO_SHARE
                               and self._side_vel(m, side) > 0))
        rotation_active = bool(rot and rot.get('ticker') != t and rot.get('watched'))
        prev = w.confidence
        new_conf, dominant = hold.confidence_step(w.confidence, f, rotation_active)
        w.confidence = new_conf
        self._label_hold_state(w, f, log)
        # Per-poll confidence trajectory (spec: log confidence every poll + the active penalty/reward)
        # so every hold/exit is reconstructable from the log/archive.
        log.append(f"{w.wave_id} HOLD conf={new_conf:.2f} (Δ{new_conf - prev:+.2f} rot={int(rotation_active)} "
                   f"ctrl_ok={int(f.get('control_ok', True))} opp={int(bool(f.get('opp_strong')))} "
                   f"dist={int(bool(f.get('dist_high')))} prem={int(f.get('progressing', True))} "
                   f"hl={int(f.get('higher_low', True))} active={int(bool(f.get('active')))})")
        if new_conf < config.HOLD_EXIT_THRESHOLD:
            log.append(f"{w.wave_id} CONFIDENCE-EXIT conf={new_conf:.2f}<{config.HOLD_EXIT_THRESHOLD} "
                       f"cause={dominant}")
            return hold.exit_reason_from(dominant, f)
        return None

    def _label_hold_state(self, w, f, log):
        """Cosmetic lifecycle label under the confidence model (FUNDED/SELF_SUSTAINING/… — §7).
        The exit decision is driven by confidence, not by this label."""
        if f.get('active'):
            new = 'ACTIVE'
        elif f.get('reaccelerating'):
            new = 'REACCELERATING'
        elif f.get('self_sustaining'):
            new = 'SELF_SUSTAINING'
        elif self._campaign_intact(f):
            new = 'STABILIZING'
        else:
            new = 'DECAYING'
        if new != w.state:
            log.append(f"{w.wave_id} {w.state}->{new} (conf={w.confidence:.2f})")
            w.state = new

    def _rotation(self, ranked, metrics, incumbent):
        """§12 — leadership transfer with hysteresis. Returns the confirmed/watched rotation."""
        if not ranked:
            return None
        top = ranked[0]
        if incumbent is None or top['symbol'] == incumbent:
            self._rot_evals = 0
            return None
        inc = metrics.get(incumbent)
        margin = top['attention_score'] - (inc['attention_score'] if inc else 0.0)
        ctrl = self._side_ctrl(top, top['dominant_side']) if top.get('dominant_side') else 0.0
        immediate = (margin >= config.WAVE_ROT_CONFIRM_MARGIN and top['mass_z'] >= config.WAVE_ROT_CONFIRM_Z
                     and top['attention_share'] >= config.WAVE_ROT_CONFIRM_SHARE
                     and ctrl >= config.WAVE_ROT_CONFIRM_CONTROL)
        if margin >= config.WAVE_ROT_WATCH_MARGIN and top['velocity'] > 0:
            self._rot_evals += 1
        else:
            self._rot_evals = 0
        persistent = (self._rot_evals >= config.WAVE_ROT_PERSIST_EVALS and top['mass_z'] >= config.WAVE_ACTIVE_Z
                      and (inc['velocity'] <= 0 if inc else True))
        confirmed = immediate or persistent
        return {'ticker': top['symbol'], 'margin': round(margin, 1), 'confirmed': confirmed,
                'watched': margin >= config.WAVE_ROT_WATCH_MARGIN}

    def _end(self, key, w, m, ts):
        self.refractory[key] = {'until': _plus_min(ts, config.WAVE_REFRACTORY_MIN),
                                'post_min': (m or {}).get('fast_mass', 0.0)}
        self.early.pop(key, None)          # Phase 2: a new campaign re-measures latency from scratch

    def force_end(self, ticker, side, now, reason='STRUCTURAL', metric=None):
        """Engine-driven end (structural target / trailing / EOD) — ends the wave + refractory."""
        key = (ticker, side)
        w = self.waves.get(key)
        if w and w.state != 'ENDED':
            w.state = 'ENDED'; w.end_reason = reason
        self._end(key, w, metric, now)


def _mins(a, b):
    """minutes(a - b); accepts datetimes or epoch floats. Positive when a is later."""
    ta = a.timestamp() if hasattr(a, 'timestamp') else float(a)
    tb = b.timestamp() if hasattr(b, 'timestamp') else float(b)
    return (ta - tb) / 60.0


def _plus_min(ts, mins):
    if hasattr(ts, 'timestamp'):
        from datetime import timedelta
        return ts + timedelta(minutes=mins)
    return float(ts) + mins * 60
