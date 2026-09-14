"""
Deterministic unit tests for Ledger Classifier using genlayer-test's Direct
Mode, with the classification LLM call mocked out. These test the
mechanical logic (access control, duplicate rejection, state) - not
real-world classification accuracy, which needs a live key.
"""

import pytest

REVENUE = '{"category": "revenue"}'
EXPENSE = '{"category": "expense"}'
INTERCOMPANY = '{"category": "intercompany_transfer"}'
BAD_LABEL = '{"category": "made_up_category"}'
MISSING = '{"category": null}'


def _deploy(direct_vm, direct_deploy, owner, standard="IFRS"):
    direct_vm.sender = owner
    return direct_deploy("contracts/ledger_classifier.py", standard=standard)


def test_initial_state(direct_vm, direct_deploy, direct_owner):
    c = _deploy(direct_vm, direct_deploy, direct_owner)
    state = c.get_state()
    assert state["standard"] == "IFRS"
    assert state["record_count"] == 0


def test_rejects_invalid_standard(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    with pytest.raises(Exception):
        direct_deploy("contracts/ledger_classifier.py", standard="US-GAAP")


def test_only_owner_can_classify(direct_vm, direct_deploy, direct_owner, direct_alice):
    c = _deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm("classifying a treasury transaction", REVENUE)
    direct_vm.sender = direct_alice
    with pytest.raises(Exception):
        c.classify_transaction("tx1", "0xsender", "0xrecipient", 1000, "payment for services")


def test_classifies_revenue(direct_vm, direct_deploy, direct_owner):
    c = _deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm("classifying a treasury transaction", REVENUE)
    direct_vm.sender = direct_owner
    c.classify_transaction("tx1", "0xcustomer", "0xtreasury", 5000, "invoice payment for consulting services")

    assert c.get_state()["record_count"] == 1
    assert c.is_classified("tx1") is True
    records = c.get_records(0, 10)
    assert records[0]["category"] == "revenue"
    assert records[0]["tx_ref"] == "tx1"


def test_classifies_expense_and_intercompany_independently(direct_vm, direct_deploy, direct_owner):
    # mock_llm matches the first-registered pattern that matches a given
    # prompt, so two mocks sharing an identical pattern would both resolve
    # to whichever was registered first - anchor each mock on distinguishing
    # text (the interpolated memo) instead of relying on registration order.
    c = _deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.sender = direct_owner

    direct_vm.mock_llm("paid vendor invoice", EXPENSE)
    c.classify_transaction("tx1", "0xtreasury", "0xvendor", 1000, "paid vendor invoice")

    direct_vm.mock_llm("funding transfer to subsidiary", INTERCOMPANY)
    c.classify_transaction("tx2", "0xparent", "0xsubsidiary", 2000, "funding transfer to subsidiary")

    records = c.get_records(0, 10)
    assert records[0]["category"] == "intercompany_transfer"  # newest first
    assert records[1]["category"] == "expense"


def test_invalid_label_falls_back_to_unclassified(direct_vm, direct_deploy, direct_owner):
    c = _deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm("classifying a treasury transaction", BAD_LABEL)
    direct_vm.sender = direct_owner
    c.classify_transaction("tx1", "0xa", "0xb", 100, "ambiguous transaction")

    records = c.get_records(0, 10)
    assert records[0]["category"] == "unclassified"


def test_missing_category_falls_back_to_unclassified(direct_vm, direct_deploy, direct_owner):
    c = _deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm("classifying a treasury transaction", MISSING)
    direct_vm.sender = direct_owner
    c.classify_transaction("tx1", "0xa", "0xb", 100, "no context given")

    records = c.get_records(0, 10)
    assert records[0]["category"] == "unclassified"


def test_rejects_duplicate_tx_ref(direct_vm, direct_deploy, direct_owner):
    # This is the exact bug class the Covenant Sentinel review caught -
    # applied proactively here rather than found after the fact.
    c = _deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm("classifying a treasury transaction", REVENUE)
    direct_vm.sender = direct_owner
    c.classify_transaction("tx1", "0xa", "0xb", 100, "first submission")

    with pytest.raises(Exception):
        c.classify_transaction("tx1", "0xa", "0xb", 100, "trying to reclassify the same tx_ref")

    assert c.get_state()["record_count"] == 1


def test_get_records_pagination(direct_vm, direct_deploy, direct_owner):
    c = _deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.mock_llm("classifying a treasury transaction", REVENUE)
    direct_vm.sender = direct_owner
    for i in range(3):
        c.classify_transaction(f"tx{i}", "0xa", "0xb", 100, f"payment {i}")

    page1 = c.get_records(0, 2)
    page2 = c.get_records(2, 2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert page1[0]["tx_ref"] == "tx2"  # newest first
    assert page2[0]["tx_ref"] == "tx0"
