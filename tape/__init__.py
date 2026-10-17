"""
Trade-level options-flow research collector (the flow handoff's tape lane).

A separate, monitored process (`tape_main.py`) that runs beside the Jakenew engine and never places
orders. It captures raw OPRA trades + quotes and SIP spot from Alpaca, keeps an append-only archive,
and derives bounded research observations: what printed, who LIKELY took liquidity (or UNKNOWN), never
who opened/closed or whether a trade has merit. See HOW_IT_WORKS.md "Tape lane".
"""
