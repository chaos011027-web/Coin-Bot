import modules.wallet_label_evidence as wallet_label_evidence


def test_wallet_label_evidence_keeps_single_hits_as_evidence_rows():
    rows = wallet_label_evidence.build_wallet_label_evidence_rows(
        smart_wallet_rows=[
            {
                "wallet_address": "wallet_alpha",
                "tags": ["Smart Money"],
                "last_active": "2026-03-31T10:00:00Z",
                "last_seen_ca": "CA_ALPHA",
                "trace_link": "CA_ALPHA:11:22",
                "sample_id": "sample_wallet_alpha_1",
            }
        ],
        wallet_cluster_rows=[
            {
                "cluster_id": "cluster_alpha",
                "wallet_address": "wallet_alpha",
                "discovered_in_token": "CA_ALPHA",
                "behavior_tag": "SUSPICIOUS_CLUSTER",
                "risk_level": 8,
                "created_at": "2026-03-31T10:05:00Z",
                "trace_link": "CA_ALPHA:11:22",
                "sample_id": "sample_wallet_alpha_1",
            }
        ],
        analysis_run_rows=[{"id": 9201, "ca": "CA_ALPHA"}],
    )

    assert len(rows) == 2
    candidates = {row["label_candidate"] for row in rows}
    assert candidates == {"SMART_MONEY_WALLET", "SUSPICIOUS_CLUSTER_WALLET"}

    for row in rows:
        assert row["evidence_id"]
        assert row["wallet_address"] == "wallet_alpha"
        assert row["source"]
        assert row["source_key"]
        assert row["ca"] == "CA_ALPHA"
        assert row["analysis_run_id"] == 9201
        assert row["confidence_hint"] > 0
        assert row["observed_at"]
        assert isinstance(row["evidence_payload"], dict)
        assert row["trace_link"] == "CA_ALPHA:11:22"
        assert row["sample_id"] == "sample_wallet_alpha_1"
