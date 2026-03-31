import json

from modules.feedback_export_bridge import build_feedback_export_records, export_feedback_export_records


def test_feedback_export_bridge_builds_independent_feedback_records_without_touching_old_label_kind_semantics():
    rows = build_feedback_export_records(
        sample_rows=[
            {
                "sample_id": "sample_feedback_export_1",
                "analysis_run_id": 1351,
                "ca": "CA_FEEDBACK_EXPORT",
                "trace_link": "CA_FEEDBACK_EXPORT:11:22",
                "final_action": "WATCH",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
            }
        ],
        label_rows=[
            {
                "sample_id": "sample_feedback_export_1",
                "analysis_run_id": 1351,
                "ca": "CA_FEEDBACK_EXPORT",
                "label_kind": "no_trade",
                "label_source": "paper_ledger",
                "position_ids": [],
                "close_legs": 0,
                "close_reasons": [],
                "realized_pnl_sol": 0.0,
                "realized_return_pct": 0.0,
            }
        ],
        decision_event_rows=[],
        execution_event_rows=[],
        state_transition_rows=[
            {
                "analysis_run_id": 1351,
                "ca": "CA_FEEDBACK_EXPORT",
                "from_state": "OBSERVING",
                "to_state": "REJECTED",
            }
        ],
        trade_close_rows=[],
        sizing_decision_rows=[],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["sample_id"] == "sample_feedback_export_1"
    assert row["label_kind"] == "no_trade"
    assert row["feedback_class"] == "observe_reject"
    assert "strategy_feedback" in row
    assert "sizing_feedback" in row
    assert "label_augmentation" in row


def test_feedback_export_bridge_writes_new_json_and_excludes_legacy_records(tmp_path):
    output_path = tmp_path / "data" / "feedback_export_records.json"
    exported = export_feedback_export_records(
        output_path=str(output_path),
        sample_rows=[
            {
                "sample_id": "sample_feedback_export_2",
                "analysis_run_id": 1352,
                "ca": "CA_FEEDBACK_EXPORT_TWO",
                "trace_link": "CA_FEEDBACK_EXPORT_TWO:11:22",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
            },
            {
                "sample_id": "sample_feedback_export_legacy_1",
                "analysis_run_id": 1398,
                "ca": "CA_FEEDBACK_EXPORT_LEGACY",
                "trace_link": "CA_FEEDBACK_EXPORT_LEGACY:11:22",
                "final_action": "ENTER",
                "strategy_id": "MIXED",
                "path_kind": "LEGACY_DIRECT_ENTER",
                "legacy_path": True,
            },
        ],
        label_rows=[
            {
                "sample_id": "sample_feedback_export_2",
                "analysis_run_id": 1352,
                "ca": "CA_FEEDBACK_EXPORT_TWO",
                "label_kind": "no_fill",
                "label_source": "paper_ledger",
                "position_ids": [],
                "close_legs": 0,
                "close_reasons": [],
                "realized_pnl_sol": 0.0,
                "realized_return_pct": 0.0,
            },
            {
                "sample_id": "sample_feedback_export_legacy_1",
                "analysis_run_id": 1398,
                "ca": "CA_FEEDBACK_EXPORT_LEGACY",
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_feedback_export_legacy_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_TP"],
                "realized_pnl_sol": 0.30,
                "realized_return_pct": 30.0,
            },
        ],
        decision_event_rows=[],
        execution_event_rows=[],
        state_transition_rows=[
            {
                "analysis_run_id": 1352,
                "ca": "CA_FEEDBACK_EXPORT_TWO",
                "from_state": "OBSERVING",
                "to_state": "ARMED",
            }
        ],
        trade_close_rows=[],
        sizing_decision_rows=[],
    )

    assert exported == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    rows = payload.get("records", []) or []
    assert len(rows) == 1
    assert rows[0]["sample_id"] == "sample_feedback_export_2"
    assert rows[0]["feedback_class"] == "armed_no_fill"
