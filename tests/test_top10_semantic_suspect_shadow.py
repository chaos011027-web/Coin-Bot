import copy

import pytest

import main


def test_top10_semantic_suspect_shadow_hits_on_bitquery_overestimate():
    token_data = {
        "ca": "So11111111111111111111111111111111111111112",
        "top10_ratio": "93.00%",
        "top10_ratio_source": "BITQUERY",
        "top10_ratio_bitquery": "93.00%",
        "top10_effective_pct_self": 22.5,
        "top10_ratio_gmgn": "23.2%",
    }

    result = main._apply_top10_semantic_research(
        copy.deepcopy(token_data),
        {"bitquery_holders_data": [{"address": "holder1"}]},
    )

    assert result["bitquery_holders_count"] == 1
    assert result["top10_semantic_suspect"] is True
    assert result["top10_bitquery_gap_vs_effective_self"] == pytest.approx(70.5)
    assert result["top10_bitquery_gap_vs_late_gmgn"] == pytest.approx(69.8)
    assert result["top10_effective_gap_vs_late_gmgn"] == pytest.approx(-0.7)
    reasons = set(str(result["top10_semantic_suspect_reason"]).split(","))
    assert {"bitquery_ge_80", "holders_count_le_2", "bitquery_minus_effective_ge_20", "effective_close_to_late_gmgn"} <= reasons


def test_top10_semantic_suspect_shadow_stays_false_for_normal_sample():
    token_data = {
        "ca": "So11111111111111111111111111111111111111112",
        "top10_ratio": "34.00%",
        "top10_ratio_source": "BITQUERY",
        "top10_ratio_bitquery": "34.00%",
        "top10_effective_pct_self": 25.0,
        "top10_ratio_gmgn": "24.5%",
    }

    result = main._apply_top10_semantic_research(
        copy.deepcopy(token_data),
        {"bitquery_holders_data": [{"address": "holder1"}, {"address": "holder2"}, {"address": "holder3"}]},
    )

    assert result["bitquery_holders_count"] == 3
    assert result["top10_semantic_suspect"] is False
    assert result["top10_bitquery_gap_vs_effective_self"] == pytest.approx(9.0)
    assert result["top10_semantic_suspect_reason"] == ""


def test_late_gmgn_top10_history_appends_and_trims_shadow():
    token_data = {"ca": "So11111111111111111111111111111111111111112"}

    for idx in range(8):
        token_data = main._append_late_gmgn_top10_history(
            token_data,
            old_top10=20.0 + idx - 1 if idx > 0 else None,
            new_top10=20.0 + idx,
            old_action="WATCH",
            new_action="WATCH",
            reasons=["late_gmgn"],
        )

    assert token_data["late_gmgn_top10_history_count"] == 6
    assert len(token_data["late_gmgn_top10_history"]) == 6
    assert token_data["late_gmgn_top10_history"][0]["new_top10"] == pytest.approx(22.0)
    assert token_data["late_gmgn_top10_history"][-1]["new_top10"] == pytest.approx(27.0)
    assert token_data["late_gmgn_top10_last_value"] == pytest.approx(27.0)
    assert token_data["late_gmgn_top10_min_value"] == pytest.approx(22.0)
    assert token_data["late_gmgn_top10_max_value"] == pytest.approx(27.0)


def test_top10_semantic_research_fields_do_not_override_formal_top10_shadow():
    token_data = {
        "ca": "So11111111111111111111111111111111111111112",
        "top10_ratio": "93.00%",
        "top10_ratio_source": "BITQUERY",
        "top10_ratio_bitquery": "93.00%",
        "top10_effective_pct_self": 22.5,
        "top10_ratio_gmgn": "23.0%",
    }

    updated = main._apply_top10_semantic_research(
        copy.deepcopy(token_data),
        {"bitquery_holders_data": [{"address": "holder1"}]},
    )
    updated = main._append_late_gmgn_top10_history(
        updated,
        old_top10=22.8,
        new_top10=23.0,
        old_action="WATCH",
        new_action="WATCH",
        reasons=["gmgn_top10_arrived"],
    )
    snapshot = main._build_stable_snapshot(updated)

    assert updated["top10_ratio"] == "93.00%"
    assert updated["top10_ratio_source"] == "BITQUERY"
    assert snapshot["top10_ratio"] == "93.00%"
    assert snapshot["top10_ratio_source"] == "BITQUERY"
    assert snapshot["top10_semantic_suspect"] is True
    assert snapshot["late_gmgn_top10_history_count"] == 1
