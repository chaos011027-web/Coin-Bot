import main


def test_snapshot_keeps_canonical_approved_gmgn_primary_shadow():
    token_data = {
        "ca": "8Y3dub9Q11111111111111111111111111111111111",
        "top10_ratio": "25.30%",
        "top10_ratio_source": "GMGN",
        "canonical_metadata": {
            "top10_primary_source": "GMGN",
            "gmgn_top10_blocked_reason": "",
        },
        "source_conflict": {
            "top10": {
                "reason": "gmgn_preferred_over_bitquery",
            }
        },
    }

    snapshot = main._build_stable_snapshot(token_data)

    assert snapshot["top10_ratio"] == "25.30%"
    assert snapshot["top10_ratio_source"] == "GMGN"


def test_snapshot_does_not_promote_blocked_gmgn_observed_shadow():
    token_data = {
        "ca": "H1v9kbii11111111111111111111111111111111111",
        "top10_ratio": "0.70%",
        "top10_ratio_source": "GMGN",
        "top10_ratio_gmgn_observed": "0.70%",
        "canonical_metadata": {
            "top10_primary_source": "GMGN",
            "gmgn_top10_blocked_reason": "overlay_mask,strength:weak",
        },
        "source_conflict": {
            "top10": {
                "reason": "gmgn_only",
            }
        },
    }

    snapshot = main._build_stable_snapshot(token_data)

    assert "top10_ratio" not in snapshot
    assert "top10_ratio_source" not in snapshot
    assert snapshot["top10_ratio_gmgn_observed"] == "0.70%"
