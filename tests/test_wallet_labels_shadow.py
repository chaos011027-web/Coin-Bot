import modules.wallet_labels as wallet_labels


def test_wallet_labels_require_evidence_aggregation_and_confidence_gate():
    rows = wallet_labels.build_wallet_label_snapshots(
        [
            {
                "evidence_id": "ev_single",
                "wallet_address": "wallet_single",
                "label_candidate": "SMART_MONEY_WALLET",
                "confidence_hint": 0.90,
                "trace_link": "CA_SINGLE:11:22",
                "sample_id": "sample_single_1",
                "observed_at": "2026-03-31T10:00:00Z",
            },
            {
                "evidence_id": "ev_agg_1",
                "wallet_address": "wallet_alpha",
                "label_candidate": "SMART_MONEY_WALLET",
                "confidence_hint": 0.80,
                "trace_link": "CA_ALPHA:11:22",
                "sample_id": "sample_alpha_1",
                "observed_at": "2026-03-31T10:05:00Z",
            },
            {
                "evidence_id": "ev_agg_2",
                "wallet_address": "wallet_alpha",
                "label_candidate": "SMART_MONEY_WALLET",
                "confidence_hint": 0.70,
                "trace_link": "CA_ALPHA:33:44",
                "sample_id": "sample_alpha_2",
                "observed_at": "2026-03-31T10:06:00Z",
            },
            {
                "evidence_id": "ev_cluster",
                "wallet_address": "wallet_cluster",
                "label_candidate": "SUSPICIOUS_CLUSTER_WALLET",
                "confidence_hint": 0.65,
                "trace_link": "CA_CLUSTER:55:66",
                "sample_id": "sample_cluster_1",
                "observed_at": "2026-03-31T10:07:00Z",
            },
        ]
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["wallet_address"] == "wallet_alpha"
    assert row["label_name"] == "SMART_MONEY_WALLET"
    assert row["confidence"] == 0.75
    assert row["confidence_score"] == 0.75
    assert row["evidence_count"] == 2
    assert row["snapshot_at"] == "2026-03-31T10:06:00Z"
    assert row["rule_version"] == "wallet_labels_v1"
