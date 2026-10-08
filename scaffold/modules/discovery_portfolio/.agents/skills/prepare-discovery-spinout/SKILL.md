---
name: prepare-discovery-spinout
description: Prepare a hash-bound no-delete seed for a SPINOUT_READY discovery candidate when the user wants to propose a separate article or coherent-program laboratory through the factory.
---

# Prepare Discovery Spin-out

Read `workflows/discovery_portfolio_protocol.md`.  Confirm the candidate is
`SPINOUT_READY`, has a linked problem dossier, and earned spin-out through at
least one recorded round.  Complete a lab-owned copy of
`spinout_request_draft.json`, then run:

```bash
python3 scripts/discovery_portfolio.py prepare-spinout \
  --candidate-id <id> --seed-id <id> --target-lab-id <id> \
  --request <root-relative-json>
python3 scripts/validate_discovery_portfolio.py
```

Stop after preparing and reviewing the seed.  This skill does not create a
sibling lab, call the network, delete the candidate, or mark it `SPUN_OUT`.
Final transition requires a copied receipt proving that the factory-created
lab passed its own doctor, validator, and smoke eval.  The CLI parses the exact
`spinout_receipt.json` schema, re-verifies the seed package, binds seed,
candidate, target lab, and manifest digest, and requires all three gates to be
literal `true`; it still conveys no mathematical truth status or authenticated
external authorship.

Do not substitute an ordinary candidate transfer: transfers reject linked
dossiers and external artifact bindings, whereas this seed intentionally
contains the frozen dossier.
