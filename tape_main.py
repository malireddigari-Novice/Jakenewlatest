"""
Tape lane — trade-level options-flow RESEARCH collector (flow handoff). Runs beside main.py; never
places orders, never touches the Jakenew engine's state.

  python tape_main.py                 baseline job, then capture today's session until the close
  python tape_main.py --baseline-only build today's universe + baselines and exit
  python tape_main.py --bootstrap     also bootstrap name-premium histograms from REST (bounded)
  python tape_main.py --replay 2026-10-19 [--out replay.db]   replay an archived session
  python tape_main.py --annotate      attach next-session OI annotations to earlier observations

Discord delivery is OFF unless TAPE_DISCORD_ENABLED=true (confirm the data provider's redistribution
terms first). Cards are rendered and stored in the tape DB either way.
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime

import config
from data import exchange_calendar as xcal
from tape import baseline, conditions, events, settings
from tape.rest import Rest
from tape.runtime import (Collector, Recorder, build_universe, close_session, load_watches, make_pipeline,
                          register_tape_webhooks, replay, state_digest)
from tape.store import Store


def _logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('tape.log', encoding='utf-8')])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline-only', action='store_true')
    ap.add_argument('--bootstrap', action='store_true')
    ap.add_argument('--replay')
    ap.add_argument('--out')
    ap.add_argument('--annotate', action='store_true')
    a = ap.parse_args()
    _logging()
    log = logging.getLogger('tape')

    if a.replay:
        pipe = replay(a.replay, out_db=a.out)
        log.info("REPLAY %s → %s: %s", a.replay, pipe.store.db_path, dict(pipe.stats))
        log.info("REPLAY digest: %s", state_digest(pipe.store, a.replay))
        return 0

    if not (config.ALPACA_API_KEY and config.ALPACA_SECRET_KEY):
        log.error("ALPACA_API_KEY / ALPACA_SECRET_KEY missing — the tape lane needs Alpaca market data")
        return 2
    session = datetime.now(events.NY).date()
    rest = Rest()
    store = Store()
    drift = conditions.drift(rest.conditions())
    if drift:
        log.error("CONDITION-MAP DRIFT %s — provider definitions changed since %s; side reads for these letters "
                  "stay UNKNOWN until the map is reviewed", drift, conditions.COND_MAP_VERSION)
    if not xcal.is_trading_day(session) and not a.baseline_only:
        log.info("%s is not a trading day — nothing to capture", session)
        return 0
    watched = list(load_watches(store))
    contracts, denom = build_universe(store, rest, session, watched)
    universe = {}
    for occ, c in contracts.items():
        universe.setdefault(c['underlying'], []).append(occ)
    baseline.run_job(store, rest, session, universe, datetime.now(events.NY).isoformat(), bootstrap=a.bootstrap,
                     log=log.info)
    pipe = make_pipeline(store, session, contracts, denom)
    n = pipe.annotate_prior_sessions()
    log.info("OI annotations attached to %d earlier observation(s)", n)
    if a.baseline_only or a.annotate:
        store.close()
        return 0
    register_tape_webhooks()
    log.info("TAPE %s: rules %s · cond map %s · Discord %s", session, settings.RULE_VERSION,
             conditions.COND_MAP_VERSION, 'ON' if settings.DISCORD_ENABLED else 'OFF (stored only)')
    rec = Recorder(store, pipe, session)
    try:
        asyncio.run(Collector(rec, rest, contracts, session).run())
    except KeyboardInterrupt:
        log.info("interrupted")
    pipe.finish()
    close_session(store, session)
    log.info("TAPE %s done: %s", session, dict(pipe.stats))
    store.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
