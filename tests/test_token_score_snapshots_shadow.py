import modules.token_score_snapshots as token_score_snapshots


def test_token_score_snapshots_emit_fixed_subscores_and_total_only():
    rows = token_score_snapshots.build_token_score_snapshots(
        signal_rows=[
            {
                "ca": "CA_SCORE",
                "pair_liquidity_usd": 50000.0,
                "top10_adjusted_pct": 20.0,
                "metric_confidence": {"liquidity": 0.9, "top10": 0.8},
                "analysis_run_id": 9401,
            }
        ],
        morphology_rows=[
            {
                "ca": "CA_SCORE",
                "social_signal": {},
                "snapshot_time": "2026-03-31T10:15:00Z",
            }
        ],
        risk_flag_rows=[],
        analysis_run_rows=[{"id": 9401, "ca": "CA_SCORE"}],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["ca"] == "CA_SCORE"
    assert row["analysis_run_id"] == 9401
    assert row["score_version"] == "token_score_snapshots_v1"
    assert row["liquidity_structure_score"] == 1.0
    assert row["top10_concentration_score"] == 0.8
    assert row["gmgn_behavior_score"] == 0.8
    assert row["source_confidence_score"] == 0.85
    assert row["total_score"] == 0.8625
    assert row["snapshot_at"] == "2026-03-31T10:15:00Z"
