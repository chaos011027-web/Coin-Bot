from modules.label_augmentation_sidecar import build_label_augmentation_record


def test_label_augmentation_preserves_coarse_label_kind_and_adds_feedback_class():
    augmented = build_label_augmentation_record(
        label_row={
            "sample_id": "sample_label_aug_1",
            "analysis_run_id": 1331,
            "ca": "CA_LABEL_AUG",
            "label_kind": "trade_closed",
            "label_source": "paper_trade_closes",
            "position_ids": ["pos_label_aug_1"],
            "close_legs": 2,
            "close_reasons": ["TP1", "CLOSED_TP"],
            "realized_pnl_sol": 0.48,
            "realized_return_pct": 48.0,
        },
        strategy_feedback_row={
            "sample_id": "sample_label_aug_1",
            "analysis_run_id": 1331,
            "ca": "CA_LABEL_AUG",
            "feedback_class": "entered_partial_win",
            "position_ids": ["pos_label_aug_1"],
            "trade_close_ids": ["close_label_aug_1", "close_label_aug_2"],
        },
        sizing_feedback_row={
            "requested_entry_size": 0.12,
            "effective_allocated_size": 0.10,
            "requested_max_add_size": 0.04,
            "effective_add_size": 0.02,
            "budget_reason": "armed_new_entry_size",
            "size_clamp_reason": "risk_clamp:LOW_LIQUIDITY",
        },
    )

    assert augmented["label_kind"] == "trade_closed"
    assert augmented["feedback_class"] == "entered_partial_win"
    assert augmented["position_ids"] == ["pos_label_aug_1"]
    assert augmented["trade_close_ids"] == ["close_label_aug_1", "close_label_aug_2"]
    assert augmented["requested_entry_size"] == 0.12
    assert augmented["effective_allocated_size"] == 0.10


def test_label_augmentation_keeps_no_trade_label_kind_separate_from_feedback_class():
    augmented = build_label_augmentation_record(
        label_row={
            "sample_id": "sample_label_aug_no_trade_1",
            "analysis_run_id": 1332,
            "ca": "CA_LABEL_AUG_NO_TRADE",
            "label_kind": "no_trade",
            "label_source": "paper_ledger",
            "position_ids": [],
            "close_legs": 0,
            "close_reasons": [],
            "realized_pnl_sol": 0.0,
            "realized_return_pct": 0.0,
        },
        strategy_feedback_row={
            "sample_id": "sample_label_aug_no_trade_1",
            "analysis_run_id": 1332,
            "ca": "CA_LABEL_AUG_NO_TRADE",
            "feedback_class": "observe_reject",
            "position_ids": [],
            "trade_close_ids": [],
        },
        sizing_feedback_row={
            "requested_entry_size": 0.0,
            "effective_allocated_size": 0.0,
            "requested_max_add_size": 0.0,
            "effective_add_size": 0.0,
            "budget_reason": "state_not_actionable",
            "size_clamp_reason": "no_clamp",
        },
    )

    assert augmented["label_kind"] == "no_trade"
    assert augmented["feedback_class"] == "observe_reject"
