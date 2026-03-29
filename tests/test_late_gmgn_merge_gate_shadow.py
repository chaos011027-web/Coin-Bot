import copy

import pytest

import main


def test_late_gmgn_merge_gate_blocks_overlay_weak_shadow():
    analytics = {
        "popup_reason": "overlay_mask",
        "gmgn_result_strength": "weak",
        "target_ready": False,
        "layout_ready": False,
        "top10_ratio": "25.3%",
    }

    gate = main._late_gmgn_merge_gate_state(analytics)
    assert gate["blocked"] is True
    assert "overlay_mask" in gate["reason"]
    assert "strength:weak" in gate["reason"]
    assert "target_not_ready" in gate["reason"]
    assert "layout_not_ready" in gate["reason"]

    token_data = {
        "ca": "So11111111111111111111111111111111111111112",
        "top10_ratio": "84.83%",
        "top10_ratio_source": "BITQUERY",
        "dex_paid": True,
        "is_burned": True,
        "is_locked": True,
        "liquidity_usd": 125000.0,
        "top10_ratio_bitquery": "84.83%",
        "top10_effective_pct_self": 24.2732,
        "top10_semantic_suspect": True,
    }
    updated = main._apply_top10_semantic_research(copy.deepcopy(token_data), None, analytics.get("top10_ratio"))
    updated["late_gmgn_merge_blocked"] = gate["blocked"]
    updated["late_gmgn_merge_block_reason"] = gate["reason"]
    updated = main._append_late_gmgn_top10_history(
        updated,
        old_top10=22.8,
        new_top10=analytics.get("top10_ratio"),
        old_action="WATCH",
        new_action="WATCH",
        reasons=[gate["reason"]],
    )
    snapshot = main._build_stable_snapshot(updated)

    assert updated["top10_ratio"] == "84.83%"
    assert updated["top10_ratio_source"] == "BITQUERY"
    assert updated["dex_paid"] is True
    assert updated["is_burned"] is True
    assert updated["is_locked"] is True
    assert updated["liquidity_usd"] == pytest.approx(125000.0)
    assert snapshot["late_gmgn_merge_blocked"] is True
    assert snapshot["late_gmgn_merge_block_reason"] == gate["reason"]


def test_late_gmgn_merge_gate_allows_strong_result_shadow():
    analytics = {
        "gmgn_result_strength": "strong",
        "target_ready": True,
        "layout_ready": True,
        "popup_reason": "",
        "blocked_reason": "",
        "top10_ratio": "23.0%",
    }

    gate = main._late_gmgn_merge_gate_state(analytics)
    assert gate["blocked"] is False
    assert gate["reason"] == ""


def test_top10_late_merge_supported_by_selfcalc_shadow():
    token_data = {
        "ca": "So11111111111111111111111111111111111111112",
        "top10_ratio_bitquery": "94.8924%",
        "top10_effective_pct_self": 23.1706,
        "top10_semantic_suspect": True,
    }

    result = main._apply_top10_semantic_research(copy.deepcopy(token_data), {"bitquery_holders_count": 1}, "23.0%")

    assert result["top10_semantic_suspect"] is True
    assert result["top10_late_merge_supported_by_selfcalc"] is True
    assert result["top10_late_merge_support_gap"] == pytest.approx(0.1706)


def test_ensure_runtime_token_ca_shadow():
    result = main._ensure_runtime_token_ca({}, "BEKq8g51abcdef")
    assert result["ca"] == "BEKq8g51abcdef"

    existing = {"ca": "F9E8CceSabcdef"}
    result_existing = main._ensure_runtime_token_ca(existing, "BEKq8g51abcdef")
    assert result_existing["ca"] == "F9E8CceSabcdef"
