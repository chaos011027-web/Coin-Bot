import pytest

from modules.phase14_feedback_manifest import build_phase14_feedback_manifest


def _base_feedback_records():
    return [
        {
            "sample_id": "sample_manifest_feedback_trade_1",
            "analysis_run_id": 14101,
            "ca": "CA_MANIFEST_FEEDBACK_TRADE",
            "trace_link": "CA_MANIFEST_FEEDBACK_TRADE:11:22",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "path_kind": "MAIN_STATE_MACHINE",
            "position_ids": ["pos_manifest_feedback_trade_1"],
            "trade_close_ids": ["close_manifest_feedback_trade_1"],
            "label_kind": "trade_closed",
            "feedback_class": "entered_profit",
            "strategy_feedback": {
                "sample_id": "sample_manifest_feedback_trade_1",
                "analysis_run_id": 14101,
                "ca": "CA_MANIFEST_FEEDBACK_TRADE",
                "trace_link": "CA_MANIFEST_FEEDBACK_TRADE:11:22",
                "position_ids": ["pos_manifest_feedback_trade_1"],
                "trade_close_ids": ["close_manifest_feedback_trade_1"],
                "label_kind": "trade_closed",
                "feedback_class": "entered_profit",
            },
            "sizing_feedback": {
                "sample_id": "sample_manifest_feedback_trade_1",
                "analysis_run_id": 14101,
                "ca": "CA_MANIFEST_FEEDBACK_TRADE",
                "trace_link": "CA_MANIFEST_FEEDBACK_TRADE:11:22",
                "position_ids": ["pos_manifest_feedback_trade_1"],
                "trade_close_ids": ["close_manifest_feedback_trade_1"],
                "feedback_class": "entered_profit",
                "requested_entry_size": 0.12,
                "effective_allocated_size": 0.10,
                "requested_max_add_size": 0.0,
                "effective_add_size": 0.0,
                "budget_reason": "armed_new_entry_size",
                "size_clamp_reason": "no_clamp",
            },
            "label_augmentation": {
                "sample_id": "sample_manifest_feedback_trade_1",
                "analysis_run_id": 14101,
                "ca": "CA_MANIFEST_FEEDBACK_TRADE",
                "label_kind": "trade_closed",
                "feedback_class": "entered_profit",
                "position_ids": ["pos_manifest_feedback_trade_1"],
                "trade_close_ids": ["close_manifest_feedback_trade_1"],
            },
        },
        {
            "sample_id": "sample_manifest_feedback_watch_1",
            "analysis_run_id": 14102,
            "ca": "CA_MANIFEST_FEEDBACK_WATCH",
            "trace_link": "CA_MANIFEST_FEEDBACK_WATCH:33:44",
            "final_action": "WATCH",
            "strategy_id": "SMART_TREND",
            "path_kind": "MAIN_STATE_MACHINE",
            "position_ids": [],
            "trade_close_ids": [],
            "label_kind": "no_trade",
            "feedback_class": "observe_reject",
            "strategy_feedback": {
                "sample_id": "sample_manifest_feedback_watch_1",
                "analysis_run_id": 14102,
                "ca": "CA_MANIFEST_FEEDBACK_WATCH",
                "trace_link": "CA_MANIFEST_FEEDBACK_WATCH:33:44",
                "position_ids": [],
                "trade_close_ids": [],
                "label_kind": "no_trade",
                "feedback_class": "observe_reject",
            },
            "sizing_feedback": {
                "sample_id": "sample_manifest_feedback_watch_1",
                "analysis_run_id": 14102,
                "ca": "CA_MANIFEST_FEEDBACK_WATCH",
                "trace_link": "CA_MANIFEST_FEEDBACK_WATCH:33:44",
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
                "sample_id": "sample_manifest_feedback_watch_1",
                "analysis_run_id": 14102,
                "ca": "CA_MANIFEST_FEEDBACK_WATCH",
                "label_kind": "no_trade",
                "feedback_class": "observe_reject",
                "position_ids": [],
                "trade_close_ids": [],
            },
        },
        {
            "sample_id": "sample_manifest_feedback_nofill_1",
            "analysis_run_id": 14103,
            "ca": "CA_MANIFEST_FEEDBACK_NOFILL",
            "trace_link": "CA_MANIFEST_FEEDBACK_NOFILL:55:66",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "path_kind": "MAIN_STATE_MACHINE",
            "position_ids": [],
            "trade_close_ids": [],
            "label_kind": "no_fill",
            "feedback_class": "armed_no_fill",
            "strategy_feedback": {
                "sample_id": "sample_manifest_feedback_nofill_1",
                "analysis_run_id": 14103,
                "ca": "CA_MANIFEST_FEEDBACK_NOFILL",
                "trace_link": "CA_MANIFEST_FEEDBACK_NOFILL:55:66",
                "position_ids": [],
                "trade_close_ids": [],
                "label_kind": "no_fill",
                "feedback_class": "armed_no_fill",
            },
            "sizing_feedback": {
                "sample_id": "sample_manifest_feedback_nofill_1",
                "analysis_run_id": 14103,
                "ca": "CA_MANIFEST_FEEDBACK_NOFILL",
                "trace_link": "CA_MANIFEST_FEEDBACK_NOFILL:55:66",
                "position_ids": [],
                "trade_close_ids": [],
                "feedback_class": "armed_no_fill",
                "requested_entry_size": 0.10,
                "effective_allocated_size": 0.0,
                "requested_max_add_size": 0.0,
                "effective_add_size": 0.0,
                "budget_reason": "armed_new_entry_size",
                "size_clamp_reason": "no_clamp",
            },
            "label_augmentation": {
                "sample_id": "sample_manifest_feedback_nofill_1",
                "analysis_run_id": 14103,
                "ca": "CA_MANIFEST_FEEDBACK_NOFILL",
                "label_kind": "no_fill",
                "feedback_class": "armed_no_fill",
                "position_ids": [],
                "trade_close_ids": [],
            },
        },
    ]


