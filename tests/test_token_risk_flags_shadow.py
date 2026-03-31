import modules.token_risk_flags as token_risk_flags


def test_token_risk_flags_emit_only_fixed_flag_set_and_exclude_legacy():
    rows = token_risk_flags.build_token_risk_flag_snapshots(
        signal_rows=[
            {
                "ca": "CA_RISK",
                "top10_adjusted_pct": 68.0,
                "pair_liquidity_usd": 12000.0,
                "source_conflict": {"has_conflict": True},
                "analysis_run_id": 9301,
            },
            {
                "ca": "CA_LEGACY",
                "top10_adjusted_pct": 95.0,
                "pair_liquidity_usd": 500.0,
                "analysis_run_id": 9399,
                "path_kind": "LEGACY_DIRECT_ENTER",
            },
        ],
        morphology_rows=[
            {
                "ca": "CA_RISK",
                "social_signal": {"ix_data": {"clusters": [{"cluster_id": "cluster_alpha"}]}},
                "holder_distribution": {"top10_semantic_conflict": True},
                "snapshot_time": "2026-03-31T10:10:00Z",
            }
        ],
        token_meta_rows=[
            {
                "ca": "CA_RISK",
                "security_flags": {"mint_authority_not_renounced": True},
            }
        ],
        analysis_run_rows=[{"id": 9301, "ca": "CA_RISK"}],
    )

    assert {row["ca"] for row in rows} == {"CA_RISK"}
    assert {row["risk_flag"] for row in rows} == {
        "TOP10_CONCENTRATION",
        "LOW_LIQUIDITY",
        "AUTHORITY_RISK",
        "GMGN_BEHAVIOR_RISK",
        "SOURCE_CONFLICT",
        "TOP10_SEMANTIC_CONFLICT",
    }
    assert all(row["analysis_run_id"] == 9301 for row in rows)
    assert all(row["rule_version"] == "token_risk_flags_v1" for row in rows)
