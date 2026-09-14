# v0.1.0
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

# Ledger Classifier - Intelligent Contract.
# Header must end in a blank line (real GenVM v0.2.11 requirement).

from genlayer import *
import datetime
import json

STANDARDS = ("IFRS", "GAAP")
CATEGORIES = ("revenue", "capital_contribution", "intercompany_transfer", "expense", "unclassified")


def _now() -> datetime.datetime:
    return datetime.datetime.fromisoformat(gl.message_raw['datetime'])


def _classify(standard: str, sender: str, recipient: str, amount_wei: u256, memo: str) -> str:
    # The only non-deterministic step: reading a transaction's counterparties
    # and memo, then picking one label from a small fixed set. Every
    # validator classifies independently and must land on the exact same
    # normalized label (strict_eq) - a classification only enters state if
    # the committee genuinely agrees on it, not because one validator's
    # phrasing happened to get recorded first. The label is constrained to
    # CATEGORIES and normalized before comparison, mirroring how a fixed
    # enum output keeps strict_eq's exact-match semantics correct here (the
    # same reasoning Covenant Sentinel's extraction step uses for numbers -
    # see that project - applied here to a categorical label instead).
    categories_list = ", ".join(CATEGORIES)
    prompt = f"""You are classifying a treasury transaction under {standard} for accounting
purposes. Based on the details below, pick exactly ONE category from this
fixed list: {categories_list}

Sender: {sender}
Recipient: {recipient}
Amount (wei): {amount_wei}
Memo/context: {memo}

Guidance: "revenue" is payment received for goods/services provided;
"capital_contribution" is an equity/capital injection, not revenue;
"intercompany_transfer" is a movement of funds between entities under
common ownership/control, not a third-party transaction; "expense" is a
payment made for goods/services received. Use "unclassified" if the memo
and counterparties don't give enough to confidently pick one of the other
four - do not guess.

Respond with ONLY a single JSON object, nothing else, no markdown fences:
{{"category": "<one of: {categories_list}>"}}"""

    def nondet() -> str:
        result = gl.nondet.exec_prompt(prompt, response_format="json")
        if not isinstance(result, dict):
            return "unclassified"
        cat = result.get("category")
        if not isinstance(cat, str):
            return "unclassified"
        normalized = cat.strip().lower()
        return normalized if normalized in CATEGORIES else "unclassified"

    result = gl.eq_principle.strict_eq(nondet)
    assert isinstance(result, str)
    return result


@allow_storage
class ClassificationRecord:
    tx_ref: str
    sender: str
    recipient: str
    amount_wei: u256
    memo: str
    category: str
    classified_at: datetime.datetime


class LedgerClassifier(gl.Contract):
    owner: Address
    standard: str  # "IFRS" | "GAAP", pinned at deploy so classifications stay comparable
    classified_refs: TreeMap[str, bool]  # tx_ref -> True, for O(1) duplicate rejection
    records: DynArray[ClassificationRecord]

    def __init__(self, standard: str):
        assert standard in STANDARDS, f"standard must be one of {STANDARDS}"
        self.owner = gl.message.sender_address
        self.standard = standard

    @gl.public.write
    def classify_transaction(self, tx_ref: str, sender: str, recipient: str, amount_wei: u256, memo: str) -> None:
        assert gl.message.sender_address == self.owner, "only the owner can submit classifications"
        assert len(tx_ref) > 0, "tx_ref cannot be empty"
        assert len(tx_ref) <= 128, "tx_ref too long (max 128 chars)"
        assert len(memo) <= 500, "memo too long (max 500 chars)"
        # A tx_ref can only ever be classified once - resubmitting the same
        # reference (accidentally or to try a different memo until a more
        # favorable category comes back) is rejected outright, not silently
        # overwritten.
        assert tx_ref not in self.classified_refs, f"tx_ref '{tx_ref}' already classified"

        category = _classify(self.standard, sender, recipient, amount_wei, memo)

        record = self.records.append_new_get()
        record.tx_ref = tx_ref
        record.sender = sender
        record.recipient = recipient
        record.amount_wei = amount_wei
        record.memo = memo
        record.category = category
        record.classified_at = _now()

        self.classified_refs[tx_ref] = True

    @gl.public.view
    def get_state(self) -> dict:
        return {
            "owner": self.owner.as_hex,
            "standard": self.standard,
            "record_count": len(self.records),
        }

    @gl.public.view
    def is_classified(self, tx_ref: str) -> bool:
        return tx_ref in self.classified_refs

    @gl.public.view
    def get_records(self, offset: u32, limit: u32) -> list:
        total = len(self.records)
        out = []
        i = total - 1 - offset
        count = 0
        while i >= 0 and count < limit:
            r = self.records[i]
            out.append({
                "tx_ref": r.tx_ref,
                "sender": r.sender,
                "recipient": r.recipient,
                "amount_wei": r.amount_wei,
                "memo": r.memo,
                "category": r.category,
                "classified_at": r.classified_at.isoformat(),
            })
            i -= 1
            count += 1
        return out
