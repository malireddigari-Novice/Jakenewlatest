"""
The Attention-Wave orchestrator.

Each poll:
  1. ingest live option snapshots per Mag-7 name (FlowTracker),
  2. compute MASS + abnormality (mass.TickerMass): weighted fresh premium, EWMA fast/slow,
     impulse, Z-scores, velocity/acceleration, control, strike-distribution quality,
  3. rank the pool by Attention Score (mass.rank_attention),
  4. drive the wave state machine (waves.WaveEngine): birth → active → decay → end, with
     leadership hysteresis, control-flip transfer, and refractory — emitting AT MOST ONE
     primary entry per wave and exits only on control transfer / rotation / exhaustion,
  5. execute: structural TP/trail first, then wave exits, then wave entries — each entry
     still passing the §16 contract gates (notional, liquidity, spread, staleness, freshness).

The goal is 0-3 waves and ≤5 primary entries per session — not a trade every qualifying
minute. Execution is real only when config.ALPACA_ENABLED; otherwise SHADOW accounting.
"""
import logging
from datetime import date, datetime

import config
import execution
import notify
import state
from analysis import archetype
from analysis import barshock
from analysis import campaign
from analysis import campaign_store
from analysis import contract_select
from analysis import dataquality
from analysis import decision_ledger
from analysis import decompose
from analysis import entry
from analysis import event_memory
from analysis import expiry_selector
from analysis import value_memory
from analysis import events as ev
from analysis import expiry
from analysis import expiry_value
from analysis import flow_response
from analysis import hedge as hedgeflow
from analysis import hold
from analysis import hypotheses
from analysis import inventory
from analysis import lifecycle as lc
from analysis import packages
from analysis import portfolio
from analysis import qualified
from analysis import regime as regimemod
from analysis import rotation
from analysis import mass
from analysis import oi_confirm
from analysis import replay
from analysis import response as resp
from analysis import reversal
from analysis import strikes as strikesurf
from analysis import value as valuemod
from analysis.flow import FlowTracker
from analysis.waves import WaveEngine
from data.alpaca_client import occ_symbol
from data.market_utils import (is_eod_window, is_market_open, is_opening_strict,
                               is_past_entry_cutoff, is_preopen_seed, now_cst, today_cst)

logger = logging.getLogger(__name__)


