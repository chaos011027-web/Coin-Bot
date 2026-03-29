import copy

import main


def test_weak_overlay_gmgn_candidate_blocked_from_canonical_shadow():
    token_data = {
        "ca": "H1v9kbii11111111111111111111111111111111111",
    }
    analytics = {
        "top10_ratio": "0.7%",
        "gmgn_result_strength": "weak",
        "popup_reason": "overlay_mask",
        "target_ready": False,
        "layout_ready": False,
    }

    token_data = main._apply_gmgn_analytics(copy.deepcopy(token_data), analytics)
    result = main._resolve_canonical_metrics(token_data, analytics, {})

    assert result["ca"] == "H1v9kbii11111111111111111111111111111111111"
    assert result.get("top10_ratio_source", "") != "GMGN"
    assert result.get("top10_ratio") in (None, "")
    assert result.get("top10_adjusted_pct") is None
    assert result.get("top10_ratio_gmgn") is None
    assert result.get("top10_ratio_gmgn_observed") == "0.70%"
    assert "overlay_mask" in str(result.get("canonical_metadata", {}).get("gmgn_top10_blocked_reason") or "")


def test_weak_gmgn_token_field_fallback_also_blocked_shadow():
    token_data = {
        "ca": "H1v9kbii11111111111111111111111111111111111",
        "top10_ratio_gmgn": "0.7%",
        "top10_ratio_gmgn_observed": "0.7%",
        "gmgn_result_strength": "thin",
        "gmgn_popup_reason": "overlay_mask",
        "gmgn_target_ready": False,
        "gmgn_layout_ready": False,
    }

    result = main._resolve_canonical_metrics(copy.deepcopy(token_data), None, {})

    assert result["ca"] == "H1v9kbii11111111111111111111111111111111111"
    assert result.get("top10_ratio_source", "") != "GMGN"
    assert result.get("top10_ratio") in (None, "")
    assert result.get("top10_adjusted_pct") is None
    assert result.get("top10_ratio_gmgn") is None
    assert result.get("top10_ratio_gmgn_observed") == "0.70%"
    assert "strength:thin" in str(result.get("canonical_metadata", {}).get("gmgn_top10_blocked_reason") or "")


def test_strong_gmgn_candidate_can_still_win_canonical_shadow():
    token_data = {
        "ca": "8Y3dub9Q11111111111111111111111111111111111",
    }
    analytics = {
        "top10_ratio": "25.3%",
        "gmgn_result_strength": "strong",
        "target_ready": True,
        "layout_ready": True,
    }
    bq_data = {
        "bitquery_top10_ratio": "84.8339%",
    }

    token_data = main._apply_gmgn_analytics(copy.deepcopy(token_data), analytics)
    result = main._resolve_canonical_metrics(token_data, analytics, bq_data)

    assert result["ca"] == "8Y3dub9Q11111111111111111111111111111111111"
    assert result.get("top10_ratio_source") == "GMGN"
    assert result.get("top10_ratio") == "25.30%"
    assert result.get("top10_adjusted_pct") == 25.3
    assert result.get("top10_ratio_gmgn") == "25.30%"
    assert result.get("top10_ratio_gmgn_observed") == "25.30%"
    assert result.get("canonical_metadata", {}).get("top10_primary_source") == "GMGN"
    assert result.get("source_conflict", {}).get("top10", {}).get("reason") == "gmgn_preferred_over_bitquery"
