"""
Re-authorize Schwab (the refresh token expires ~weekly).

Run:  python schwab_reauth.py
Opens a browser for OAuth consent and saves a fresh token to SCHWAB_TOKEN_FILE.
Schwab is optional — it only enriches the structural (OI-target) exit; the engine runs on
Alpaca alone without it.
"""
import logging

import config
from data.schwab_client import SchwabClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

if __name__ == '__main__':
    if not config.SCHWAB_API_KEY or not config.SCHWAB_APP_SECRET:
        raise SystemExit("Set SCHWAB_API_KEY and SCHWAB_APP_SECRET in .env first.")
    client = SchwabClient()
    client.login_manual()
    # Prove it works with a live quote.
    price = client.get_quote('AAPL')
    print(f"Schwab re-auth OK — AAPL last = {price}")
