"""
Quick connectivity check for all three data/exec surfaces.

Run:  python check_connections.py
Verifies Alpaca market data, Alpaca account, and (optionally) Schwab OI — printing a live
spot + one attention-input row for AAPL so you can see the full Layer 1-2 pipeline working
before you start the loop.
"""
import logging
import sys

import config

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
from analysis.premium import PremiumTracker, symbol_attention_input
from data.alpaca_client import AlpacaClient
from data.alpaca_data_client import AlpacaDataClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def main() -> None:
    print("-- Alpaca market data --")
    data = AlpacaDataClient()
    ok = data.verify()
    print(f"  data feed: {'OK' if ok else 'FAILED'}")
    if ok:
        sym = 'AAPL'
        spot = data.get_spot(sym)
        expiry = data.get_nearest_expiry(sym)
        print(f"  {sym} spot={spot}  nearest expiry={expiry}")
        if spot and expiry:
            snaps = data.get_option_snapshots(sym, expiry, spot)
            tracker = PremiumTracker()
            # Two reads a moment apart so the second poll shows non-zero fresh deltas.
            tracker.contracts_with_deltas(sym, snaps)
            snaps2 = data.get_option_snapshots(sym, expiry, spot)
            contracts = tracker.contracts_with_deltas(sym, snaps2)
            ai = symbol_attention_input(contracts, spot, config.PREMIUM_BAND_PCT)
            print(f"  {sym} attention input (2nd poll): {ai}")

    print("-- Alpaca account --")
    execu = AlpacaClient()
    print(f"  account: {'OK' if execu.verify() else 'FAILED'}  "
          f"(execution {'ENABLED' if config.ALPACA_ENABLED else 'disabled'})")

    print("-- Schwab (optional, OI/structural) --")
    if not config.SCHWAB_ENABLED:
        print("  disabled via SCHWAB_ENABLED=false")
        return
    try:
        from data.schwab_client import SchwabClient
        sc = SchwabClient()
        if sc.login():
            print(f"  quote AAPL = {sc.get_quote('AAPL')}")
        else:
            print("  not authorized - run: python schwab_reauth.py")
    except Exception as exc:
        print(f"  schwab unavailable: {exc}")


if __name__ == '__main__':
    main()
