"""
Decision ledger (v3-review item 17) — one immutable record per near-candidate poll. Pure + append I/O.

The single most useful debugging artifact: for every candidate that gets close to qualifying, persist
its FULL state, the decision, the owning module, and — critically — EVERY failed gate, not just the
first one. Otherwise diagnosing "why didn't TSLA fire?" degrades into serially discovering one hidden
blocker at a time.

`build_record` assembles the flat record from the metric row + candidate read + decision; `append`
writes it as one JSON line. Failures never disrupt trading (the caller wraps append). The record is a
plain dict so it survives config/version drift; `code_version` + `config_hash` stamp provenance.
"""
import json


def build_record(*, now, ticker, side, metric, cand, decision, owner,
                 veto_reasons=None, code_version=None, config_hash=None,
                 candidate_expiry=None, candidate_strike=None, runtime_flags=None,
                 entry_window=None, provenance=None) -> dict:
    m = metric or {}
    c = cand or {}
    inv = c.get('inventory') or {}
    qc = m.get('qualified_control') or {}
    hyp = c.get('hypotheses') or {}
    bs = c.get('barshock') or {}
    return {
        'ts': (now.isoformat() if hasattr(now, 'isoformat') else str(now)),
        'code_version': code_version, 'config_hash': config_hash,
        # flow handoff §10: schema/ruleset version, NY session, DTE channel, coverage, catalyst status
        **(provenance or {}),
        'ticker': ticker, 'side': side,
        # masses / control
        'raw_call_mass': round(m.get('call', {}).get('total', 0.0)) if m.get('call') else None,
        'raw_put_mass': round(m.get('put', {}).get('total', 0.0)) if m.get('put') else None,
        'qualified_call_mass': qc.get('q_call_mass'), 'qualified_put_mass': qc.get('q_put_mass'),
        'qualified_control_side': qc.get('dominant_side'), 'control_flipped': qc.get('flipped_from_raw'),
        # attention + discovery ranks (item 6: is a cheap clean event buried under expensive premium?)
        'attention_rank': m.get('rank'), 'attention_share': m.get('attention_share'),
        'info_share': m.get('info_share'), 'discovery_share': m.get('discovery_share'),
        'premium_mass_rank': m.get('premium_mass_rank'), 'info_mass_rank': m.get('info_mass_rank'),
        'discovery_rank': m.get('discovery_rank'), 'qualified_control_rank': m.get('qualified_control_rank'),
        'attention_velocity': m.get('velocity'), 'attention_acceleration': m.get('acceleration'),
        'mass_z': m.get('mass_z'),
        'baseline_n': m.get('baseline_n'), 'baseline_quality': m.get('baseline_quality'),
        # event / morphology (item 7: baseline_quality — UNSEEDED ≠ statistically-confirmed shock)
        'event_archetype': (c.get('archetype') or {}).get('archetype'),
        'bar_volume_shock': bs.get('shock'), 'relative_strike_shock': bs.get('rel_shock'),
        'cross_strike_cluster': bs.get('cluster'), 'barshock_event': bs.get('event_type'),
        'barshock_baseline_quality': bs.get('baseline_quality'),
        # intent / inventory / package / hypotheses
        'premium_acceptance': (c.get('acceptance') or {}).get('label'),
        'inventory_state': inv.get('state'), 'inventory_ambiguity': inv.get('ambiguity'),
        'inventory_depletion': (inv.get('depletion') or {}).get('state'),
        'package_hypothesis': (c.get('package') or {}).get('label'),
        'package_confidence': (c.get('package') or {}).get('confidence'),
        'package_ratio': (c.get('package') or {}).get('ratio'),
        'package_association': (c.get('package') or {}).get('association'),
        'hedge_read': (c.get('hedge') or {}).get('read'),
        'premium_driver': (c.get('decomp') or {}).get('driver'),
        'unexplained_share': (c.get('decomp') or {}).get('unexplained_share'),
        'value_state': (c.get('value') or {}).get('value_state'),
        'value_cheapness': (c.get('value') or {}).get('cheapness'),
        'top_hypothesis': hyp.get('top'), 'hypothesis_p': hyp.get('top_p'),
        'directional_p': hyp.get('directional_p'),
        # item 14: cross-feed synchronization — degrade economic inference when feeds are skewed.
        'quote_ts': c.get('quote_ts'), 'quote_skew_ms': c.get('quote_skew_ms'),
        # campaign economics
        'campaign_score': c.get('campaign_score'), 'dist_prob': c.get('dist_prob'),
        'cont_prob': c.get('cont_prob'), 'self_sust': c.get('self_sust'),
        # expression
        'candidate_expiry': candidate_expiry, 'candidate_strike': candidate_strike,
        # route-score decomposition (audit): the 7-dimension asymmetry breakdown + what dragged it down.
        # item 1: route_score is NULL under a hard veto (never 0.00) — route_score_status disambiguates,
        # route_raw_score is what it WOULD have scored, route_hard_vetoes names every veto that applied.
        'route': (c.get('route_decision') or {}).get('route'),
        'route_score': (c.get('route_decision') or {}).get('score'),
        'route_score_status': (c.get('route_decision') or {}).get('score_status'),
        'route_raw_score': (c.get('route_decision') or {}).get('raw_score'),
        'route_hard_vetoes': (c.get('route_decision') or {}).get('hard_vetoes'),
        'route_primary_veto': (c.get('route_decision') or {}).get('primary_veto'),
        'route_evidence': (c.get('route_decision') or {}).get('evidence'),
        'route_contributions': (c.get('route_decision') or {}).get('contributions'),
        'route_top_drag': (c.get('route_decision') or {}).get('top_drag'),
        'route_shortfall': (c.get('route_decision') or {}).get('shortfall'),
        # EntryWindow (2026-08-22): entry eligibility decoupled from campaign lifecycle state
        **(entry_window or {}),
        # decision — the whole point
        'decision': decision, 'owner': owner,
        'veto_reasons': list(veto_reasons or []),        # ALL gate failures, not just the first
        'runtime_flags': runtime_flags,
    }


def append(path, record) -> None:
    """Append one ledger record as a JSON line. Caller wraps in try/except — never disrupt trading."""
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, default=str) + '\n')