class AttentionEngine:

    def __init__(self, alpaca_data, alpaca_exec=None, schwab=None) -> None:
        self.data = alpaca_data
        self.exec = alpaca_exec
        self.schwab = schwab

        self.flow = FlowTracker()
        self.mass_book: dict = {}          # symbol -> mass.TickerMass
        self.waves = WaveEngine()
        self.orders = execution.OrderManager(alpaca_exec)
        self.sheets = self._init_sheets()

        self._hist = {'date': None}
        self._snaps: dict = {}
        self._spot: dict = {}
        self._expiry: dict = {}
        self._first_price: dict = {}       # (sym, side) -> {'price', 'ts'} (freshness / detection)
        self._expiry_scan_ts = None        # Phase 3: last multi-expiry shadow scan (throttle)
        self._fwd_share: dict = {}         # Phase 3: sym -> last forward-share (migration slope)
        self._expiry_class: dict = {}      # Phase 3/4: sym -> last expiry structural classification
        self._surf_center: dict = {}       # Phase 5: (sym,side) -> last weighted strike center (momentum)
        self._prev_scores: dict = {}       # §23: last poll's attention score per symbol (rotation velocity)
        self._expiry_rows: dict = {}       # #8: last multi-expiry rows per symbol (cross-expiry direction)
        self._dq: dict = {}                # #11-12: (sym) -> {contract: quote confidence 0..1}
        self._code_version, self._config_hash = self._provenance()   # item 17: ledger stamps
        self._nm_ts: dict = {}             # near-miss alert throttle: (sym,side) -> last alert ts
        self._nm_last_score: dict = {}     # near-miss dedup: (sym,side) -> last alerted route score
        self._attr = self._new_attrition() # EOD entry-funnel attrition counters
        self._shape_hist: dict = {}        # rolling-shape: (sym,side) -> [recent price-response shapes]
        self.archive = replay.ResearchArchive(config.RESEARCH_ARCHIVE_FILE)  # Phase 6
        self._archive_ts = None            # Phase 6: last candidate-snapshot write (throttle)

        self.state = state.load()
        # P1: on a mid-day RESTART, don't treat today as a fresh session — anchor the session date
        # from the persisted state so consumed slots + campaign memory survive the restart.
        if config.CROSS_SESSION_MEMORY_ENABLED and self.state.get('day'):
            self._hist['date'] = date.fromisoformat(self.state['day'])
        self._reconcile_positions()

    def _new_attrition(self) -> dict:
        """Fresh EOD entry-funnel counters (audit item 3/6). Sets are keyed by wave_id so a candidate
        re-evaluated across many polls is counted once per stage."""
        from collections import defaultdict
        return {'polls': 0, 'evaluated': set(), 'qualified': set(), 'route_passed': set(),
                'entered': set(), 'near_miss_alerts': 0,
                'hard_veto': defaultdict(set), 'near_miss': defaultdict(set),
                'post_route_veto': defaultdict(set)}   # route passed but a later hard gate killed it

    def _provenance(self):
        """(code_version, config_hash) for the Decision Ledger — so a record is tied to exactly what
        was executing. code_version from .git/HEAD (best-effort); config_hash over behavior flags."""
        import hashlib
        cv = None
        try:
            head = open('.git/HEAD').read().strip()
            if head.startswith('ref:'):
                cv = open('.git/' + head.split(' ', 1)[1]).read().strip()[:12]
            else:
                cv = head[:12]
        except Exception:
            cv = None
        try:
            flags = sorted(k for k in dir(config) if k.endswith('_ENABLED'))
            blob = ';'.join(f'{k}={getattr(config, k)}' for k in flags)
            ch = hashlib.sha1(blob.encode()).hexdigest()[:10]
        except Exception:
            ch = None
        return cv, ch

    def _init_sheets(self):
        """Connect the Google Sheets trade log (ported from Jakevolume). Never fatal — a missing
        credential / spreadsheet logs a warning and the engine runs on without Sheets."""
        if not config.SHEETS_ENABLED:
            return None
        try:
            from output.sheets_logger import SheetsLogger
            s = SheetsLogger()
            s.connect()
            return s
        except Exception:
            logger.warning("Google Sheets trade log disabled (connect failed)", exc_info=True)
            return None

    def _sheet(self, fn) -> None:
        """Run a Sheets log call, swallowing any error so it can never disrupt trading."""
        if not self.sheets:
            return
        try:
            fn()
        except Exception:
            logger.warning("Sheets log call failed", exc_info=True)

    # ── session / phase ───────────────────────────────────────────────────────

    def _roll_session(self, today: date) -> None:
        if self._hist['date'] != today:
            self._hist['date'] = today
            self.flow.new_session(today)
            self.waves.new_session()
            self.mass_book.clear()
            self._first_price.clear()
            self._expiry_scan_ts = None
            self._fwd_share.clear()
            self._expiry_class.clear()
            self._surf_center.clear()
            self.state['entered_today'] = []       # NS: daily one-ENTER-per-side slots reset each session
            self.state['reversal'] = {}            # P3: reversal clusters are intraday — reset each session
            # Addendum #1: inventory memory is CROSS-SESSION (a print's meaning depends on prior
            # inventory) — keep records whose expiry is still alive, prune the rest.
            if config.INVENTORY_ENABLED:
                self.state['inventory'] = inventory.prune(
                    self.state.get('inventory', {}), today, campaign_store.survives)
            # item 4: contract value memory is cross-session too — keep while the expiry is alive.
            if config.VALUE_MEMORY_ENABLED:
                self.state['value_mem'] = value_memory.prune(
                    self.state.get('value_mem', {}), today, campaign_store.survives)
            # item 17: immutable event provenance is cross-session too (superposed-campaign analysis).
            if config.EVENT_MEMORY_ENABLED:
                self.state['events'] = event_memory.prune(
                    self.state.get('events', {}), today, campaign_store.survives)
            # P1: carry surviving campaigns forward as inherited/overnight memory (prune expired),
            # instead of waking up fresh. The intraday microstructure above is correctly reset; the
            # campaign MEMORY persists so the engine manages yesterday's still-alive theses first.
            if config.CROSS_SESSION_MEMORY_ENABLED:
                carried = campaign_store.carry_forward(self.state.get('campaigns', {}), today)
                self.state['campaigns'] = carried
                if carried:
                    logger.info("CAMPAIGN MEMORY: carried %d overnight campaign(s) into %s: %s",
                                len(carried), today, ", ".join(carried))
            self.state['day'] = today.isoformat()
            self._attr = self._new_attrition()     # reset the EOD attrition funnel each session
            self._nm_ts.clear()
            self._nm_last_score.clear()
            self._shape_hist.clear()               # rolling-shape history is intraday
            logger.info("-- New session %s - waves/mass/baselines reset --", today)

    def _reconcile_positions(self) -> None:
        if not (self.exec and config.ALPACA_ENABLED):
            return
        kept = []
        for pos in self.state.get('positions', []):
            live = self.orders.reconcile(pos['occ'])
            if live and live['qty'] > 0:
                kept.append(pos)
            else:
                logger.info("startup: stored position %s not held - clearing", pos['occ'])
        self.state['positions'] = kept
        state.save(self.state)

    def _phase(self, now: datetime) -> str:
        if is_preopen_seed(now):
            return 'preopen'
        if is_market_open(now):
            return 'opening' if is_opening_strict(now) else 'regular'
        return 'closed'

    def _held(self):
        return self.state.setdefault('positions', [])

    def _dte(self, sym):
        exp = self._expiry.get(sym)
        return (exp - today_cst()).days if exp else None

    def _minutes_since_open(self, now) -> float:
        """Minutes since the 08:30 CST cash open (for the §36 late-0DTE theta ramp)."""
        open_t = now.replace(hour=8, minute=30, second=0, microsecond=0)
        return max(0.0, (now - open_t).total_seconds() / 60.0)

    def _campaign_ctx(self, sym, now) -> dict:
        """Context for the Bayesian prior — morning bias (institutional campaigns often commit
        early) nudges the prior up; DTE is carried for downstream use. Each poll UPDATES the
        posterior from this prior rather than resetting the thesis."""
        prior = 0.55 if is_opening_strict(now) else 0.50
        return {'prior': prior, 'dte': self._dte(sym)}

    def _position_dist_prob(self, pos, mark, metric, now, giveback) -> float:
        """Distribution probability for a LIVE position — the management-side read that drives
        WATCH/REDUCE. Uses premium extension, peak giveback, IV roll-over and opposite-side
        acceleration (efficiency-decay is entry-side only)."""
        strike, side = pos['strike'], pos['side']
        q = (self._snaps.get(pos['symbol']) or {}).get((strike, side)) or {}
        low = q.get('day_low') or mark
        extension = (mark / low) if low else 1.0
        iv_now = q.get('iv')
        iv_prev = self.flow.contract_iv_at(pos['symbol'], strike, side,
                                           now.timestamp() - config.IV_SLOPE_WINDOW_S)
        iv_slope = (iv_now - iv_prev) if (iv_now is not None and iv_prev is not None) else None
        rel_premium = (mark / pos['entry_price']) if pos.get('entry_price') else 1.0
        opp_accel_norm = 0.0
        if metric:
            opp_acc = metric['put_acceleration'] if side == 'CALL' else metric['call_acceleration']
            own_acc = abs(metric['acceleration']) + config.WAVE_EPS
            opp_accel_norm = max(0.0, min(1.0, opp_acc / own_acc)) if opp_acc > 0 else 0.0
        # Weak self-sustainability (premium no longer holding as volume fades) reads as efficiency
        # decay in the distribution logistic — a campaign that has stopped sustaining itself.
        marks = self.flow.contract_marks(pos['symbol'], strike, side, now)
        vols = self.flow.contract_minute_vols(pos['symbol'], strike, side, now)
        self_sust = lc.self_sustainability(vols, marks)
        eff_decay = -(1.0 - self_sust) if self_sust < config.SELF_SUST_WEAK else 0.0
        return resp.distribution_probability(
            extension=extension, eff_decay=eff_decay, rel_premium=rel_premium, iv_slope=iv_slope,
            giveback=giveback, opp_accel_norm=opp_accel_norm, spot_confirms=True)

    def _side_quality(self, sym, side, masses, tm, now):
        """Per-side quality multiplier for qualified directional control: event SHAPE (class) × premium
        ACCEPTANCE on the side's top-mass strike × FRESHNESS (abnormality z + acceleration). Returns
        (quality, acceptance_label). Empty side → (0.0, None)."""
        sk = masses['call_strikes'] if side == 'CALL' else masses['put_strikes']
        if not sk:
            return 0.0, None
        topk = max(sk, key=sk.get)
        acc = flow_response.premium_acceptance(
            self.flow.contract_minute_vols(sym, topk, side, now),
            self.flow.contract_marks(sym, topk, side, now))['label']
        z = tm['call_z'] if side == 'CALL' else tm['put_z']
        accel = tm['call_acceleration'] if side == 'CALL' else tm['put_acceleration']
        cls = (masses['call'] if side == 'CALL' else masses['put'])['class']
        return qualified.side_quality(cls, acc, z, accel), acc

    # ── Phase 1 / Follow-up P1: campaign-health read for stabilization + confidence ───
    def _campaign_health_by(self, ranked, metrics_by, cand, now) -> dict:
        """(ticker,side) -> structural-health read consumed by the wave stabilization (P1) and
        campaign-confidence (follow-up §4-7) exit logic. Empty unless one of those flags is on, so
        the validated exit behaviour is untouched otherwise. Covers ranked dominant sides + held sides."""
        if not (config.STABILIZE_ENABLED or config.CAMPAIGN_CONFIDENCE_ENABLED):
            return {}
        out = {}
        for m in ranked:
            side = m.get('dominant_side')
            if side:
                out[(m['symbol'], side)] = self._campaign_health(m['symbol'], side, m,
                                                                  cand.get(m['symbol']), None, now)
        for p in self._held():
            k = (p['symbol'], p['side'])
            if k not in out:
                out[k] = self._campaign_health(p['symbol'], p['side'],
                                               metrics_by.get(p['symbol']), None, p, now)
        return out

    def _campaign_health(self, t, side, m, c, pos, now) -> dict:
        """control_ok / opp_strong / dist_high / progressing / recovering for one (ticker,side).
        Uses the candidate read when the side is the current dominant side, else a live-position
        read (premium vs entry + position distribution probability)."""
        if not m:
            return {'control_ok': True, 'opp_strong': False, 'dist_high': False,
                    'progressing': True, 'recovering': False}
        control = m['call_control'] if side == 'CALL' else m['put_control']
        opp_ctrl = m['put_control'] if side == 'CALL' else m['call_control']
        opp_acc = m['put_acceleration'] if side == 'CALL' else m['call_acceleration']
        control_ok = control >= config.STABILIZE_MIN_CONTROL
        # When the P3 reversal cluster is active it OWNS the opposite side — so CampaignConfidence
        # stops exiting on raw opposite strength and only reacts to OWN-side deterioration; the staged
        # reversal machine decides whether opposite flow actually invalidates/reverses the campaign.
        opp_strong = (opp_ctrl >= config.STABILIZE_OPP_CONTROL and opp_acc > 0
                      and not config.REVERSAL_ENABLED)
        higher_low = True
        self_sustaining = False
        if c:
            progressing = (c.get('rel_premium', 1.0) >= config.STABILIZE_MIN_RELPREM
                           or c.get('self_sust', 0.0) >= config.SELF_SUST_WEAK
                           or c.get('cont_prob', 0.0) >= config.STABILIZE_MIN_CONT)
            dist_high = c.get('dist_prob', 0.0) >= config.DIST_PROB_EXIT
            recovering = c.get('shakeout', 0.0) >= config.SHAKEOUT_MIN
            self_sustaining = c.get('self_sust', 0.0) >= config.ARCH_SELF_SUST_MIN
            higher_low = (c.get('mfe', 0.0) or 0.0) >= 0.0
        elif pos is not None:
            mark = self._current_mark(pos) or pos['entry_price']
            entry = pos.get('entry_price') or mark
            rel = (mark / entry) if entry else 1.0
            peak = pos.get('peak_price', mark)
            pnl = (mark - entry) / entry if entry else 0.0
            peak_pnl = (peak - entry) / entry if entry else 0.0
            giveback = max(0.0, peak_pnl - pnl)
            dp = self._position_dist_prob(pos, mark, m, now, giveback)
            progressing = rel >= config.STABILIZE_MIN_RELPREM
            dist_high = dp >= config.DIST_PROB_EXIT
            recovering = False
            # Follow-up §16: premium-structure read from the live mark series (held position).
            marks = self.flow.contract_marks(pos['symbol'], pos['strike'], side, now)
            vols = self.flow.contract_minute_vols(pos['symbol'], pos['strike'], side, now)
            higher_low = hold.higher_low_quality(marks) >= 0.5
            self_sustaining = lc.self_sustainability(vols, marks) >= config.ARCH_SELF_SUST_MIN
        else:
            progressing, dist_high, recovering = True, False, False
        # Exit arbitration (new-spec 8/11): a raw control-flip is an INPUT to the ReversalCluster
        # machine, not an independent exit command — so when reversal owns the opposite side, control
        # loss no longer forces a PERSISTENT_CONTROL_TRANSFER confidence exit (the NVDA 6:37 / GOOGL
        # 7:44 two-minute flips). And a STRENGTHENING same-side campaign suppresses control/opposite
        # exits entirely (kills "STRENGTHENING + EXIT"). Own-side deterioration still exits.
        strengthening = bool(recovering or self_sustaining)
        if config.EXIT_ARBITRATION_ENABLED:
            if config.REVERSAL_ENABLED or strengthening:
                control_ok = True
            if strengthening:
                opp_strong = False
        return {'control_ok': control_ok, 'opp_strong': opp_strong, 'dist_high': dist_high,
                'progressing': progressing, 'recovering': recovering,
                'higher_low': higher_low, 'self_sustaining': self_sustaining,
                'reaccelerating': recovering, 'strengthening': strengthening}

    # ── the poll ────────────────────────────────────────────────────────────────

    def poll(self) -> None:
        now = now_cst()
        phase = self._phase(now)
        if phase == 'closed':
            return
        self._roll_session(today_cst())
        measured = self._ingest_all(now)

        if phase == 'preopen':
            for s in measured:
                self.flow.mark_poll(s, now)
            logger.info("PREOPEN  seeding baselines (%d names) - capturing the open", len(measured))
            return

        ranked, metrics_by, cand, market_mass = self._build_metrics(measured, now)
        for s in measured:
            self.flow.mark_poll(s, now)
        if not ranked:
            return

        market_ok = market_mass >= config.ATTENTION_MIN_TOTAL
        self._attr['polls'] += 1
        self._log_waves(ranked, market_mass, market_ok)
        # item 12: continuous attention-transfer — a destination accelerating while another cools is a
        # PRIORITY INVESTIGATION signal EVERY poll, independent of any exit (both may stay valid). This
        # is a discovery accelerator, not a portfolio handoff.
        if config.ATTN_TRANSFER_ENABLED and self._prev_scores:
            risers = [(r['symbol'], r['attention_score'] - self._prev_scores.get(r['symbol'], r['attention_score']))
                      for r in ranked if r.get('dominant_side')]
            up = [(s, d) for s, d in risers if d >= config.ROT_MIN_DELTA_SCORE]
            fell = any(d <= -config.ROT_MIN_DELTA_SCORE for _, d in risers)
            if up and fell:
                s, d = max(up, key=lambda x: x[1])
                logger.info("ATTENTION-TRANSFER → PRIORITY INVESTIGATE %s (+%.0f attention; another "
                            "ticker cooling) — discovery accelerator, not an exit", s, d)
        if config.MULTI_EXPIRY_ENABLED:
            self._maybe_scan_expiries(now)

        # 1) structural TP/trail first (may free the wave/slot), then reversal management (P3, owns
        #    opposite-side exits), then wave-driven exits/entries.
        self._manage_structural(now, metrics_by, ranked, market_mass)
        if config.REVERSAL_ENABLED:
            self._manage_reversal(metrics_by, now)
        held = {(p['symbol'], p['side']) for p in self._held()}
        today = today_cst()
        dte_by = {s: (self._expiry[s] - today).days for s in measured if self._expiry.get(s)}
        health_by = self._campaign_health_by(ranked, metrics_by, cand, now)
        res = self.waves.evaluate(ranked, metrics_by, held, now, market_ok=market_ok,
                                  dte_by=dte_by, health_by=health_by)
        for lg in res['log']:
            logger.info("WAVE  %s", lg)
        for ex in res['exit']:
            pos = self._find(ex['ticker'], ex['side'])
            if pos:
                mark = self._current_mark(pos)
                self._close(pos, mark if mark is not None else pos['entry_price'], now,
                            reason=ex['reason'], board=self._board_ctx(ranked, market_mass),
                            metric=metrics_by.get(ex['ticker']))
            # §23-24: a rotation exit should point the entry engine at WHERE attention went (this poll's
            # ranked candidates are already evaluated below; this makes the destination explicit).
            if config.ROTATION_RESOLVER_ENABLED and 'ROTATION' in (ex.get('reason') or ''):
                dest = rotation.resolve(ex['ticker'], ranked, self._prev_scores, cand, metrics_by)
                if dest.get('ticker'):
                    logger.info("ROTATION-DEST after %s %s exit → investigate %s %s (%s)",
                                ex['ticker'], ex['side'], dest['ticker'], dest['side'], dest['reason'])
        if is_past_entry_cutoff(now):
            if res['enter']:
                logger.info("ENTRY-CUTOFF  %d wave(s) suppressed (within %dmin of EOD flatten)",
                            len(res['enter']), config.ENTRY_CUTOFF_BUFFER_MIN)
        else:
            for en in res['enter']:
                slot = f"{en['ticker']}|{en['side']}"
                # NS daily lock: one ENTER per side per ticker per session. A used slot blocks any
                # re-entry that side/ticker today (even after an exit) — everything else is management.
                if config.DAILY_ENTRY_LOCK_ENABLED and slot in self.state.get('entered_today', []):
                    logger.info("ENTRY-SUPPRESSED %s %s — daily %s slot already used this session "
                                "(campaign management only, no re-entry)",
                                en['ticker'], en['side'], en['side'])
                    continue
                # item 10: expiry selector (shadow) — recommend the expiry that best expresses the
                # campaign before entering (execution still uses the nearest expiry when shadow).
                if config.EXPIRY_SELECTOR_ENABLED and self._expiry_rows.get(en['ticker']):
                    sel = expiry_selector.select(
                        self._expiry_rows[en['ticker']], traded_side=en['side'],
                        minutes_since_open=self._minutes_since_open(now))
                    if sel.get('best_dte') is not None:
                        logger.info("EXPIRY-SELECT %s %s → %s%s", en['ticker'], en['side'], sel['reason'],
                                    '' if config.EXPIRY_SELECTOR_SHADOW else ' (LIVE reroute)')
                rej = self._open_wave(en, cand, ranked, market_mass, now)   # None on entry; §19 label on reject
                # funnel attribution: if the route PASSED but the entry was still rejected, a POST-ROUTE
                # hard gate owns the kill — record which, so "ROUTE_PASSED but 0 ENTERED" is explained.
                rd = ((cand.get(en['ticker']) or {}).get('route_decision') or {})
                if rd.get('pass') and rej is not None:
                    self._attr['post_route_veto'][rej].add(en.get('wave_id'))
                if rej is None:
                    self._attr['entered'].add(en.get('wave_id'))
                    if config.DAILY_ENTRY_LOCK_ENABLED:
                        self.state.setdefault('entered_today', []).append(slot)
                # item 17: Decision Ledger — record the outcome with EVERY hard veto (not just the first).
                cc = cand.get(en['ticker'])
                self._log_decision(now, en['ticker'], en['side'], metrics_by.get(en['ticker']), cc,
                                   decision=('ALLOW' if rej is None else 'REJECT'),
                                   owner=('_open_wave' if rej is None else f'_open_wave:{rej}'),
                                   veto_reasons=([] if rej is None else self._hard_vetoes(cc, metrics_by.get(en['ticker']), now) or [rej]),
                                   strike=(cc or {}).get('best', {}).get('strike'),
                                   expiry=(self._expiry.get(en['ticker']).isoformat()
                                           if self._expiry.get(en['ticker']) else None),
                                   wave=en.get('wave'))
                if config.RESEARCH_ARCHIVE_ENABLED:
                    self.archive.write(replay.candidate_record(
                        now, en['ticker'], en['side'], metrics_by.get(en['ticker']),
                        cand.get(en['ticker']), en['wave'].state,
                        'ENTERED' if rej is None else 'REJECTED', rej))
        if config.REINFORCE_LOG_ENABLED:
            self._log_reinforcement(metrics_by, now)
        if config.RESEARCH_ARCHIVE_ENABLED:
            self._archive_snapshot(ranked, metrics_by, cand, now)
        # §23: remember this poll's attention scores for next poll's rotation-velocity read.
        self._prev_scores = {r['symbol']: r['attention_score'] for r in ranked}
        state.save(self.state)

    def _ingest_all(self, now: datetime) -> list:
        measured = []
        for sym in config.MAG7:
            try:
                spot = self.data.get_spot(sym)
                expiry = self.data.get_nearest_expiry(sym)     # dynamic: 0DTE if listed, else nearest
                if not spot or not expiry:
                    continue
                snaps = self.data.get_option_snapshots(sym, expiry, spot, config.PREMIUM_BAND_PCT)
                if not snaps:
                    continue
                # Addendum #11-12: validate the OPRA stream before it feeds event detection — drop
                # crossed/negative/no-mark snapshots so a bad quote can't fabricate an "event".
                if config.DATA_QUALITY_ENABLED:
                    snaps = self._clean_snaps(sym, snaps, now)
                    if not snaps:
                        continue
                self._snaps[sym], self._spot[sym], self._expiry[sym] = snaps, spot, expiry
                self.flow.ingest(sym, snaps, spot, now)
                measured.append(sym)
            except Exception:
                logger.warning("%s: ingest failed", sym, exc_info=True)
        return measured

    def _clean_snaps(self, sym, snaps, now) -> dict:
        """Addendum #11-12 data-quality pass: drop structurally-invalid contract snapshots and stash a
        per-contract quote confidence (used to discount aggressor/acceptance reads). Never fatal."""
        out, dropped, self._dq[sym] = {}, 0, {}
        for key, snap in snaps.items():
            try:
                v = dataquality.validate(snap, now)
            except Exception:
                out[key] = snap
                continue
            self._dq[sym][key] = v['confidence']
            if v['drop']:
                dropped += 1
                continue
            out[key] = snap
        if dropped:
            logger.info("DATA-QUALITY %s dropped %d/%d invalid snapshot(s)", sym, dropped, len(snaps))
        return out

    # ── build per-ticker metrics (mass + abnormality + candidate contract) ───────

    def _build_metrics(self, measured: list, now: datetime):
        metrics, cand = {}, {}
        for sym in measured:
            sf = self.flow.symbol_flow(sym, now)
            if not sf:
                continue
            masses = mass.compute_masses(sf['strikes'], sf['spot'])
            tm = self.mass_book.setdefault(sym, mass.TickerMass()).update(masses)
            if masses['call_mass'] == 0 and masses['put_mass'] == 0:
                dom = None
            else:
                dom = 'CALL' if masses['call_mass'] >= masses['put_mass'] else 'PUT'
            # Qualified directional control: raw call-vs-put mass must not decide side control. Discount
            # DISTRIBUTED / premium-REJECTING (heavy-volume-lower-lows) / stale flow before it counts, so
            # a compact, premium-expanding opposite event can win (the NVDA 8/11 220C-vs-220P case).
            qc = None
            if config.QUALIFIED_CONTROL_ENABLED and dom:
                call_q, call_acc = self._side_quality(sym, 'CALL', masses, tm, now)
                put_q, put_acc = self._side_quality(sym, 'PUT', masses, tm, now)
                qc = qualified.qualified_control(masses['call_mass'], masses['put_mass'], call_q, put_q)
                if qc['dominant_side']:
                    if qc['flipped_from_raw']:
                        logger.info("QUALIFIED-CONTROL %s raw=%s → qualified=%s "
                                    "(call q=%.2f/%s put q=%.2f/%s)", sym, dom, qc['dominant_side'],
                                    call_q, call_acc, put_q, put_acc)
                    dom = qc['dominant_side']
            metrics[sym] = {**tm, 'symbol': sym, 'dominant_side': dom, 'spot': sf['spot'],
                            'call': masses['call'], 'put': masses['put'], 'qualified_control': qc,
                            'ticker_info': masses.get('ticker_info', 0.0)}
            if dom:
                side_strikes = [d for (k, s), d in sf['strikes'].items() if s == dom]
                # P2/P4: per-strike BarVolumeShock, computed once here and reused for the barshock
                # log and for event-information contract selection.
                shk_by_strike = {}
                if config.BARSHOCK_ENABLED or config.EVENT_SELECT_ENABLED:
                    for k in (masses['call_strikes'] if dom == 'CALL' else masses['put_strikes']):
                        mk = ((self._snaps.get(sym) or {}).get((k, dom)) or {}).get('mark')
                        shk_by_strike[k] = barshock.bar_shock(
                            self.flow.contract_minute_vols(sym, k, dom, now), mk)
                # P4: pick the highest-information contract (falls back to the mass-based selector).
                if config.EVENT_SELECT_ENABLED:
                    best = (contract_select.select(dom, side_strikes, sf['spot'], shk_by_strike)
                            or ev.select_contract(dom, side_strikes, sf['spot']))
                else:
                    best = ev.select_contract(dom, side_strikes, sf['spot'])
                if best:
                    fkey = (sym, dom)
                    if tm['mass_z'] >= config.WAVE_FORMING_Z:
                        # Capture the campaign's accumulation-phase baseline at birth — price,
                        # contracts, notional, IV — the reference for the RELATIVE metrics and
                        # response-efficiency decay below.
                        self._first_price.setdefault(fkey, {
                            'price': best['mark'], 'ts': now.isoformat(),
                            'contracts': best.get('fresh_vol') or 0,
                            'notional': (best.get('fresh_vol') or 0) * (best.get('mark') or 0) * 100,
                            'iv': best.get('iv'), 'eff_peak': None})
                    elif tm['mass_z'] < config.WAVE_END_Z:
                        self._first_price.pop(fkey, None)
                    base = self._first_price.get(fkey) or {}
                    fp = base.get('price')
                    notional = (best.get('fresh_vol') or 0) * (best.get('mark') or 0) * 100
                    dlt = best.get('delta')
                    delta_adj_notional = notional * (abs(float(dlt)) if dlt is not None else 1.0)
                    clow = best.get('day_low') or best.get('mark') or 0
                    dist_low = (best['mark'] / clow) if (clow and best.get('mark')) else 9.9
                    # Price-response validation: is the option ACCUMULATING (premium expanding
                    # off the event) or DISTRIBUTING (heavy volume while premium collapses)?
                    minute_vols = self.flow.contract_minute_vols(sym, best['strike'], dom, now)
                    vp = resp.volume_pattern(minute_vols)
                    resp_event = resp.price_response(fp, best['mark'])
                    mark_recent = self.flow.contract_mark_at(
                        sym, best['strike'], dom, now.timestamp() - config.RESP_RECENT_WINDOW_S)
                    resp_recent = resp.price_response(mark_recent, best['mark'])
                    # Windowed premium response + shakeout — the lifecycle read that lets a briefly
                    # consolidating (but recovering) campaign still qualify (delayed convexity).
                    marks = self.flow.contract_marks(sym, best['strike'], dom, now)
                    wpr = lc.windowed_premium_response(marks, fp)
                    shakeout = lc.shakeout_score(marks, fp)
                    verdict = resp.classify(vp, resp_event, resp_recent, dist_low,
                                            masses[dom.lower()]['class'],
                                            mfe=wpr['mfe'], shakeout=shakeout)
                    # ── event-shape-through-time features ─────────────────────────────
                    # IV velocity dIV/dt over the slope window (None when IV unavailable).
                    iv_now = best.get('iv')
                    iv_prev = self.flow.contract_iv_at(
                        sym, best['strike'], dom, now.timestamp() - config.IV_SLOPE_WINDOW_S)
                    iv_slope = (iv_now - iv_prev) if (iv_now is not None and iv_prev is not None) else None
                    # Spot-direction confirmation dS/dt (CALL wants spot up, PUT wants spot down).
                    spot_vel = sf['spot'] - (sf.get('spot_prev') or sf['spot'])
                    spot_confirms = (spot_vel >= 0) if dom == 'CALL' else (spot_vel <= 0)
                    # Relative-to-accumulation ratios (current vs the campaign's start).
                    base_c, base_n = base.get('contracts') or 0, base.get('notional') or 0
                    rel_contracts = ((best.get('fresh_vol') or 0) / base_c) if base_c > 0 else 1.0
                    rel_notional = (notional / base_n) if base_n > 0 else 1.0
                    rel_premium = (best['mark'] / fp) if (fp and best.get('mark')) else 1.0
                    # Response efficiency (ΔP per unit fresh flow) + decay from campaign peak.
                    resp_eff = resp.response_efficiency(resp_event, notional)
                    peak_eff = base.get('eff_peak')
                    peak_eff = resp_eff if peak_eff is None else max(peak_eff, resp_eff)
                    eff_hist = base.get('eff_hist') or []
                    if fkey in self._first_price:
                        self._first_price[fkey]['eff_peak'] = peak_eff
                        eff_hist = (eff_hist + [resp_eff])[-config.EFF_HIST_MAX:]
                        self._first_price[fkey]['eff_hist'] = eff_hist
                    eff_decay = round(resp_eff - peak_eff, 4)
                    eff_trend = lc.efficiency_trend(eff_hist)
                    # Campaign self-sustainability — premium still rising while the buying fades.
                    self_sust = lc.self_sustainability(minute_vols, marks)
                    # Opposite-side acceleration, normalised 0-1 against our own.
                    opp_acc = tm['put_acceleration'] if dom == 'CALL' else tm['call_acceleration']
                    own_acc = abs(tm['acceleration']) + config.WAVE_EPS
                    opp_accel_norm = max(0.0, min(1.0, opp_acc / own_acc)) if opp_acc > 0 else 0.0
                    # Joint distribution probability (no giveback pre-entry).
                    dist_prob = resp.distribution_probability(
                        extension=dist_low, eff_decay=eff_decay, rel_premium=rel_premium,
                        iv_slope=iv_slope, giveback=0.0, opp_accel_norm=opp_accel_norm,
                        spot_confirms=spot_confirms)
                    # Continuation probability — P(campaign continues), feeds EV's P(continue).
                    ctrl_dom = tm['call_control'] if dom == 'CALL' else tm['put_control']
                    cont_prob = lc.continuation_probability(
                        self_sust=self_sust, eff_slope=eff_trend['slope'], auc=wpr['auc'],
                        control=ctrl_dom, spot_confirms=spot_confirms, shakeout=shakeout)
                    cand[sym] = {
                        'side': dom, 'best': best, 'notional': notional,
                        'delta_adj_notional': delta_adj_notional,
                        'freshness': ev.entry_freshness(fp, best['mark']),
                        'dist_low': dist_low, 'event_class': masses[dom.lower()]['class'],
                        'first_ts': base.get('ts'),
                        'accumulation': verdict['eligible'], 'acc_label': verdict['label'],
                        'shape': verdict['shape'], 'resp_event': resp_event, 'vp': vp,
                        'iv_now': iv_now, 'iv_slope': iv_slope, 'spot_vel': spot_vel,
                        'spot_confirms': spot_confirms, 'rel_contracts': round(rel_contracts, 3),
                        'rel_notional': round(rel_notional, 3), 'rel_premium': round(rel_premium, 3),
                        'resp_eff': resp_eff, 'resp_eff_decay': eff_decay, 'dist_prob': dist_prob,
                        'self_sust': self_sust, 'eff_trend': eff_trend['label'],
                        'cont_prob': cont_prob, 'mfe': wpr['mfe'], 'auc': wpr['auc'],
                        'shakeout': shakeout,
                    }
                    # Phase 2: EarlyAccumulationScore (research; logged, never gates alone).
                    cand[sym]['eas'] = campaign.early_accumulation_score(metrics[sym], cand[sym])
                    # 2026-08-22 rolling-shape: track the recent price-response shapes per (sym,side) so
                    # the EXIT_SHAPE veto can tell a persistent exit from a single-poll classifier flip.
                    if config.ROLLING_SHAPE_ENABLED:
                        hk = (sym, dom)
                        h = (self._shape_hist.get(hk, []) + [cand[sym]['shape']])[-config.SHAPE_HIST_MAX:]
                        self._shape_hist[hk] = h
                        exitc = sum(1 for s in h if s in entry._EXIT_SHAPES)
                        cand[sym]['shape_hist_n'] = len(h)
                        cand[sym]['recent_exit_frac'] = round(exitc / len(h), 3) if h else 1.0
                    # Addendum #1-4,7: inventory memory (cost-basis drift + MarginalFlowEfficiency;
                    # HIGH ambiguity → abstain at entry) and the package/leg resolver (spread/roll
                    # legs). Wrapped: a data-shape surprise here must never break the whole poll.
                    try:
                        if config.INVENTORY_ENABLED:
                            exp = self._expiry.get(sym)
                            exp_iso = exp.isoformat() if exp else 'x'
                            ikey = inventory.contract_key(sym, dom, best['strike'], exp_iso)
                            store = self.state.setdefault('inventory', {})
                            rec = store.get(ikey)
                            cand[sym]['inventory'] = inventory.assess(
                                rec, current_price=best.get('mark'), new_size=best.get('fresh_vol') or 0)
                            if config.INV_DEPLETION_ENABLED:
                                cand[sym]['inventory']['depletion'] = inventory.depletion(rec)
                            last = (rec or {}).get('last_ts')
                            due = True
                            if last:
                                try:
                                    due = (now - datetime.fromisoformat(last)).total_seconds() >= config.INV_OBSERVE_INTERVAL_S
                                except Exception:
                                    due = True
                            if due and (best.get('fresh_vol') or 0) >= config.INV_EVENT_MIN_CONTRACTS:
                                store[ikey] = inventory.observe(
                                    rec, price=best.get('mark'), size=best.get('fresh_vol') or 0,
                                    ts=now.isoformat(), spot=sf['spot'], iv=best.get('iv'))
                            # item 5: cumulative small-clip unwind — does NOT need a ≥250 print.
                            if config.INV_MICRODIST_ENABLED:
                                est_vol = ((inventory._basis(rec)['size'] if rec else 0)
                                           or (best.get('fresh_vol') or 0))
                                cand[sym]['inventory']['micro'] = inventory.micro_distribution(
                                    minute_vols, marks, est_vol)
                        # item 4: contract value memory (state-adjusted cheapness, not session-low).
                        if config.VALUE_MEMORY_ENABLED:
                            exp_iso2 = (self._expiry.get(sym).isoformat() if self._expiry.get(sym) else 'x')
                            vkey = value_memory.contract_key(sym, dom, best['strike'], exp_iso2)
                            vstore = self.state.setdefault('value_mem', {})
                            vrec = vstore.get(vkey)
                            cand[sym]['value'] = value_memory.assess(
                                vrec, current_mark=best.get('mark'), current_delta=best.get('delta'),
                                current_spot=sf['spot'])
                            vstore[vkey] = value_memory.observe(
                                vrec, mark=best.get('mark'), bid=best.get('bid'), ask=best.get('ask'),
                                spot=sf['spot'],
                                moneyness=(best['strike'] - sf['spot']) / sf['spot'] if sf.get('spot') else None,
                                delta=best.get('delta'), iv=best.get('iv'), ts=now.isoformat())
                        if config.PACKAGES_ENABLED:
                            raw_vols = {(k, s): (d.get('fresh_vol') or 0)
                                        for (k, s), d in sf['strikes'].items()}
                            cand[sym]['package'] = packages.resolve(best['strike'], dom, raw_vols, sf['spot'])
                    except Exception:
                        logger.warning("%s: inventory/package read failed (non-fatal)", sym, exc_info=True)
                    # Addendum #14/#13/#9: premium-move decomposition (delta/gamma/IV), hedge-flow
                    # (directional vs convexity), and the competing-hypotheses distribution. All pure,
                    # all wrapped — a greek/data gap degrades to a neutral read, never breaks the poll.
                    try:
                        gamma = ((self._snaps.get(sym) or {}).get((best['strike'], dom)) or {}).get('gamma')
                        if config.DECOMPOSE_ENABLED:
                            cand[sym]['decomp'] = decompose.decompose(
                                prev_mark=mark_recent, mark=best.get('mark'), delta=dlt, gamma=gamma,
                                spot_prev=sf.get('spot_prev'), spot=sf['spot'])
                        if config.HEDGE_FLOW_ENABLED:
                            cand[sym]['hedge'] = hedgeflow.assess(
                                iv_slope=iv_slope, spot_confirms=spot_confirms,
                                resp_event=resp_event, delta=dlt)
                        # item 14: cross-feed skew — how stale is the option quote vs this poll?
                        qts = ((self._snaps.get(sym) or {}).get((best['strike'], dom)) or {}).get('quote_ts')
                        cand[sym]['quote_ts'] = qts
                        if qts:
                            try:
                                cand[sym]['quote_skew_ms'] = round(
                                    (now - datetime.fromisoformat(qts)).total_seconds() * 1000, 0)
                            except Exception:
                                cand[sym]['quote_skew_ms'] = None
                        # item 20: the candidate carries ONE authoritative control side (already resolved
                        # to qualified control upstream when enabled). No downstream module recomputes it.
                        cand[sym]['authoritative_control'] = dom
                        if config.HYPOTHESES_ENABLED:
                            acc_lbl = flow_response.premium_acceptance(minute_vols, marks)['label']
                            invd = cand[sym].get('inventory') or {}
                            cand[sym]['hypotheses'] = hypotheses.assess({
                                'acceptance': acc_lbl, 'resp_event': resp_event, 'self_sust': self_sust,
                                'inv_ambiguity': invd.get('ambiguity'), 'inv_state': invd.get('state'),
                                'package': (cand[sym].get('package') or {}).get('label'),
                                'hedge': (cand[sym].get('hedge') or {}).get('read'),
                                'drift': cand[sym].get('rel_premium')})
                    except Exception:
                        logger.warning("%s: decompose/hedge/hypotheses read failed (non-fatal)", sym, exc_info=True)
                    # New-spec: Premium Acceptance — absorption vs rejection under heavy volume.
                    if config.ACCEPTANCE_ENABLED:
                        cand[sym]['acceptance'] = flow_response.premium_acceptance(minute_vols, marks)
                    # P2: per-strike BarVolumeShock across the dominant side's strikes (research/log;
                    # the highest-information strike right now, vs its own baseline + neighbors).
                    if config.BARSHOCK_ENABLED:
                        shk = shk_by_strike
                        if shk:
                            tk = max(shk, key=lambda kk: shk[kk]['shock'])
                            top = shk[tk]
                            rel = barshock.relative_shock(
                                top['shock'], [s['shock'] for kk, s in shk.items() if kk != tk])
                            clus = barshock.cluster_shock([s['shock'] for s in shk.values()])
                            cand[sym]['barshock'] = {
                                'top_strike': tk, 'shock': top['shock'], 'rel_shock': rel,
                                'cluster': clus, 'significant': top['significant'],
                                'event_type': barshock.classify_event(top['shock'], rel, clus),
                                'position': barshock.strike_position(tk, sf['spot'], dom),
                                'baseline_quality': top.get('baseline_quality')}
                    # item 17: record the significant event IMMUTABLY (event-level provenance) so future
                    # logic can separate multiple latent campaigns superposed on one contract.
                    if config.EVENT_MEMORY_ENABLED:
                        try:
                            bsr = cand[sym].get('barshock') or {}
                            if bsr.get('significant'):
                                exp_iso3 = (self._expiry.get(sym).isoformat() if self._expiry.get(sym) else 'x')
                                self.state['events'] = event_memory.record(
                                    self.state.get('events', {}), ticker=sym, side=dom,
                                    strike=best['strike'], expiry=exp_iso3, ts=now.isoformat(),
                                    size=best.get('fresh_vol') or 0, price=best.get('mark'),
                                    spot=sf['spot'], iv=best.get('iv'), delta=best.get('delta'),
                                    moneyness=(best['strike'] - sf['spot']) / sf['spot'] if sf.get('spot') else None,
                                    shape=bsr.get('event_type'),
                                    direction_hyp=(cand[sym].get('hypotheses') or {}).get('top'),
                                    inventory_hyp=(cand[sym].get('inventory') or {}).get('state'))
                        except Exception:
                            logger.warning("%s: event-memory record failed (non-fatal)", sym, exc_info=True)
                    # Phase 5: strike-surface profile (ticker-level campaign first; research/log).
                    if config.SURFACE_ENABLED:
                        sm = masses['call_strikes'] if dom == 'CALL' else masses['put_strikes']
                        cand[sym]['surface'] = strikesurf.surface_profile(
                            sm, sf['spot'], self._surf_center.get((sym, dom)))
                        self._surf_center[(sym, dom)] = cand[sym]['surface']['weighted_center']
                    # Phase 4: campaign archetype (research; logged, gates nothing yet).
                    if config.ARCHETYPE_ENABLED:
                        cand[sym]['archetype'] = archetype.classify({
                            'vp': vp, 'mass_z': tm['mass_z'], 'impulse': tm['impulse'],
                            'velocity': tm['velocity'], 'resp_event': resp_event,
                            'self_sust': self_sust, 'eff_trend': eff_trend['label'],
                            'rel_premium': rel_premium, 'dist_prob': dist_prob,
                            'shakeout': shakeout, 'mfe': wpr['mfe'],
                            'expiry_class': self._expiry_class.get(sym)})
                        # Follow-up §15-17: archetype-aware CampaignQualityScore (persistence-weighted
                        # for persistent builds, acceleration-weighted for shocks, …). Research/log.
                        ctrl_q = tm['call_control'] if dom == 'CALL' else tm['put_control']
                        qf = {
                            'persistence': hold.premium_persistence(minute_vols),
                            'notional': min(1.0, notional / (config.GATE_MIN_EVENT_NOTIONAL * 2.0)),
                            'control': max(0.0, min(1.0, (ctrl_q - 0.5) * 2.0)),
                            'continuation': cont_prob, 'low_dist': max(0.0, 1.0 - dist_prob),
                            'acceleration': max(0.0, min(1.0, (tm['impulse'] - 1.0) / 1.5)),
                            'response': max(0.0, min(1.0, 0.5 + resp_event * 2.0)),
                            'expiry': self._fwd_share.get(sym, 0.0), 'self_sust': self_sust}
                        cand[sym]['quality'] = archetype.quality_score(
                            cand[sym]['archetype']['archetype'], qf)
        market_mass = sum(metrics[s]['ticker_mass'] for s in metrics) or config.WAVE_EPS
        # item 15: InformationMass share (price-independent participation) kept PARALLEL to premium
        # share, and a blended discovery_share so a cheap clean-convexity event is not buried by an
        # expensive deep-ITM pool. Discovery uses the blend; core ranking still uses premium share.
        market_info = sum(metrics[s].get('ticker_info', 0.0) for s in metrics) or config.WAVE_EPS
        for s in metrics:
            metrics[s]['attention_share'] = round(metrics[s]['ticker_mass'] / market_mass, 4)
            metrics[s]['info_share'] = round(metrics[s].get('ticker_info', 0.0) / market_info, 4)
            if config.INFO_MASS_ENABLED:
                w = config.INFO_MASS_WEIGHT
                metrics[s]['discovery_share'] = round(
                    (1 - w) * metrics[s]['attention_share'] + w * metrics[s]['info_share'], 4)
            else:
                metrics[s]['discovery_share'] = metrics[s]['attention_share']
        # v3-audit item 6: log Premium / Information / Blended-discovery / Qualified-control RANKS per
        # ticker so the Decision Ledger can reveal whether the 30% info blend still buries a pristine
        # cheap event under expensive low-information premium (the NVDA 220P failure mode).
        for s in metrics:
            qc = metrics[s].get('qualified_control') or {}
            dom = metrics[s].get('dominant_side')
            metrics[s]['qc_strength'] = ((qc.get('q_call_control', 0.0) if dom == 'CALL'
                                          else qc.get('q_put_control', 0.0)) if qc else 0.0)

        def _rank_by(key):
            order = sorted(metrics, key=lambda s: metrics[s].get(key, 0.0), reverse=True)
            return {s: i + 1 for i, s in enumerate(order)}
        prem_r, info_r = _rank_by('ticker_mass'), _rank_by('ticker_info')
        disc_r, qc_r = _rank_by('discovery_share'), _rank_by('qc_strength')
        for s in metrics:
            metrics[s]['premium_mass_rank'] = prem_r[s]
            metrics[s]['info_mass_rank'] = info_r[s]
            metrics[s]['discovery_rank'] = disc_r[s]
            metrics[s]['qualified_control_rank'] = qc_r[s]
        ranked = mass.rank_attention(metrics)
        return ranked, {r['symbol']: r for r in ranked}, cand, market_mass

    # ── Phase 3: multi-expiration shadow scan (throttled, log-only) ───────────────
    def _maybe_scan_expiries(self, now) -> None:
        """Every MULTI_EXPIRY_POLL_S, derive the per-ticker expiry structure (share/control/
        migration) across several relevant expiries and LOG it. Does not affect entries/exits —
        the trading path still uses the nearest expiry (spec §8 / Phase 3 is shadow)."""
        if (self._expiry_scan_ts is not None
                and (now - self._expiry_scan_ts).total_seconds() < config.MULTI_EXPIRY_POLL_S):
            return
        self._expiry_scan_ts = now
        today = today_cst()
        for sym in config.MAG7:
            spot = self._spot.get(sym)
            if not spot:
                continue
            try:
                exps = self.data.get_scan_expiries(sym, config.MULTI_EXPIRY_MAX)
                by_expiry, dte_by = {}, {}
                for e in exps:
                    snaps = self.data.get_option_snapshots(sym, e, spot, config.PREMIUM_BAND_PCT)
                    if not snaps:
                        continue
                    strikes = {(k, side): {'fresh_vol': v.get('volume', 0) or 0, 'mark': v.get('mark') or 0}
                               for (k, side), v in snaps.items() if v.get('mark')}
                    if not strikes:
                        continue
                    by_expiry[e.isoformat()] = mass.compute_masses(strikes, spot)
                    dte_by[e.isoformat()] = (e - today).days
                if not by_expiry:
                    continue
                summ = expiry.summarize(by_expiry, dte_by, self._fwd_share.get(sym))
                self._fwd_share[sym] = summ['forward_share']
                self._expiry_class[sym] = summ['classification']
                self._expiry_rows[sym] = summ['rows']       # #8: cross-expiry directional input
                parts = "  ".join(f"{r['key'][5:]}={100*r['share']:.0f}%{(r['side'] or '-')[0]}"
                                  for r in summ['rows'] if r['share'] >= 0.05)
                logger.info("EXPIRY %s %s fwd=%.0f%% mig=%s | %s", sym, summ['classification'],
                            100 * summ['forward_share'], summ['migration'] or '-', parts)
            except Exception:
                logger.warning("%s: expiry scan failed", sym, exc_info=True)

    # ── New-spec: reinforcement lifecycle updates (not new entries) ───────────────
    def _log_reinforcement(self, metrics_by, now) -> None:
        """Same-side concentrated flow resurging on a HELD position is REINFORCEMENT, not a new
        trade (the AMZN 12:04 $1.44M second wave). Log/notify STRENGTHENING, throttled — the daily
        lock already prevents a re-ENTER; this makes the 'one alert + lifecycle updates' model real."""
        for pos in self._held():
            m = metrics_by.get(pos['symbol'])
            if not m or m.get('dominant_side') != pos['side']:
                continue
            # Never post STRENGTHENING on a campaign whose confidence has already faded toward exit —
            # that produced the contradictory "STRENGTHENING + EXIT" output. One authoritative state.
            w = self.waves.waves.get((pos['symbol'], pos['side']))
            if w and w.confidence is not None and w.confidence < config.REINFORCE_MIN_CONF:
                continue
            # Addendum #3 — same-side flow after a successful event is NOT automatically reinforcement.
            # If MarginalFlowEfficiency has gone weak (premium no longer advancing on the new flow), the
            # original inventory is more likely being monetized into strength — suppress STRENGTHENING.
            if config.INVENTORY_ENABLED:
                ikey = inventory.contract_key(pos['symbol'], pos['side'], pos['strike'], pos.get('expiry'))
                rec = self.state.get('inventory', {}).get(ikey)
                mk = self._current_mark(pos)
                if rec and mk is not None:
                    mfe = inventory.marginal_flow_efficiency(rec, mk)
                    if mfe <= config.INV_MFE_WEAK:
                        logger.info("REINFORCE-SUPPRESSED %s %s — same-side flow but MFE=%.4f weak "
                                    "(likely inventory distribution, not reinforcement)",
                                    pos['symbol'], pos['side'], mfe)
                        continue
                # item 5: cumulative small-clip unwind — even sub-250 clips into strength are exit-like.
                if config.INV_MICRODIST_ENABLED:
                    mv = self.flow.contract_minute_vols(pos['symbol'], pos['strike'], pos['side'], now)
                    mks = self.flow.contract_marks(pos['symbol'], pos['strike'], pos['side'], now)
                    est = (inventory._basis(rec)['size'] if rec else 0) or 0
                    micro = inventory.micro_distribution(mv, mks, est)
                    if micro['chunked']:
                        logger.info("REINFORCE-SUPPRESSED %s %s — chunked micro-distribution (%s) — "
                                    "likely quiet unwind, not reinforcement", pos['symbol'], pos['side'],
                                    micro['reason'])
                        continue
            ctrl = m['call_control'] if pos['side'] == 'CALL' else m['put_control']
            strong = (m.get('mass_z', 0.0) >= config.WAVE_ACTIVE_Z and ctrl >= config.WAVE_ACTIVE_CONTROL
                      and m.get('velocity', 0.0) > 0)
            last = pos.get('last_reinforce_ts')
            due = True
            if last:
                try:
                    due = (now - datetime.fromisoformat(last)).total_seconds() >= config.REINFORCE_MIN_INTERVAL_S
                except Exception:
                    due = True
            if strong and due:
                pos['last_reinforce_ts'] = now.isoformat()
                logger.info("CAMPAIGN STRENGTHENING %s %s — same-side flow reinforcing "
                            "(z=%.1f ctrl=%.2f share=%.0f%%) — HOLD, not a new entry",
                            pos['symbol'], pos['side'], m['mass_z'], ctrl, 100 * m.get('attention_share', 0.0))
                try:
                    notify.send(f"🟢 {pos['symbol']} {pos['side']} — CAMPAIGN STRENGTHENING "
                                f"(same-side flow reinforcing; HOLD, not a new entry)")
                except Exception:
                    pass

    # ── Phase 6: candidate archive / campaign replay (throttled, JSONL) ───────────
    def _archive_snapshot(self, ranked, metrics_by, cand, now) -> None:
        """Every RESEARCH_ARCHIVE_EVERY_S, append a poll-by-poll record for the top-K ranked
        candidates (held or observed) so a campaign can be reconstructed and a missed winner
        diagnosed offline. Never affects the trading loop; failures are swallowed."""
        if (self._archive_ts is not None
                and (now - self._archive_ts).total_seconds() < config.RESEARCH_ARCHIVE_EVERY_S):
            return
        self._archive_ts = now
        held = {(p['symbol'], p['side']) for p in self._held()}
        for m in ranked[:config.RESEARCH_ARCHIVE_TOPK]:
            sym, side = m['symbol'], m.get('dominant_side')
            if not side:
                continue
            w = self.waves.waves.get((sym, side))
            state = w.state if w else (self.waves.early_marks(sym, side).get('state') or 'DORMANT')
            decision = 'HELD' if (sym, side) in held else 'OBSERVED'
            self.archive.write(replay.candidate_record(now, sym, side, m, cand.get(sym), state, decision))

    def _log_waves(self, ranked, market_mass, market_ok) -> None:
        parts = []
        for r in ranked[:3]:
            w = self.waves.waves.get((r['symbol'], r.get('dominant_side')))
            st = w.state[:4] if w else '----'
            parts.append(f"{r['symbol']}={r['attention_score']:.0f}"
                         f"({100*r['attention_share']:.0f}%/z{r['mass_z']:.1f}/"
                         f"{r.get('dominant_side') or '-'}/{st})")
        logger.info("WAVES  mass=$%s%s | %s", f"{round(market_mass):,}",
                    '' if market_ok else ' (below floor)', "  ".join(parts))

    # ── structural exits (Route A) ────────────────────────────────────────────────

    def _manage_structural(self, now, metrics_by, ranked, market_mass) -> None:
        for pos in list(self._held()):
            mark = self._current_mark(pos)
            if mark is None:
                continue
            entry = pos['entry_price']
            pos['peak_price'] = max(pos.get('peak_price', entry), mark)
            pos['trough_price'] = min(pos.get('trough_price', entry), mark)   # Phase 7: MAE tracking
            pnl = (mark - entry) / entry if entry else 0.0
            peak = (pos['peak_price'] - entry) / entry if entry else 0.0
            board = self._board_ctx(ranked, market_mass)
            # Hard stop-loss first — risk backstop, caps the tail regardless of thesis/min-hold.
            if config.STOP_LOSS_PCT and pnl <= -config.STOP_LOSS_PCT:
                self._close(pos, mark, now, reason='STOP_LOSS', board=board,
                            metric=metrics_by.get(pos['symbol']))
                continue
            # WATCH/REDUCE — deterioration-driven partial exit. When the CampaignConfidence hold
            # engine is authoritative it OWNS deterioration (distribution feeds its dist_high penalty),
            # so this independent legacy trim is disabled — the hold engine is the single decision
            # owner except for hard stop / EOD / overwhelming flip / profit objective (spec §4).
            if (config.REDUCE_ON_DISTRIBUTION and not config.CAMPAIGN_CONFIDENCE_ENABLED
                    and not pos.get('tp1_done') and not pos.get('reduced')):
                giveback = max(0.0, peak - pnl)
                dp = self._position_dist_prob(pos, mark, metrics_by.get(pos['symbol']), now, giveback)
                if dp >= config.DIST_PROB_REDUCE and giveback >= config.REDUCE_MIN_GIVEBACK:
                    pos['reduced'] = True
                    logger.info("WATCH/REDUCE %s %s distribution p=%.2f giveback=%.0f%% — trimming",
                                pos['symbol'], pos['side'], dp, 100 * giveback)
                    self._scale_out(pos, mark, now, reason='DISTRIBUTION_REDUCE', pnl=pnl)
                    if pos not in self._held():
                        continue
            if not pos.get('tp1_done') and pnl >= config.TAKE_PROFIT_1_PCT:
                self._scale_out(pos, mark, now, reason='STRUCTURAL_TP1', pnl=pnl)
                if pos not in self._held():
                    continue
            # Phase 7 runner: after TP1, HOLD the rest as a runner (no hard +150% close). Exit only
            # on coherent distribution, a wide expiry-aware trail, or an optional hard ceiling.
            if config.RUNNER_ENABLED and pos.get('tp1_done'):
                dp = self._position_dist_prob(pos, mark, metrics_by.get(pos['symbol']), now,
                                              max(0.0, peak - pnl))
                if config.DIST_PROB_ENABLED and dp >= config.DIST_PROB_EXIT:
                    self._close(pos, mark, now, reason='DISTRIBUTION_EXIT', board=board,
                                metric=metrics_by.get(pos['symbol']))
                    continue
                if config.RUNNER_MAX_PCT and pnl >= config.RUNNER_MAX_PCT:
                    self._close(pos, mark, now, reason='STRUCTURAL_TP2', board=board,
                                metric=metrics_by.get(pos['symbol']))
                    continue
                if (peak >= config.RUNNER_TRAIL_ARM_PCT
                        and pnl <= peak - config.RUNNER_TRAIL_GIVEBACK_PCT):
                    self._close(pos, mark, now, reason='RUNNER_TRAIL', board=board,
                                metric=metrics_by.get(pos['symbol']))
                continue                      # runner-managed — skip the fixed TP2/trail below
            if pnl >= config.TAKE_PROFIT_2_PCT:
                self._close(pos, mark, now, reason='STRUCTURAL_TP2', board=board,
                            metric=metrics_by.get(pos['symbol']))
                continue
            if peak >= config.TRAIL_ARM_PCT and pnl <= peak - config.TRAIL_GIVEBACK_PCT:
                self._close(pos, mark, now, reason='TRAIL_GIVEBACK', board=board,
                            metric=metrics_by.get(pos['symbol']))

    # ── P3: stateful opposite-side reversal management (owns opposite-side exits) ──
    def _manage_reversal(self, metrics_by, now) -> None:
        """Escalate a per-held-position ReversalCluster from opposite-side evidence; at
        REVERSAL_ACTIVATED, EXIT_FLAT (invalidate) or EXIT_REVERSE (invalidate + let the opposite
        side enter). A single opposite print never flips the position (§11-15, safeguard #10)."""
        rev = self.state.setdefault('reversal', {})
        for pos in list(self._held()):
            sym, side = pos['symbol'], pos['side']
            m = metrics_by.get(sym)
            if not m:
                continue
            opp = 'PUT' if side == 'CALL' else 'CALL'
            oc = opp.lower()
            opp_q = m.get(oc) or {}
            entry = pos.get('entry_price') or 0.0
            mark = self._current_mark(pos) or entry
            pnl = (mark - entry) / entry if entry else 0.0
            ev = {'opp_abnormal': m.get(oc + '_z', 0.0) >= config.REV_OPP_Z,
                  'opp_control': m.get(oc + '_control', 0.0),
                  'opp_premium_accept': m.get(oc + '_acceleration', 0.0) > 0,
                  'cross_strike': (opp_q.get('n_active', 0) >= 2 or 'CHAIN' in (opp_q.get('class') or '')),
                  'incumbent_progress_fail': pnl < 0,
                  'opp_strike': opp_q.get('top_strike')}
            key = f"{sym}|{side}"
            cl = rev.get(key) or reversal.new_cluster(sym, side)
            prev = cl['state']
            cl = reversal.update(cl, ev, now)
            rev[key] = cl
            if cl['state'] != prev:
                logger.info("REVERSAL %s %s->%s (opp=%s events=%d strikes=%s)", key, prev,
                            cl['state'], opp, cl['events'], cl['strikes'])
            opp_slot = f"{sym}|{opp}"
            opp_qualifies = (opp_slot not in self.state.get('entered_today', [])
                             and ev['opp_control'] >= config.REV_ACTIVATE_CONTROL)
            out = reversal.outcome(cl, opp_qualifies)
            if out != 'HOLD':
                logger.info("REVERSAL %s %s → %s (opp %s qualifies=%s)", key, cl['state'], out,
                            opp, opp_qualifies)
                self._close(pos, mark, now, reason='REVERSAL_ACTIVATED', metric=m)
                rev.pop(key, None)
                if out == 'EXIT_FLAT':      # invalidate but do NOT reverse — block the opposite slot today
                    self.state.setdefault('entered_today', []).append(opp_slot)

    # ── entries (Route: new ACTIVE wave, §16 contract gates) ──────────────────────

    def _hard_vetoes(self, c, m, now) -> list:
        """item 17: collect ALL hard gates that would block this candidate — not just the first — so the
        Decision Ledger can expose every blocker at once. Best-effort mirror of the hard gates in
        _open_wave (the ones that apply in both route and conjunctive modes)."""
        v = []
        if not c or not c.get('best'):
            return ['DATA_QUALITY_REJECTION']
        if config.BARSHOCK_GATE_ENABLED:
            ok, why = barshock.entry_gate(c.get('barshock'))
            if not ok:
                v.append(f'barshock:{why}')
        inv = c.get('inventory') or {}
        if config.INVENTORY_ENABLED and config.INV_PASS_ON_HIGH and inv.get('ambiguity') == 'HIGH':
            v.append('INVENTORY_AMBIGUITY_PASS')
        pkg = c.get('package') or {}
        if config.PACKAGES_ENABLED and config.PKG_VETO_ENABLED and pkg.get('leg'):
            v.append(f"PACKAGE_LEG:{pkg.get('label')}")
        if config.PORTFOLIO_RISK_ENABLED and config.PORT_GATE_ENABLED:
            pg = portfolio.gate(c['side'], self._held())
            if not pg['ok']:
                v.append('PORTFOLIO_CONCENTRATION_LIMIT')
        hyp = c.get('hypotheses') or {}
        if config.HYPOTHESES_ENABLED and config.HYP_PASS_ENABLED and hyp.get('ambiguous'):
            v.append('HYPOTHESIS_AMBIGUITY_PASS')
        try:
            ok, why = execution.check_executable(c['best'], now)
            if not ok:
                v.append(f'execution:{why}')
        except Exception:
            pass
        return v

    def _log_decision(self, now, sym, side, m, c, decision, owner, veto_reasons, expiry=None,
                      strike=None, wave=None) -> None:
        """item 17: append one immutable Decision Ledger record. Never disrupts trading."""
        if not config.DECISION_LEDGER_ENABLED:
            return
        try:
            ew = {}
            if wave is not None:
                age = None
                if getattr(wave, 'ew_opened_at', None) is not None:
                    try:
                        age = round((now - wave.ew_opened_at).total_seconds()) if hasattr(wave.ew_opened_at, 'total_seconds') \
                              else round(now.timestamp() - float(wave.ew_opened_at))
                    except Exception:
                        age = None
                ew = {'entry_window': ('OPEN' if getattr(wave, 'ew_open', False) else 'CLOSED'),
                      'entry_window_reason': getattr(wave, 'ew_reason', None),
                      'entry_window_age_s': age, 'campaign_state': getattr(wave, 'state', None)}
            rec = decision_ledger.build_record(
                now=now, ticker=sym, side=side, metric=m, cand=c, decision=decision, owner=owner,
                veto_reasons=veto_reasons, code_version=self._code_version, config_hash=self._config_hash,
                candidate_expiry=expiry, candidate_strike=strike, entry_window=ew,
                runtime_flags={'MULTI_CAMPAIGN': config.MULTI_CAMPAIGN_ENABLED,
                               'REVERSAL': config.REVERSAL_ENABLED,
                               'QUALIFIED_CONTROL': config.QUALIFIED_CONTROL_ENABLED,
                               'ENTRY_ROUTES': config.ENTRY_ROUTES_ENABLED})
            decision_ledger.append(config.DECISION_LEDGER_FILE, rec)
        except Exception:
            logger.warning("decision-ledger write failed (non-fatal)", exc_info=True)

    def _maybe_near_miss_alert(self, sym, side, c, m, dec, now) -> None:
        """Audit item 2: RESEARCH-ONLY 🟡 WATCH alert for a genuinely-scored near-miss (no hard veto,
        route in the approved set, qualified control, low distribution, value not EXTENDED/MATURE).
        Never places an order. Throttled per (ticker,side). Restores visibility while 0.55 stays the
        execution boundary — and collects live evidence on whether 0.50-0.54 candidates are tradeable."""
        if not config.NEAR_MISS_ALERT_ENABLED:
            return
        route = dec.get('route')
        if route not in config.NEAR_MISS_ROUTES:
            return
        vs = (c.get('value') or {}).get('value_state')
        if vs in ('EXTENDED', 'MATURE'):
            return
        if (c.get('dist_prob') or 0.0) > config.NEAR_MISS_MAX_DIST_PROB:
            return
        qcs = m.get('qc_strength', 0.0) or 0.0                 # qualified control strength on the dom side
        ctrl = m.get('call_control', 0.0) if side == 'CALL' else m.get('put_control', 0.0)
        if max(qcs, ctrl or 0.0) < 0.55:                       # some real directional control required
            return
        key = (sym, side)
        # dedup: one WATCH per campaign, re-alerting ONLY on a MATERIAL score improvement — not a fresh
        # card every interval for the same stagnant candidate (the repeated NVDA 210C cards).
        last = self._nm_ts.get(key)
        last_score = self._nm_last_score.get(key)
        improved = last_score is None or (dec['score'] - last_score) >= config.NEAR_MISS_REALERT_DELTA
        if last is not None:
            if not improved:
                return                                        # same campaign, no material change → silent
            if (now - last).total_seconds() < config.NEAR_MISS_MIN_INTERVAL_S and last_score is not None:
                return                                        # too soon even for an improvement
        self._nm_last_score[key] = dec['score']
        self._nm_ts[key] = now
        self._attr['near_miss_alerts'] += 1
        best = c.get('best') or {}
        drag = ', '.join(f"{k} {v:+.2f}" for k, v in (dec.get('top_drag') or [])[:2])
        try:
            notify.near_miss_card(sym=sym, side=side, strike=best.get('strike'), route=route,
                                  score=dec['score'], threshold=config.ENTRY_ROUTE_MIN_SCORE,
                                  shortfall=dec.get('shortfall'), value_state=vs,
                                  qual_control=max(qcs, ctrl or 0.0), dist_prob=c.get('dist_prob'),
                                  archetype=dec.get('archetype'), info_rank=m.get('info_mass_rank'),
                                  acceptance=(c.get('acceptance') or {}).get('label'), top_drag=drag, now=now)
        except Exception:
            logger.warning("near-miss alert card failed (non-fatal)", exc_info=True)
        logger.info("NEAR-MISS-WATCH %s %s %s route=%s score=%.3f/%.3f value=%s qctrl=%.2f drag=[%s] "
                    "— RESEARCH ONLY, no entry", sym, side, best.get('strike'), route, dec['score'],
                    config.ENTRY_ROUTE_MIN_SCORE, vs, max(qcs, ctrl or 0.0), drag)

    def _open_wave(self, en, cand, ranked, market_mass, now) -> None:
        sym, side, w, m = en['ticker'], en['side'], en['wave'], en['metric']
        c = cand.get(sym)
        if not c or not c.get('best'):
            return 'DATA_QUALITY_REJECTION'
        best = c['best']
        # EntryWindow: record the premium at which the window first became actionable (for the ledger's
        # PremiumAtFirstInformationEvent vs current-poll comparison and convexity-since-open reads).
        if getattr(w, 'ew_opened_price', None) is None and best.get('mark'):
            w.ew_opened_price = best.get('mark')
        # §10 archetype routes: when enabled, a candidate that clears the hard vetoes AND scores
        # enough total expected-asymmetry on its archetype route ENTERS — the soft conjunctive gates
        # below are bypassed (each is guarded by `not route_ok`). Microstructure vetoes still apply.
        route_ok = False
        if config.ENTRY_ROUTES_ENABLED:
            dec = entry.decide(c, m)
            c['route_decision'] = dec           # audit: carry the full decomposition into the ledger
            wid = en.get('wave_id')
            self._attr['evaluated'].add(wid)
            if not dec['pass']:
                drag = ' '.join(f"{k}-{v:.2f}" for k, v in (dec.get('top_drag') or []))
                if dec['score_status'] == 'HARD_VETO':
                    # audit item 1: a veto is NOT a 0.00 score — report raw_score + status + all vetoes.
                    for fam in dec.get('hard_vetoes') or []:
                        self._attr['hard_veto'][fam].add(wid)
                    logger.info("ENTRY-REJECT %s %s route=%s HARD_VETO=%s raw_score=%.2f (%s) top_drag=[%s]",
                                sym, side, dec.get('route'), ','.join(dec.get('hard_vetoes') or []),
                                dec.get('raw_score') or 0.0, dec['reason'], drag)
                else:
                    # genuinely SCORED but below threshold — the near-miss population.
                    self._attr['qualified'].add(wid)
                    logger.info("ENTRY-REJECT %s %s route=%s asym=%.3f<%.3f (%s) | contrib=%s | top_drag=[%s]",
                                sym, side, dec.get('route'), dec['score'], config.ENTRY_ROUTE_MIN_SCORE,
                                dec['reason'], dec.get('contributions'), drag)
                    if dec['score'] >= config.NEAR_MISS_MIN_SCORE:
                        self._attr['near_miss'][dec.get('route')].add(wid)
                        self._maybe_near_miss_alert(sym, side, c, m, dec, now)
                return dec['reason']
            route_ok = True
            self._attr['qualified'].add(wid)
            self._attr['route_passed'].add(wid)     # ROUTE_PASSED — NOT yet entry-eligible (post-route
            #                                          hard gates below can still veto: barshock, inventory
            #                                          PASS, package, portfolio, execution, late-0DTE, hyp)
            logger.info("ENTRY-ROUTE %s %s %s asym=%.3f (archetype=%s) — soft gates bypassed",
                        sym, side, dec['route'], dec['score'], dec['archetype'])
            # P1 overnight hysteresis: a surviving opposite-side campaign raises the bar (Friday's
            # first AMZN put must overcome Thursday's funded call campaign).
            if config.CROSS_SESSION_MEMORY_ENABLED:
                opp = campaign_store.opposite_inherited(self.state.get('campaigns', {}), sym, side)
                need = config.ENTRY_ROUTE_MIN_SCORE + config.CROSS_SESSION_OPP_BUMP
                if opp and dec['score'] < need:
                    logger.info("ENTRY-REJECT %s %s overnight-hysteresis: opposite %s campaign %s "
                                "intact (asym %.2f < %.2f)", sym, side, opp['side'],
                                opp['campaign_id'], dec['score'], need)
                    return 'MISSED_DUE_TO_OVERNIGHT_HYSTERESIS'
        # P2 barshock entry-gate: require a genuine abnormal event on the traded side before entering —
        # background flow (no significant BarVolumeShock) or a sub-floor tiny-baseline spike is NOT a
        # tradeable event. A HARD evidence gate: applies in BOTH route and conjunctive modes (like the
        # microstructure vetoes). Degrades to ALLOW when no barshock read exists. Default OFF.
        if config.BARSHOCK_GATE_ENABLED:
            bs_ok, bs_why = barshock.entry_gate(c.get('barshock'))
            if not bs_ok:
                logger.info("ENTRY-REJECT %s %s barshock-gate=%s (no genuine event)", sym, side, bs_why)
                return 'ECONOMICALLY_VALID_REJECTION'
        # Addendum #1,10 — INVENTORY AMBIGUITY PASS (first-class abstain): a fresh print colliding with
        # prior inventory at a materially different cost basis (probable unwind / distribution-into-
        # strength) is high-ambiguity — passing is a feature, not a failure. HARD gate (both modes).
        inv = c.get('inventory') or {}
        if config.INVENTORY_ENABLED and config.INV_PASS_ON_HIGH and inv.get('ambiguity') == 'HIGH':
            logger.info("ENTRY-ABSTAIN %s %s inventory ambiguity HIGH (%s, basis $%.2f mfe=%.4f) — PASS",
                        sym, side, inv.get('state'), inv.get('basis_vwap') or 0.0, inv.get('mfe') or 0.0)
            return 'INVENTORY_AMBIGUITY_PASS'
        # Addendum #7 — PACKAGE LEG veto (default OFF; soft-discounts EV otherwise): a size-matched
        # spread/roll leg is not clean outright directional flow.
        pkg = c.get('package') or {}
        if config.PACKAGES_ENABLED and config.PKG_VETO_ENABLED and pkg.get('leg'):
            logger.info("ENTRY-REJECT %s %s package=%s (%s) — not clean outright flow",
                        sym, side, pkg.get('label'), pkg.get('reason'))
            return 'PACKAGE_LEG_REJECTION'
        # Addendum #18 — PORTFOLIO correlation risk gate: campaign discovery is unconstrained, but a
        # new correlated same-direction leg that would over-concentrate the (one-factor) Mag-7 book is
        # a risk veto. HARD gate (both modes); never forces an exit or blocks holding.
        if config.PORTFOLIO_RISK_ENABLED and config.PORT_GATE_ENABLED:
            pg = portfolio.gate(side, self._held())
            if not pg['ok']:
                logger.info("ENTRY-REJECT %s %s portfolio-risk: %s", sym, side, pg['reason'])
                return 'PORTFOLIO_CONCENTRATION_LIMIT'
        strict = config.OPENING_STRICT_MULT if is_opening_strict(now) else 1.0
        # §13 opening rework: instead of a blanket 1.4× penalty on every opening candidate, waive it
        # for a genuinely clean opening campaign — one that persists beyond the auction, shows a
        # positive short response, or has adjacent-strike confirmation. Default OFF.
        if config.OPENING_QUALITY_ENABLED and is_opening_strict(now):
            vp = c.get('vp') or {}
            surf = c.get('surface') or {}
            if (vp.get('burst', 0) >= config.VP_BURST_PERSIST_MIN
                    or (c.get('resp_event') or 0.0) > 0 or surf.get('breadth', 0) >= 2):
                logger.info("OPENING-QUALITY %s %s clean opening (burst=%s resp=%+.0f%% breadth=%s) "
                            "— normal floor", sym, side, vp.get('burst'),
                            100 * (c.get('resp_event') or 0.0), surf.get('breadth'))
                strict = 1.0
        # Chain-led events must clear a SUBSTANTIALLY higher notional floor than single strikes —
        # a synchronised institutional chain, not three mediocre strikes summed (spec §5/§13).
        is_chain = 'CHAIN' in (c.get('event_class') or '')
        notional_floor = config.GATE_MIN_EVENT_NOTIONAL * strict * (config.CHAIN_NOTIONAL_MULT if is_chain else 1.0)
        if not route_ok and c['notional'] < notional_floor:
            # P5 surface gate: a genuine broad ticker-level campaign (AMZN ladder) can fail the
            # single-contract notional floor even though capital IS concentrating across the surface.
            # When SURFACE_GATE_ENABLED, let a tradeable broad/ladder surface clear the floor on its
            # breadth-adjusted LADDER mass instead of the one contract's notional (spec §23-25).
            surf = c.get('surface') or {}
            broad_ok = (config.SURFACE_GATE_ENABLED
                        and strikesurf.is_tradeable_surface(surf.get('classification'))
                        and surf.get('breadth', 0) >= config.SURFACE_BROAD_BREADTH
                        and surf.get('breadth_adjusted_strength', 0.0) >= notional_floor)
            if not broad_ok:
                logger.info("ENTRY-REJECT %s %s notional $%.0f < %s min $%.0f", sym, side,
                            c['notional'], 'CHAIN' if is_chain else 'single', notional_floor)
                # §12: was it a thin single strike, or a cluster the aggregation would have covered?
                return valuemod.notional_reject_label(
                    c['notional'], surf.get('breadth_adjusted_strength', 0.0), notional_floor)
            logger.info("ENTRY-ALLOW %s %s broad-surface campaign overrides single-strike notional "
                        "(%s breadth=%d ladder=$%.0f)", sym, side, surf.get('classification'),
                        surf.get('breadth'), surf.get('breadth_adjusted_strength'))
        # v3-audit item 5: ONE authoritative value owner. When ContractValueMemory has real history it
        # OWNS the CHEAP/FAIR/EXTENDED/MATURE decision — EXTENDED/MATURE rejects, CHEAP/FAIR allows, and
        # the session-low distance is merely a logged component (not an independent veto that can fight
        # ValueMemory). Only when there is NO value history does the legacy session-low gate govern.
        vm = c.get('value') or {}
        value_owned = (config.VALUE_MEMORY_ENABLED and config.VALUE_STATE_AUTHORITATIVE
                       and vm.get('n', 0) >= config.BARSHOCK_MIN_BINS
                       and vm.get('value_state') not in (None, 'UNKNOWN'))
        if not route_ok and value_owned:
            vs = vm.get('value_state')
            if vs in ('EXTENDED', 'MATURE'):
                logger.info("ENTRY-REJECT %s %s value=%s (%s; session-low dist %.2f is a component) "
                            "— too rich by robust value", sym, side, vs, vm.get('reason'), c['dist_low'])
                return 'MISSED_DUE_TO_PRICE_EXTENSION'
            logger.info("VALUE-OK %s %s value=%s owns the decision (session-low dist %.2f = component only)",
                        sym, side, vs, c['dist_low'])
        elif not route_ok and c['dist_low'] > config.GATE_MAX_DIST_FROM_LOW:
            # no value history yet → legacy session-low gate. §11: distinguish 'discovered early,
            # executed late' (fixable latency) from 'only recognised after it extended' (valid reject).
            chased_label = valuemod.classify_chased(c.get('rel_premium'))
            logger.info("ENTRY-REJECT %s %s chased (%.2f, drift=%.2fx → %s) [no value history]", sym, side,
                        c['dist_low'], c.get('rel_premium') or 1.0, chased_label)
            return chased_label
        ok, why = execution.check_executable(best, now)
        if not ok:
            logger.info("ENTRY-REJECT %s %s execution=%s", sym, side, why)
            return 'DATA_QUALITY_REJECTION'
        if not route_ok and not c['freshness']['tradeable']:
            logger.info("ENTRY-REJECT %s %s freshness=%s (+%.0f%%)", sym, side,
                        c['freshness']['label'], 100 * c['freshness']['run_pct'])
            return 'MISSED_DUE_TO_PRICE_EXTENSION'
        # ACCUMULATION vs DISTRIBUTION — reject heavy volume that is NOT expanding the premium
        # (distribution / exit flow / late chasing). Only accumulation waves may open a trade.
        # v3-canonicalization item 5: premium ACCEPTANCE > required appreciation. Exceptional flow being
        # ABSORBED without contract-price deterioration is tradeable even if premium isn't yet rising —
        # accumulation does not require price to already have moved.
        absorbing = (config.ACCEPT_ABSORPTION_ENABLED
                     and (c.get('acceptance') or {}).get('label') == 'ABSORPTION'
                     and (c.get('resp_event') or 0.0) >= 0)
        if not route_ok and config.REQUIRE_ACCUMULATION and not c.get('accumulation') and not absorbing:
            logger.info("ENTRY-REJECT %s %s %s (%s, resp=%+.0f%% shape=%s)", sym, side,
                        c.get('acc_label'), c.get('shape'), 100 * (c.get('resp_event') or 0),
                        c.get('shape'))
            return 'ECONOMICALLY_VALID_REJECTION'
        if absorbing and not c.get('accumulation'):
            logger.info("ENTRY-ALLOW %s %s premium ABSORPTION accepted (resp=%+.0f%%) — accumulation "
                        "does not require prior appreciation (item 5)", sym, side, 100 * (c.get('resp_event') or 0))
        # P4 archetype gate: apply archetype-specific ENTRY expectations. Only a recognized
        # ACCUMULATION archetype may open a trade — a DISTRIBUTION shape (exit flow) or an
        # UNCLASSIFIED one (no coherent signature) is rejected even if the earlier gates passed
        # (spec §10). Default OFF, so validated behaviour is unchanged until enabled.
        arch_lbl = (c.get('archetype') or {}).get('archetype')
        if not route_ok and config.ARCHETYPE_GATE_ENABLED and arch_lbl in ('DISTRIBUTION', 'UNCLASSIFIED', None):
            logger.info("ENTRY-REJECT %s %s archetype=%s (not a recognized accumulation shape)",
                        sym, side, arch_lbl)
            return 'MISSED_DUE_TO_ARCHETYPE_MISCLASSIFICATION'
        # §14/§15 — the unified campaign verdict: is this a genuine institutional campaign starting
        # while convexity is still cheap? This is THE entry decision, not another threshold.
        camp = (campaign.assess(m, c, self._campaign_ctx(sym, now)) if config.CAMPAIGN_ENABLED
                else {'confirmed': True, 'score': 0.0, 'posterior': 1.0, 'thesis': '', 'missing': []})
        if not route_ok and not camp['confirmed']:
            miss = camp.get('missing') or []
            reason = ('MISSED_DUE_TO_RANK_REQUIREMENT' if 'leadership' in miss
                      else 'MISSED_DUE_TO_CONTROL_CONFIRMATION' if 'control' in miss
                      else 'MISSED_DUE_TO_PERSISTENCE_LOGIC' if ('waking' in miss or 'accumulation' in miss)
                      else 'MISSED_DUE_TO_POSTERIOR_GATE')
            logger.info("ENTRY-REJECT %s %s not-a-campaign (missing=%s score=%.0f post=%.2f)", sym, side,
                        ','.join(camp['missing']) or 'score', camp['score'], camp.get('posterior', 0.0))
            return reason
        # Joint distribution probability veto — heavy activity that is more likely distribution
        # than accumulation is rejected even if the five linear signals line up.
        post = camp.get('posterior', 1.0)
        dist_prob = c.get('dist_prob', 0.0)
        if not route_ok and config.DIST_PROB_ENABLED and dist_prob > config.DIST_PROB_MAX_ENTRY:
            logger.info("ENTRY-REJECT %s %s distribution p=%.2f > %.2f", sym, side,
                        dist_prob, config.DIST_PROB_MAX_ENTRY)
            return 'ECONOMICALLY_VALID_REJECTION'
        # Delta-adjusted notional floor (directional exposure, not just gross dollars).
        if (not route_ok and config.DELTA_ADJ_ENABLED and config.DELTA_ADJ_NOTIONAL_MIN > 0
                and c.get('delta_adj_notional', 0.0) < config.DELTA_ADJ_NOTIONAL_MIN):
            logger.info("ENTRY-REJECT %s %s delta-adj notional $%.0f < $%.0f", sym, side,
                        c.get('delta_adj_notional', 0.0), config.DELTA_ADJ_NOTIONAL_MIN)
            return 'MISSED_DUE_TO_SINGLE_STRIKE_NOTIONAL'
        # IV confirmation (only when we actually have IV and it is required): reject a rolling-over IV.
        if (not route_ok and config.REQUIRE_IV_CONFIRM and c.get('iv_slope') is not None
                and c['iv_slope'] < config.IV_FIRM_SLOPE):
            logger.info("ENTRY-REJECT %s %s IV rolling over (dIV=%.4f)", sym, side, c['iv_slope'])
            return 'ECONOMICALLY_VALID_REJECTION'
        # Expected-value timing — enter at the earliest positive-asymmetry moment, not maximum
        # confirmation. EV = P(continue)·RemainingConvexity − P(false)·ExpectedLoss.
        run = c['freshness']['run_pct']
        rc_fresh = max(0.0, 1.0 - run / max(config.FRESH_EXTENDED_PCT, 1e-9))
        d = c['dist_low']
        rc_cheap = (max(0.0, min(1.0, 1.0 - (d - 1.0) / max(config.GATE_MAX_DIST_FROM_LOW - 1.0, 1e-9)))
                    if d >= 1 else 1.0)
        remaining_convexity = 0.6 * rc_fresh + 0.4 * rc_cheap
        p_false = dist_prob if config.DIST_PROB_ENABLED else (1.0 - post)
        # P(continue) blends the Bayesian posterior with the lifecycle continuation probability
        # (self-sustainability + efficiency trend + premium persistence + control).
        cont = c.get('cont_prob', post)
        w_cont = config.EV_CONTINUATION_WEIGHT
        p_continue = (1.0 - w_cont) * post + w_cont * cont
        # Graduated soft discounts to P(continue) from the economic-intent reads. Each is a MULTIPLIER
        # (never a hard veto here — the hard abstains are above): MED inventory ambiguity / spread-roll
        # leg (#1,7), convexity-dominant hedge flow (#13), cross-expiry conflict (#8), and macro/vol
        # regime (#17). Cross-expiry AGREEMENT adds a small bonus.
        hedge_r = c.get('hedge') or {}
        hyp = c.get('hypotheses') or {}
        xexp = (expiry_value.cross_expiry_direction(side, self._expiry_rows.get(sym))
                if config.CROSS_EXPIRY_DIR_ENABLED else {'verdict': 'NEUTRAL', 'mult': 1.0, 'bonus': 0.0})
        reg = (regimemod.assess(now.date()) if config.REGIME_ENABLED else {'regime': 'NORMAL', 'mult': 1.0})
        pi_disc = 1.0
        if config.INVENTORY_ENABLED:
            pi_disc *= inv.get('discount', 1.0)
        if config.PACKAGES_ENABLED:
            pi_disc *= pkg.get('discount', 1.0)
        if config.HEDGE_FLOW_ENABLED:
            pi_disc *= hedge_r.get('mult', 1.0)
        if config.CROSS_EXPIRY_DIR_ENABLED:
            pi_disc *= xexp.get('mult', 1.0)
        if config.REGIME_ENABLED:
            pi_disc *= reg.get('mult', 1.0)
        p_continue = min(1.0, p_continue * pi_disc + (xexp.get('bonus', 0.0) if config.CROSS_EXPIRY_DIR_ENABLED else 0.0))
        if pi_disc < 1.0 or xexp.get('bonus'):
            logger.info("ENTRY-DISCOUNT %s %s p_continue×%.2f (inv=%s pkg=%s hedge=%s xexp=%s regime=%s)",
                        sym, side, pi_disc, inv.get('ambiguity'), pkg.get('label'),
                        hedge_r.get('read'), xexp.get('verdict'), reg.get('regime'))
        # Addendum #9 — hypotheses PASS: if no hypothesis dominates (ambiguous intent), abstain. Default
        # OFF (HYP_PASS_ENABLED) so Monday observes the distribution before it gates.
        if config.HYPOTHESES_ENABLED and config.HYP_PASS_ENABLED and hyp.get('ambiguous'):
            logger.info("ENTRY-ABSTAIN %s %s hypotheses ambiguous (%s) — PASS", sym, side, hyp.get('reason'))
            return 'HYPOTHESIS_AMBIGUITY_PASS'
        # §36 — late-day 0DTE value gate: strength × activation × remaining_convexity − theta_risk.
        if config.EXPIRY_VALUE_ENABLED and config.LATE0DTE_GATE_ENABLED:
            dte0 = self._dte(sym)
            mins = self._minutes_since_open(now)
            l0 = expiry_value.late_day_0dte_value(
                dte0, mins, strength=post, activation=c.get('cont_prob', post),
                remaining_convexity=remaining_convexity)
            ok0, why0 = expiry_value.late_day_0dte_ok(l0)
            if not route_ok and not ok0:
                logger.info("ENTRY-REJECT %s %s %s", sym, side, why0)
                return 'MISSED_DUE_TO_LATE_0DTE_THETA'
        ev = campaign.expected_value(p_continue, remaining_convexity, p_false, config.EV_EXPECTED_LOSS)
        if not route_ok and config.REQUIRE_POSITIVE_EV and ev < config.EV_MIN:
            logger.info("ENTRY-REJECT %s %s negative EV=%.3f (post=%.2f conv=%.2f pF=%.2f)", sym, side,
                        ev, post, remaining_convexity, p_false)
            return 'MISSED_DUE_TO_EV_GATE'
        # Stricter EARLY-ASYMMETRY test for entering while still FORMING (fast route): a
        # not-yet-confirmed wave must clear a higher bar than a fully-ACTIVE one.
        if not route_ok and config.FORMING_ENTRY_ENABLED and w.state == 'FORMING':
            # item 9: volume is senior to price. An EXCEPTIONAL FORMING event (very high posterior) is
            # NOT spot-gated — waiting for the underlying to visibly move reprices away the convexity
            # (NVDA 222.5P). Spot may confirm/penalise confidence afterward, but must not veto the first
            # pristine informational event. Weak/ambiguous FORMING events still require spot confirm.
            spot_required = (config.FORMING_REQUIRE_SPOT_CONFIRM
                             and post < config.FORMING_SPOT_EXEMPT_POSTERIOR)
            if (post < config.FORMING_MIN_POSTERIOR or dist_prob > config.FORMING_MAX_DIST_PROB
                    or ev < config.FORMING_MIN_EV
                    or (spot_required and not c.get('spot_confirms'))):
                logger.info("ENTRY-REJECT %s %s FORMING early-asymmetry (post=%.2f dist=%.2f ev=%.3f "
                            "spot=%s)", sym, side, post, dist_prob, ev, c.get('spot_confirms'))
                return 'MISSED_DUE_TO_EV_GATE'
        expiry, spot = self._expiry.get(sym), self._spot.get(sym)
        limit = execution.limit_price(best)
        if not expiry or not limit:
            return 'DATA_QUALITY_REJECTION'
        qty = 1
        if self.exec and config.ALPACA_ENABLED:
            qty, _ = self.exec.calculate_qty(limit)
            if qty <= 0:
                logger.info("ENTRY-REJECT %s %s sizing=0", sym, side)
                return 'MISSED_DUE_TO_CAPACITY'
        occ = occ_symbol(sym, expiry, best['strike'], side)
        order = self.orders.submit_entry(occ, sym, expiry, best['strike'], side, qty, limit)
        if order is None and self.exec and config.ALPACA_ENABLED:
            return 'DATA_QUALITY_REJECTION'
        w.entry_issued = True
        if w.active_ts is None:      # entered while FORMING → anchor the min-hold at entry time
            w.active_ts = now
        # Incumbent-strength hysteresis: a strong, heavily-funded campaign starts with higher
        # CampaignConfidence, so it takes more sustained opposing evidence to erode it out.
        w.confidence = hold.initial_confidence(m.get('attention_share', 0.0), post, c.get('notional', 0.0))
        # P1: serialize the campaign so it survives session boundaries and restarts.
        if config.CROSS_SESSION_MEMORY_ENABLED:
            rec = campaign_store.record(sym, side, best['strike'], expiry.isoformat(),
                                        now.date().isoformat(), w.confidence, 'ACTIVE', c.get('notional'))
            self.state.setdefault('campaigns', {})[rec['campaign_id']] = rec

        lag = None
        if c.get('first_ts'):
            try:
                lag = round((now - datetime.fromisoformat(c['first_ts'])).total_seconds(), 0)
            except Exception:
                lag = None
        # Phase 2: detection/decision latency from the early-detection marks (WATCH/BUILDING).
        em = self.waves.early_marks(sym, side)
        _lag = lambda ts: round((now - ts).total_seconds(), 0) if ts else None
        abn_lag, watch_lag, build_lag = (_lag(em.get('first_abnormal_ts')),
                                         _lag(em.get('watch_ts')), _lag(em.get('building_ts')))
        drift = c.get('rel_premium')          # alert premium / campaign-start premium (premium drift)
        self._held().append({
            'symbol': sym, 'side': side, 'occ': occ, 'strike': best['strike'],
            'expiry': expiry.isoformat(), 'qty': qty, 'entry_price': limit,
            'peak_price': limit, 'tp1_done': False, 'opened_at': now.isoformat(),
            'wave_id': en['wave_id'], 'event_class': c['event_class'],
            'acc_label': c.get('acc_label'), 'shape': c.get('shape'),
            'resp_event': c.get('resp_event'), 'campaign_score': camp['score'],
            'posterior': post, 'dist_prob': dist_prob, 'ev': ev, 'p_continue': round(p_continue, 3),
            'resp_eff': c.get('resp_eff'), 'rel_premium': c.get('rel_premium'),
            'iv_slope': c.get('iv_slope'), 'entry_state': w.state,
            'self_sust': c.get('self_sust'), 'cont_prob': c.get('cont_prob'),
            'eff_trend': c.get('eff_trend'), 'shakeout': c.get('shakeout'),
            'freshness': c['freshness']['label'], 'detection_lag_s': lag,
            'eas': c.get('eas'), 'early_state': em.get('state'), 'watch_lag_s': watch_lag,
            'building_lag_s': build_lag, 'abnormal_lag_s': abn_lag, 'premium_drift': drift,
            'archetype': (c.get('archetype') or {}).get('archetype'),
            'surface_class': (c.get('surface') or {}).get('classification'),
            'quality': c.get('quality'),
            'acceptance': (c.get('acceptance') or {}).get('label'),
            'barshock_event': (c.get('barshock') or {}).get('event_type'),
            'inventory_state': (c.get('inventory') or {}).get('state'),
            'inventory_ambiguity': (c.get('inventory') or {}).get('ambiguity'),
            'inventory_depletion': ((c.get('inventory') or {}).get('depletion') or {}).get('state'),
            'package': (c.get('package') or {}).get('label'),
            'hedge_read': (c.get('hedge') or {}).get('read'),
            'premium_driver': (c.get('decomp') or {}).get('driver'),
            'hypothesis': (c.get('hypotheses') or {}).get('top'),
            'hypothesis_p': (c.get('hypotheses') or {}).get('top_p'),
            'entry_score': m['attention_score'], 'entry_z': m['mass_z'],
            'entry_share': m['attention_share'], 'entry_rank': m['rank'],
            'entry_control': round(m['call_control'] if side == 'CALL' else m['put_control'], 3),
        })
        mode = 'LIVE' if (self.exec and config.ALPACA_ENABLED) else 'SHADOW'
        logger.info("[%s] ENTER %s %s %g x%d @ $%.2f  NEW WAVE %s (%s share=%.0f%% z=%.1f "
                    "ctrl=%.2f resp=%+.0f%% shape=%s fresh=%s lag=%ss | %s post=%.2f dist=%.2f "
                    "ev=%.2f eff=%.2f cont=%.2f sust=%.2f %s)",
                    mode, sym, side, best['strike'], qty, limit, en['wave_id'],
                    c.get('acc_label'), 100 * m['attention_share'], m['mass_z'],
                    m['call_control'] if side == 'CALL' else m['put_control'],
                    100 * (c.get('resp_event') or 0), c.get('shape'),
                    c['freshness']['label'], lag, w.state, post, dist_prob, ev,
                    c.get('resp_eff') or 0.0, c.get('cont_prob') or 0.0,
                    c.get('self_sust') or 0.0, c.get('eff_trend') or '')
        if camp.get('thesis'):
            logger.info("  %s (campaign score %.0f)", camp['thesis'], camp['score'])
        if config.EARLY_DETECT_ENABLED:
            logger.info("  LATENCY %s %s abn->alert=%ss watch->alert=%ss build->alert=%ss "
                        "accum->alert=%ss drift=%.2fx eas=%.0f", sym, side, abn_lag, watch_lag,
                        build_lag, lag, drift or 1.0, c.get('eas') or 0.0)
        arch = c.get('archetype')
        if config.ARCHETYPE_ENABLED and arch:
            logger.info("  ARCHETYPE %s %s = %s (conf=%.2f quality=%.0f) — %s", sym, side,
                        arch['archetype'], arch['confidence'], c.get('quality') or 0.0, arch['reason'])
        surf = c.get('surface')
        if config.SURFACE_ENABLED and surf:
            logger.info("  SURFACE %s %s = %s (breadth=%d top=%.0f%% center=%s rep=%s)", sym, side,
                        surf['classification'], surf['breadth'], 100 * surf['top_share'],
                        surf['weighted_center'], surf['representative_strike'])
        acc = c.get('acceptance')
        if config.ACCEPTANCE_ENABLED and acc:
            logger.info("  FLOW %s %s premium-acceptance=%s (score=%.2f)", sym, side,
                        acc['label'], acc['score'])
        bs = c.get('barshock')
        if config.BARSHOCK_ENABLED and bs:
            logger.info("  BARSHOCK %s %s top=%g@%s shock=%.1f rel=%.1f cluster=%d %s (sig=%s)", sym,
                        side, bs['top_strike'], bs['position'], bs['shock'], bs['rel_shock'],
                        bs['cluster'], bs['event_type'], bs['significant'])
        if config.INVENTORY_ENABLED and inv:
            logger.info("  INVENTORY %s %s %s ambiguity=%s basis=$%s mfe=%.4f — %s", sym, side,
                        inv.get('state'), inv.get('ambiguity'),
                        f"{inv.get('basis_vwap'):.2f}" if inv.get('basis_vwap') else '-',
                        inv.get('mfe') or 0.0, inv.get('reason'))
        if config.PACKAGES_ENABLED and pkg and pkg.get('label') != 'OUTRIGHT_LIKELY':
            logger.info("  PACKAGE %s %s = %s (conf=%.2f) — %s", sym, side, pkg.get('label'),
                        pkg.get('confidence') or 0.0, pkg.get('reason'))
        if config.PORTFOLIO_RISK_ENABLED:
            pex = portfolio.exposure(self._held())
            logger.info("  PORTFOLIO after-entry: %d CALL / %d PUT campaigns, net Δ-notional $%s",
                        pex['n_call'], pex['n_put'], f"{pex['net_delta_notional']:,}")
        dec = c.get('decomp')
        if config.DECOMPOSE_ENABLED and dec and dec.get('driver') != 'UNKNOWN':
            logger.info("  DECOMP %s %s ΔP=%.3f driver=%s (delta=%.3f gamma=%.3f unexplained=%.3f)", sym, side,
                        dec.get('dP') or 0.0, dec['driver'], dec.get('delta_contrib') or 0.0,
                        dec.get('gamma_contrib') or 0.0, dec.get('unexplained_premium') or 0.0)
        hr = c.get('hedge')
        if config.HEDGE_FLOW_ENABLED and hr and hr.get('read') != 'NEUTRAL':
            logger.info("  HEDGE %s %s %s (dir=%.2f conv=%.2f) — %s", sym, side, hr['read'],
                        hr.get('directional_conf') or 0.0, hr.get('convexity_conf') or 0.0, hr.get('reason'))
        hy = c.get('hypotheses')
        if config.HYPOTHESES_ENABLED and hy:
            logger.info("  HYPOTHESES %s %s top=%s p=%.2f directional=%.2f%s", sym, side, hy.get('top'),
                        hy.get('top_p') or 0.0, hy.get('directional_p') or 0.0,
                        ' (AMBIGUOUS)' if hy.get('ambiguous') else '')
        notify.entry_card(self._board_ctx(ranked, market_mass), symbol=sym, side=side,
                          strike=best['strike'], expiry=expiry.isoformat(), qty=qty, price=limit,
                          row=self._board_ctx(ranked, market_mass)['by_symbol'][sym], spot=spot,
                          mode=mode, now=now)
        pos = self._held()[-1]
        self._sheet(lambda: self.sheets.log_trade_entry(pos, mode=mode))
        if config.OI_CONFIRM_ENABLED:      # store campaign fingerprint for T+1 OI confirmation
            surf = c.get('surface') or {}
            oi_confirm.record_campaign(config.OI_CONFIRM_FILE, {
                'date': now.date().isoformat(), 'symbol': sym, 'side': side, 'strike': best['strike'],
                'cluster_center': surf.get('weighted_center'), 'cluster_breadth': surf.get('breadth'),
                'today_volume': best.get('fresh_vol'), 'fresh_premium': c['notional'],
                'control': round(m['call_control'] if side == 'CALL' else m['put_control'], 3),
                'prior_oi': None})         # prior/next-day OI filled from Schwab when OI is enabled

    # ── position close/scale ─────────────────────────────────────────────────────

    def _scale_out(self, pos, mark, now, *, reason, pnl) -> None:
        qty = pos['qty']
        sell = max(1, qty // 2)
        if sell >= qty:
            self._close(pos, mark, now, reason=reason)
            return
        if self.exec and config.ALPACA_ENABLED:
            self.exec.close_position_qty(pos['occ'], sell)
        pos['qty'] = qty - sell
        pos['tp1_done'] = True
        mode = 'LIVE' if (self.exec and config.ALPACA_ENABLED) else 'SHADOW'
        logger.info("[%s] SCALE %s %s sell %d/%d @ $%.2f (%s +%.0f%%)",
                    mode, pos['symbol'], pos['side'], sell, qty, mark, reason, 100 * pnl)
        notify.scale_card(pos, sold=sell, remaining=pos['qty'], price=mark, reason=reason,
                          pnl=pnl, mode=mode, now=now)
        self._sheet(lambda: self.sheets.log_trade_scale(pos, sold=sell, price=mark, reason=reason,
                                                        pnl=pnl, mode=mode))

    def _close(self, pos, mark, now, *, reason, board=None, metric=None) -> None:
        entry = pos['entry_price']
        pnl = (mark - entry) / entry if entry else 0.0
        hold_s = None
        try:
            hold_s = round((now - datetime.fromisoformat(pos['opened_at'])).total_seconds(), 0)
        except Exception:
            pass
        mfe = round((pos.get('peak_price', entry) - entry) / entry, 4) if entry else None
        mae = round((pos.get('trough_price', entry) - entry) / entry, 4) if entry else None
        category = campaign.exit_category(reason)
        if config.RESEARCH_ARCHIVE_ENABLED:
            w = self.waves.waves.get((pos['symbol'], pos['side']))
            self.archive.write(replay.candidate_record(
                now, pos['symbol'], pos['side'], metric, None, w.state if w else None,
                'EXIT', reason, extra={'pnl': round(pnl, 4), 'hold_s': hold_s,
                                       'exit_category': category, 'decided_by': campaign.decision_path(reason),
                                       'confidence': (w.confidence if w else None),
                                       'mfe': mfe, 'mae': mae, 'entry_price': entry, 'exit_price': mark,
                                       'wave_id': pos.get('wave_id'), 'archetype': pos.get('archetype')}))
        mode = 'LIVE' if (self.exec and config.ALPACA_ENABLED) else 'SHADOW'
        # P1: a genuine exit ends the campaign; an EOD flatten does NOT (position flat, but the
        # campaign persists if the expiry survives — position persistence ≠ campaign persistence).
        if config.CROSS_SESSION_MEMORY_ENABLED and reason != 'EOD_FLATTEN':
            camps = self.state.get('campaigns', {})
            try:
                cid = campaign_store.campaign_id(pos['symbol'], pos['side'], pos['opened_at'][:10],
                                                 pos['strike'])
            except Exception:
                cid = None
            if cid in camps:
                camps[cid]['state'] = 'COMPLETED' if reason in ('STRUCTURAL_TP2', 'RUNNER_TRAIL') else 'EXITED'
                # Addendum #21 — durable end taxonomy (death vs completion) for historical memory.
                if config.CAMPAIGN_TAXONOMY_ENABLED:
                    camps[cid]['end_taxonomy'] = campaign_store.classify_end(reason, pnl=pnl, carried=False)
        self._sheet(lambda: self.sheets.log_trade_exit(pos, price=mark, reason=reason, pnl=pnl,
                                                       mode=mode, category=category, hold_s=hold_s,
                                                       mfe=mfe, mae=mae))
        if self.exec and config.ALPACA_ENABLED:
            self.exec.close_position_qty(pos['occ'], pos['qty'])
        self.orders.clear(pos['occ'])
        self.waves.force_end(pos['symbol'], pos['side'], now, reason=reason, metric=metric)
        if pos in self._held():
            self._held().remove(pos)
        mode = 'LIVE' if (self.exec and config.ALPACA_ENABLED) else 'SHADOW'
        logger.info("[%s] EXIT %s %s x%d @ $%.2f (%s %s%.0f%%)  wave=%s  decided_by=%s  CAMPAIGN ENDED: %s",
                    mode, pos['symbol'], pos['side'], pos['qty'], mark, reason,
                    '+' if pnl >= 0 else '', 100 * pnl, pos.get('wave_id'),
                    campaign.decision_path(reason), campaign.campaign_end(reason))
        notify.exit_card(pos, price=mark, reason=reason, pnl=pnl, mode=mode,
                         board=board if board is not None else {}, now=now)
        state.save(self.state)

    def _current_mark(self, pos):
        snaps = self._snaps.get(pos['symbol']) or {}
        q = snaps.get((pos['strike'], pos['side']))
        if q:
            return q.get('mark') or q.get('bid')
        live = self.orders.reconcile(pos['occ'])
        return live['current_price'] if live else None

    def _find(self, ticker, side):
        return next((p for p in self._held() if p['symbol'] == ticker and p['side'] == side), None)

    def _board_ctx(self, ranked, market_mass) -> dict:
        """Compat board for the Discord cards (built from the wave ranking)."""
        bysym, rk = {}, []
        for r in ranked:
            row = {'symbol': r['symbol'], 'attention_score': r['attention_score'], 'rank': r['rank'],
                   'share': r['attention_share'], 'premium_share': r['attention_share'],
                   'control_side': r.get('dominant_side'),
                   'control_dominance': r.get('side_dominance_quality', 0.0),
                   'shock': r.get('mass_z', 0.0)}
            bysym[r['symbol']] = row
            rk.append(row)
        return {'total_premium': round(market_mass), 'leader': ranked[0]['symbol'] if ranked else None,
                'by_symbol': bysym, 'ranked': rk}

    # ── EOD ───────────────────────────────────────────────────────────────────────

    def maybe_eod_flatten(self, now: datetime) -> None:
        if not is_eod_window(now):
            return
        if self.state.get('eod_done') == now.date().isoformat():
            return
        self.state['eod_done'] = now.date().isoformat()
        for pos in list(self._held()):
            mark = self._current_mark(pos) or pos['entry_price']
            self._close(pos, mark, now, reason='EOD_FLATTEN')
        if self.exec and config.ALPACA_ENABLED:
            self.exec.close_all_positions()
        self._attrition_report()
        state.save(self.state)

    def _attrition_report(self) -> None:
        """Audit item 3/6: EOD entry-funnel + hard-veto + near-miss breakdown, so we can see exactly
        where candidates are lost (ACTIVE_EVENT → QUALIFIED_CAMPAIGN → ENTRY_READY → ENTER)."""
        if not config.ATTRITION_REPORT_ENABLED:
            return
        a = self._attr
        hv = {k: len(v) for k, v in a['hard_veto'].items()}
        nm = {k: len(v) for k, v in a['near_miss'].items()}
        prv = {k: len(v) for k, v in a['post_route_veto'].items()}
        # Corrected funnel (audit): ROUTE_PASSED is NOT the same as entry-eligible — post-route hard
        # gates can still veto. ENTERED is the only "order submitted" stage.
        logger.info("ATTRITION-REPORT polls=%d | ACTIVE_EVENT=%d → QUALIFIED_CAMPAIGN(no route-veto)=%d "
                    "→ ROUTE_PASSED(score≥%.2f)=%d → ENTERED=%d | near-miss-alerts=%d",
                    a['polls'], len(a['evaluated']), len(a['qualified']), config.ENTRY_ROUTE_MIN_SCORE,
                    len(a['route_passed']), len(a['entered']), a['near_miss_alerts'])
        logger.info("ATTRITION-REPORT route hard-veto by reason: %s", hv or '{}')
        logger.info("ATTRITION-REPORT POST-ROUTE veto (why ROUTE_PASSED did not ENTER): %s", prv or '{}')
        logger.info("ATTRITION-REPORT near-miss (0.45-0.55) by route: %s", nm or '{}')
        try:
            notify.send(f"📊 Jakenew EOD attrition — ACTIVE {len(a['evaluated'])} → qualified "
                        f"{len(a['qualified'])} → route-passed {len(a['route_passed'])} → entered "
                        f"{len(a['entered'])} | post-route veto {prv or '{}'} | route-veto {hv or '{}'}")
        except Exception:
            pass
