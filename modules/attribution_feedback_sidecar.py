from __future__ import annotations

from typing import Any, Dict, List, Set

from modules.execution_outcome_bridge import build_execution_outcome_bucket
from modules.label_augmentation_sidecar import build_label_augmentation_record
from modules.sizing_feedback_snapshot import build_sizing_feedback_snapshot
from modules.strategy_feedback_snapshot import build_strategy_feedback_snapshot


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported attribution feedback row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def _matches_analysis_identity(row: Dict[str, Any], *, analysis_run_id: int, ca: str) -> bool:
    if _is_legacy_row(row):
        return False
    if _safe_text(row.get("ca")) not in {"", ca}:
        return False
    row_run_id = _safe_int(row.get("analysis_run_id"))
    if row_run_id is not None and row_run_id != analysis_run_id:
        return False
    return True


def _matches_position_identity(
    row: Dict[str, Any],
    *,
    analysis_run_id: int,
    ca: str,
    position_ids: Set[str],
) -> bool:
    if not _matches_analysis_identity(row, analysis_run_id=analysis_run_id, ca=ca):
        return False
    if not position_ids:
        return True
    return _safe_text(row.get("position_id")) in position_ids


def build_attribution_feedback_rows(
    *,
    sample_rows,
    label_rows,
    decision_event_rows=None,
    execution_event_rows=None,
    state_transition_rows=None,
    trade_close_rows=None,
    sizing_decision_rows=None,
) -> List[Dict[str, Any]]:
    label_map = {
        _safe_text(_normalize_row(row).get("sample_id")): _normalize_row(row)
        for row in list(label_rows or [])
        if _safe_text(_normalize_row(row).get("sample_id")) and not _is_legacy_row(_normalize_row(row))
    }
    out: List[Dict[str, Any]] = []
    for raw_sample in list(sample_rows or []):
        sample = _normalize_row(raw_sample)
        if _is_legacy_row(sample):
            continue
        sample_id = _safe_text(sample.get("sample_id"))
        if not sample_id:
            raise RuntimeError("sample_id missing from attribution feedback sample")
        label = label_map.get(sample_id)
        if not label:
            raise RuntimeError(f"training label missing for sample: {sample_id}")

        analysis_run_id = int(_safe_int(sample.get("analysis_run_id"), 0) or 0)
        ca = _safe_text(sample.get("ca"))
        position_ids = {
            _safe_text(value)
            for value in list(label.get("position_ids") or [])
            if _safe_text(value)
        }
        matched_decision_rows = [
            _normalize_row(row)
            for row in list(decision_event_rows or [])
            if _matches_analysis_identity(_normalize_row(row), analysis_run_id=analysis_run_id, ca=ca)
        ]
        matched_execution_rows = [
            _normalize_row(row)
            for row in list(execution_event_rows or [])
            if _matches_analysis_identity(_normalize_row(row), analysis_run_id=analysis_run_id, ca=ca)
        ]
        matched_state_rows = [
            _normalize_row(row)
            for row in list(state_transition_rows or [])
            if _matches_analysis_identity(_normalize_row(row), analysis_run_id=analysis_run_id, ca=ca)
        ]
        matched_trade_close_rows = [
            _normalize_row(row)
            for row in list(trade_close_rows or [])
            if _matches_position_identity(
                _normalize_row(row),
                analysis_run_id=analysis_run_id,
                ca=ca,
                position_ids=position_ids,
            )
        ]
        matched_sizing_rows = [
            _normalize_row(row)
            for row in list(sizing_decision_rows or [])
            if not _is_legacy_row(_normalize_row(row))
            and (
                _safe_text(_normalize_row(row).get("sample_id")) == sample_id
                or _matches_analysis_identity(_normalize_row(row), analysis_run_id=analysis_run_id, ca=ca)
            )
        ]

        execution_outcome = build_execution_outcome_bucket(
            sample_row=sample,
            label_row=label,
            state_transition_rows=matched_state_rows,
            decision_event_rows=matched_decision_rows,
            execution_event_rows=matched_execution_rows,
            trade_close_rows=matched_trade_close_rows,
        )
        strategy_feedback = build_strategy_feedback_snapshot(
            sample_row=sample,
            label_row=label,
            execution_outcome_row=execution_outcome,
            decision_event_rows=matched_decision_rows,
            state_transition_rows=matched_state_rows,
        )
        sizing_feedback = build_sizing_feedback_snapshot(
            sample_row=sample,
            execution_outcome_row=execution_outcome,
            sizing_decision_rows=matched_sizing_rows,
            execution_event_rows=matched_execution_rows,
        )
        label_augmentation = build_label_augmentation_record(
            label_row=label,
            strategy_feedback_row=strategy_feedback,
            sizing_feedback_row=sizing_feedback,
        )

        out.append(
            {
                "sample_id": sample_id,
                "analysis_run_id": analysis_run_id,
                "ca": ca,
                "trace_link": _safe_text(sample.get("trace_link")),
                "final_action": _safe_text(sample.get("final_action")),
                "strategy_id": _safe_text(sample.get("strategy_id")),
                "path_kind": _safe_text(sample.get("path_kind")),
                "position_ids": list(execution_outcome.get("position_ids") or []),
                "trade_close_ids": list(execution_outcome.get("trade_close_ids") or []),
                "label_kind": _safe_text(label.get("label_kind")).lower(),
                "feedback_class": _safe_text(execution_outcome.get("feedback_class")),
                "strategy_feedback": strategy_feedback,
                "sizing_feedback": sizing_feedback,
                "label_augmentation": label_augmentation,
            }
        )
    return out
