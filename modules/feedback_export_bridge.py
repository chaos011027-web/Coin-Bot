from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from modules.attribution_feedback_sidecar import build_attribution_feedback_rows


DEFAULT_OUTPUT = Path("data/feedback_export_records.json")
LEGACY_OUTPUT_NAMES = {
    "training_replay_records.json",
    "training_dataset_bridge.csv",
    "replay_dataset_bridge.json",
}


def build_feedback_export_records(
    *,
    sample_rows,
    label_rows,
    decision_event_rows=None,
    execution_event_rows=None,
    state_transition_rows=None,
    trade_close_rows=None,
    sizing_decision_rows=None,
) -> List[Dict[str, Any]]:
    return build_attribution_feedback_rows(
        sample_rows=sample_rows,
        label_rows=label_rows,
        decision_event_rows=decision_event_rows,
        execution_event_rows=execution_event_rows,
        state_transition_rows=state_transition_rows,
        trade_close_rows=trade_close_rows,
        sizing_decision_rows=sizing_decision_rows,
    )


def export_feedback_export_records(
    *,
    output_path: str = "",
    sample_rows,
    label_rows,
    decision_event_rows=None,
    execution_event_rows=None,
    state_transition_rows=None,
    trade_close_rows=None,
    sizing_decision_rows=None,
) -> Path:
    target = Path(output_path) if output_path else DEFAULT_OUTPUT
    if target.name in LEGACY_OUTPUT_NAMES:
        raise ValueError("feedback export output must not overwrite existing phase-3/4 bridge outputs")

    rows = build_feedback_export_records(
        sample_rows=sample_rows,
        label_rows=label_rows,
        decision_event_rows=decision_event_rows,
        execution_event_rows=execution_event_rows,
        state_transition_rows=state_transition_rows,
        trade_close_rows=trade_close_rows,
        sizing_decision_rows=sizing_decision_rows,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "records": rows,
        "records_count": len(rows),
        "generated_from": "phase13_feedback_sidecars",
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
