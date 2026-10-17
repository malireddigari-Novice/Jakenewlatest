# Campaign-flow Discord card samples

> **CLEARLY LABELLED TEST DATA.** Rendered by `campaign_flow/cards.py` from constructed inputs. The ticker `XMPL` is fictitious. These are not trades, fills or market history. A real card shows only its actual recorded fill and reason.

Green = entry, red = exit. Proposals show an *Indicative quote* and *Planned contracts*. Filled cards show the *Actual fill* and *Contracts*, and an exit return is computed from actual fills only (fees excluded). Mentions are disabled (`allowed_mentions: {parse: []}`). Scores, OI zones, percentiles, windows and gate tables stay in the journal.

## ENTRY_PROPOSED

```
GREEN ENTRY · PROPOSED · awaiting fill
XMPL 345C · Oct 23
Indicative quote $2.90 · Planned contracts 2
Campaign 8f3a1b2c... · 10:02 ET
Paper simulation · Options can lose 100% · Not investment advice.
```

## ENTRY_FILLED

```
GREEN ENTRY · FILLED
XMPL 345C · Oct 23
Actual fill $2.92 · Contracts 2
Campaign 8f3a1b2c... · 10:02 ET
Paper simulation · Options can lose 100% · Not investment advice.
```

## EXIT_PROPOSED

```
RED EXIT · PROPOSED · awaiting fill
XMPL 345C · Oct 23
Indicative quote $2.55 · Planned contracts 2
Reason: Confirmed opposite put cluster
Campaign 8f3a1b2c... · 10:09 ET
Paper simulation · Options can lose 100% · Not investment advice.
```

## EXIT_FILLED (partial)

```
RED EXIT · FILLED
XMPL 345C · Oct 23
Actual fill $2.54 · Contracts 1 · Option return -13.0% (fills)
Partial execution: 1 executed, 1 still open
Reason: Confirmed opposite put cluster
Campaign 8f3a1b2c... · 10:09 ET
Paper simulation · Options can lose 100% · Not investment advice.
```

## EXIT_FILLED

```
RED EXIT · FILLED
XMPL 345C · Oct 23
Actual fill $2.50 · Contracts 1 · Option return -14.4% (fills)
Reason: Confirmed opposite put cluster
Campaign 8f3a1b2c... · 10:10 ET
Paper simulation · Options can lose 100% · Not investment advice.
```

## ENTRY_PROPOSED (opposite campaign, after full exit)

```
GREEN ENTRY · PROPOSED · awaiting fill
XMPL 340P · Oct 23
Indicative quote $1.75 · Planned contracts 2
Campaign 2c7d9e0f... · 10:11 ET
Paper simulation · Options can lose 100% · Not investment advice.
```

## EXIT_FILLED (deadline)

```
RED EXIT · FILLED
XMPL 340P · Oct 23
Actual fill $2.10 · Contracts 2 · Option return +19.3% (fills)
Reason: Planned/expiry deadline
Campaign 2c7d9e0f... · 15:30 ET
Paper simulation · Options can lose 100% · Not investment advice.
```