def test_phase14_feedback_manifest_counts_distributions_and_identity_summary(tmp_path):
    records = _base_feedback_records()
    records_path = tmp_path / "data" / "feedback_export_records.json"

    manifest = build_phase14_feedback_manifest(
        records=records,
        records_path=str(records_path),
    )

    assert manifest["records_count"] == 3
    assert manifest["label_kind_distribution"] == {
        "trade_closed": 1,
        "no_trade": 1,
        "no_fill": 1,
    }
    assert manifest["feedback_class_distribution"] == {
        "entered_profit": 1,
        "observe_reject": 1,
        "armed_no_fill": 1,
    }
    assert manifest["unique_sample_ids"] == 3
    assert manifest["legacy_records_count"] == 0
    assert manifest["feedback_export_records_path"] == str(records_path.resolve())


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda records: records.__setitem__(0, {**records[0], "label_kind": "observe_reject"}),
            "unsupported label_kind",
        ),
        (
            lambda records: records.__setitem__(0, {**records[0], "feedback_class": "trade_closed"}),
            "unsupported feedback_class",
        ),
        (
            lambda records: records.__setitem__(0, {**records[0], "position_ids": "pos_manifest_feedback_trade_1"}),
            "position_ids must be a list",
        ),
        (
            lambda records: records.__setitem__(0, {**records[0], "trade_close_ids": "close_manifest_feedback_trade_1"}),
            "trade_close_ids must be a list",
        ),
        (
            lambda records: records[0]["strategy_feedback"].__setitem__("sample_id", "sample_mismatch"),
            "identity mismatch",
        ),
    ],
)
def test_phase14_feedback_manifest_fails_on_bad_semantics_or_identity(tmp_path, mutator, message):
    records = _base_feedback_records()
    mutator(records)

    with pytest.raises(RuntimeError, match=message):
        build_phase14_feedback_manifest(
            records=records,
            records_path=str(tmp_path / "data" / "feedback_export_records.json"),
        )
