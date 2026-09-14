# Ledger Classifier

An on-chain transaction classifier for treasury/foundation accounting, built as a [GenLayer](https://genlayer.com) Intelligent Contract. A treasury owner submits a transaction's counterparties, amount, and memo; every validator independently classifies it into one of a fixed set of IFRS/GAAP categories (revenue, capital contribution, intercompany transfer, expense, or unclassified) and must reach byte-identical agreement before the classification is recorded.

**Live on GenLayer's Bradbury testnet. Testnet only - no real value anywhere in this project.**

## Why this needs GenLayer

Crypto-native treasuries and foundations need consistent, defensible transaction classification for financial reporting, but today that's a manual bookkeeping judgment call: someone reads a transaction's memo and counterparties and decides, by hand, whether it was revenue, an expense, an intercompany transfer, or a capital contribution. A plain EVM contract can't make that call - it has no way to interpret free-form context. A single off-chain classifier (a script, an API, one person's spreadsheet) reintroduces exactly the single point of judgment a defensible audit trail is supposed to avoid - whoever controls that classifier can quietly reclassify a transaction to make the books look better.

GenLayer's validator committee removes that single point of trust: every validator reads the same transaction details and independently picks one label from a fixed category set, and they must land on the exact same normalized label (`gl.eq_principle.strict_eq`) before it's recorded. If the memo is genuinely ambiguous, validators still converge - on `unclassified`, the deliberate safe default - rather than one validator's guess winning by default.

## Design: a constrained single-label classification, not open-ended judgment

The classifier is explicitly told to pick exactly one label from `("revenue", "capital_contribution", "intercompany_transfer", "expense", "unclassified")`, and any output that isn't one of those five exact strings collapses to `unclassified` before it ever reaches `strict_eq`. This is a different shape of equivalence-principle use than a numeric-extraction contract: instead of validators agreeing on a number pulled from text, they're agreeing on a single fixed enum value - which is what actually makes `strict_eq`'s exact-match semantics the right tool here rather than a limitation. A `TreeMap[str, bool]` keyed by transaction reference gives O(1) duplicate-reference rejection independent of the ordered `DynArray` used for the audit-trail listing.

## How it works

1. Owner (the treasury) deploys the contract with an accounting standard, `"IFRS"` or `"GAAP"`, pinned at construction so classifications made under it stay comparable.
2. Owner calls `classify_transaction(tx_ref, sender, recipient, amount_wei, memo)` for each transaction to classify. `tx_ref` can only ever be classified once - resubmitting the same reference (accidentally, or to fish for a different category) reverts outright rather than overwriting the record.
3. Every validator independently classifies the transaction from the submitted details and must agree on the exact label before it's recorded.
4. `get_records()` returns the full, paginated audit trail - every transaction's raw inputs alongside its recorded category, so anyone can check the classification against the original memo.

## Contract

- **Address:** [`0x418532e9a759cE71173c369C03234FBee2272F63`](https://explorer-bradbury.genlayer.com/address/0x418532e9a759cE71173c369C03234FBee2272F63) on GenLayer Bradbury Testnet (chain id `4221`)
- Source: [`contracts/ledger_classifier.py`](contracts/ledger_classifier.py)
- The live instance already has one real transaction classified through actual validator consensus (correctly classified as `revenue`), and one real replay attempt that correctly reverted with the record count unchanged - not seeded with mock data.

## Frontend

A treasury dashboard for this contract lives in a separate repo, submitted separately as a Project: [github.com/HarrisonJL/ledger-classifier-dashboard](https://github.com/HarrisonJL/ledger-classifier-dashboard).

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "genlayer-test[sim]" genvm-linter==0.11.0

genvm-lint check contracts/ledger_classifier.py
python -m pytest tests/ -v
```

Deploying a fresh instance: `npm install`, set `DEPLOYER_PRIVATE_KEY` in `.env` (gitignored, never commit a private key), then `npm run deploy` (add `DEPLOY_CHAIN=localnet` to target a local GLSim network first, or `STANDARD=GAAP` to deploy under GAAP instead of the default IFRS).

## Known limitations

- **Testnet only.** No real value anywhere in this project.
- **Owner-submitted, not fetched.** The contract classifies whatever the owner submits about a transaction - it doesn't independently fetch or verify that a transaction with those exact details actually happened on some other ledger. Pairing this with an on-chain source of truth (verifying `sender`/`recipient`/`amount_wei` against a real transaction receipt) is a natural v2 extension, not attempted here.
- **Standard is descriptive, not enforced.** Pinning `"IFRS"` or `"GAAP"` at deploy time keeps classifications comparable within one instance, but the contract doesn't independently verify the LLM actually applied that standard's specific rules versus general accounting judgment - the prompt asks for it, but that's a prompt-level instruction, not a mathematical guarantee, the same honest caveat Covenant Sentinel makes about its own guard prompt.
- **Five categories only.** Real chart-of-accounts classification has far more categories than this v1's five; the fixed small set is what makes `strict_eq`'s exact-match semantics reliable across validators - a much larger label set would need a different verification approach (e.g. `prompt_non_comparative` grading against criteria) to stay robust.

## Relationship to Covenant Sentinel and GenLayer's own examples

This is the second Intelligent Contract in a small "on-chain finance-ops trust stack," alongside [Covenant Sentinel](https://github.com/HarrisonJL/covenant-sentinel) (debt-covenant monitoring). The two intentionally use different equivalence-principle shapes - Covenant Sentinel has validators agree on an extracted *number*, this contract has them agree on a *category label* - to cover more of what `strict_eq` is actually good for, not just repeat the same pattern under a different name.
