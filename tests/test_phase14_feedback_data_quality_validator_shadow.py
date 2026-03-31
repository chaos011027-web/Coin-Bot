import pytest

from modules.phase14_feedback_data_quality_validator import validate_phase14_feedback_export_payloads
from modules.phase14_feedback_manifest import build_phase14_feedback_manifest


def _base_feedback_records():
    return [
        {
            "sample_id": "sample_validator_feedback_trade_1",
            "analysis_run_id": 14201,
            "ca": "CA_VALIDATOR_FEEDBACK_TRADE",
            "trace_link": "CA_VALIDATOR_FEEDBACK_TRADE:11:22",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "path_kind": "MAIN_STATE_MACHINE",
            "position_ids": ["pos_validator_feedback_trade_1"],
            "trade_close_ids": ["close_validator_feedback_trade_1"],
            "label_kind": "trade_closed",
            "feedback_class": "entered_profit",
            "strategy_feedback": {
                "sample_id": "sample_validator_feedback_trade_1",
                "analysis_run_id": 14201,
                "ca": "CA_VALIDATOR_FEEDBACK_TRADE",
                "trace_link": "CA_VALIDATOR_FEEDBACK_TRADE:11:22",
                "position_ids": ["pos_validator_feedback_trade_1"],
                "trade_close_ids": ["close_validator_feedback_trade_1"],
                "label_kind": "trade_closed",
                "feedback_class": "entered_profit",
            },
            "sizing_feedback": {
                "sample_id": "sample_validator_feedback_trade_1",
                "analysis_run_id": 14201,
                "ca": "CA_VALIDATOR_FEEDBACK_TRADE",
                "trace_link": "CA_VALIDATOR_FEEDBACK_TRADE:11:22",
                "position_ids": ["pos_validator_feedback_trade_1"],
                "trade_close_ids": ["close_validator_feedback_trade_1"],
                "feedback_class": "entered_profit",
                "requested_entry_size": 0.12,
                "effective_allocated_size": 0.10,
                "requested_max_add_size": 0.0,
                "effective_add_size": 0.0,
                "budget_reason": "armed_new_entry_size",
                "size_clamp_reason": "no_clamp",
            },
            "label_augmentation": {
                "sample_id": "sample_validator_feedback_trade_1",
                "analysis_run_id": 14201,
                "ca": "CA_VALIDATOR_FEEDBACK_TRADE",
                "label_kind": "trade_closed",
                "feedback_class": "entered_profit",
                "position_ids": ["pos_validator_feedback_trade_1"],
                "trade_close_ids": ["close_validator_feedback_trade_1"],
            },
        },
        {
            "sample_id": "sample_validator_feedback_watch_1",
            "analysis_run_id": 14202,
            "ca": "CA_VALIDATOR_FEEDBACK_WATCH",
            "trace_link": "CA_VALIDATOR_FEEDBACK_WATCH:33:44",
            "final_action": "WATCH",
            "strategy_id": "SMART_TREND",
            "path_kind": "MAIN_STATE_MACHINE",
            "position_ids": [],
            "trade_close_ids": [],
            "label_kind": "no_trade",
            "feedback_class": "observe_reject",
            "strategy_feedback": {
                "sample_id": "sample_validator_feedback_watch_1",
                "analysis_run_id": 14202,
                "ca": "CA_VALIDATOR_FEEDBACK_WATCH",
                "trace_link": "CA_VALIDATOR_FEEDBACK_WATCH:33:44",
                "position_ids": [],
                "trade_close_ids": [],
                "label_kind": "no_trade",
                "feedback_class": "observe_reject",
            },
            "sizing_feedback": {
                "sample_id": "sample_validator_feedback_watch_1",
                "analysis_run_id": 14202,
                "ca": "CA_VALIDATOR_FEEDBACK_WATCH",
                "trace_link": "CA_VALIDATOR_FEEDBACK_WATCH:33:44",
                "position_ids": [],
                "trade_close_ids": [],
                "feedback_class": "observe_reject",
                "requested_entry_size": 0.0,
                "effective_allocated_size": 0.0,
                "requested_max_add_size": 0.0,
                "effective_add_size": 0.0,
                "budget_reason": "state_not_actionable",
                "size_clamp_reason": "no_clamp",
            },
            "label_augmentation": {
                "sample_id": "sample_validator_feedback_watch_1",
                "analysis_run_id": 14202,
                "ca": "CA_VALIDATOR_FEEDBACK_WATCH",
                "label_kind": "no_trade",
                "feedback_class": "observe_reject",
                "position_ids": [],
                "trade_close_ids": [],
            },
        },
    ]


def _build_success_payloads():
    records = _base_feedback_records()
    manifest = build_phase14_feedback_manifest(
        records=records,
        records_path="data/feedback_export_records.json",
    )
    return {"records": records, "records_count": len(records)}, manifest


def test_phase14_feedback_validator_accepts_valid_payloads_and_keeps_coarse_labels_separate():
    records_payload, manifest_payload = _build_success_payloads()

    report = validate_phase14_feedback_export_payloads(
        records_payload=records_payload,
        manifest_payload=manifest_payload,
    )

    assert report["status"] == "success"
    assert report["records_count"] == 2
    assert records_payload["records"][0]["label_kind"] == "trade_closed"
    assert records_payload["records"][0]["feedback_class"] == "entered_profit"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload, manifest: payload.__setitem__("records", []),
            "feedback export records empty",
        ),
        (
            lambda payload, manifest: payload["records"].append(dict(payload["records"][0])),
            "duplicate sample_id",
        ),
        (
            lambda payload, manifest: payload["records"][0].__setitem__("feedback_class", "trade_closed"),
            "unsupported feedback_class",
        ),
        (
            lambda payload, manifest: payload["records"][0].__setitem__("label_kind", "entered_profit"),
            "unsupported label_kind",
        ),
        (
            lambda payload, manifest: payload["records"][0].__setitem__("path_kind", "LEGACY_DIRECT_ENTER"),
            "legacy samples must be excluded",
        ),
        (
            lambda payload, manifest: payload["records"][0].__setitem__("position_ids", "broken"),
            "position_ids must be a list",
        ),
        (
            lambda payload, manifest: payload["records"][0].__setitem__("trade_close_ids", "broken"),
            "trade_close_ids must be a list",
        ),
        (
            lambda payload, manifest: payload["records"][0].__setitem__("sample_id", ""),
            "required field missing: sample_id",
        ),
        (
            lambda payload, manifest: payload["records"][0]["strategy_feedback"].__setitem__("sample_id", "sample_mismatch"),
            "identity mismatch",
        ),
        (
            lambda payload, manifest: payload.__setitem__("records_count", 99),
            "records_count mismatch",
        ),
    ],
)
def test_phase14_feedback_validator_fails_loudly_on_bad_payloads(mutator, message):
    records_payload, manifest_payload = _build_success_payloads()
    mutator(records_payload, manifest_payload)

    with pytest.raises(RuntimeError, match=message):
        validate_phase14_feedback_export_payloads(
            records_payload=records_payload,
            manifest_payload=manifest_payload,
        )
