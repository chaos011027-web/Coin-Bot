from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.training_label_builder import training_label_repository
from modules.training_sample_builder import training_sample_repository


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        try:
            return {key: row[key] for key in row.keys()}
        except Exception:
            pass
    raise TypeError(f"unsupported export row type: {type(row)!r}")


def _normalize_rows(rows: Any) -> List[Dict[str, Any]]:
    return [_normalize_row(row) for row in list(rows or [])]


async def _load_samples(repository=None) -> List[Dict[str, Any]]:
    repo = repository or training_sample_repository
    if hasattr(repo, "list_samples"):
        return _normalize_rows(await repo.list_samples())
    return _normalize_rows(getattr(repo, "samples", []) or [])


async def _load_labels(repository=None) -> List[Dict[str, Any]]:
    repo = repository or training_label_repository
    if hasattr(repo, "list_labels"):
        return _normalize_rows(await repo.list_labels())
    return _normalize_rows(getattr(repo, "labels", []) or [])


async def async_build_training_replay_records(
    *,
    sample_repository=None,
    label_repository=None,
) -> List[Dict[str, Any]]:
    samples = await _load_samples(sample_repository)
    labels = await _load_labels(label_repository)

    if not samples:
        raise RuntimeError("training samples missing")
    if not labels:
        raise RuntimeError("training labels missing")

    sample_map = {
        str(row.get("sample_id") or "").strip(): dict(row)
        for row in samples
        if str(row.get("sample_id") or "").strip()
    }
    label_map = {
        str(row.get("sample_id") or "").strip(): dict(row)
        for row in labels
        if str(row.get("sample_id") or "").strip()
    }

    missing_labels = sorted(sample_id for sample_id in sample_map if sample_id not in label_map)
    orphan_labels = sorted(sample_id for sample_id in label_map if sample_id not in sample_map)
    if missing_labels:
        raise RuntimeError(f"training labels missing for samples: {', '.join(missing_labels)}")
    if orphan_labels:
        raise RuntimeError(f"training samples missing for labels: {', '.join(orphan_labels)}")

    records: List[Dict[str, Any]] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "").strip()
        if not sample_id:
            raise RuntimeError("sample_id missing from training sample")
        label = label_map[sample_id]
        records.append(
            {
                "sample_id": sample_id,
                "analysis_run_id": sample.get("analysis_run_id"),
                "ca": sample.get("ca"),
                "final_action": sample.get("final_action"),
                "strategy_id": sample.get("strategy_id"),
                "trace_link": sample.get("trace_link"),
                "path_kind": sample.get("path_kind"),
                "frozen_features": dict(sample.get("frozen_features") or {}),
                "feature_sources": dict(sample.get("feature_sources") or {}),
                "label": {
                    "label_kind": label.get("label_kind"),
                    "label_source": label.get("label_source"),
                    "position_ids": list(label.get("position_ids") or []),
                    "close_legs": int(label.get("close_legs") or 0),
                    "close_reasons": list(label.get("close_reasons") or []),
                    "realized_pnl_sol": label.get("realized_pnl_sol"),
                    "realized_return_pct": label.get("realized_return_pct"),
                },
            }
        )
    return records


def build_training_replay_records(
    *,
    sample_repository=None,
    label_repository=None,
) -> List[Dict[str, Any]]:
    return asyncio.run(
        async_build_training_replay_records(
            sample_repository=sample_repository,
            label_repository=label_repository,
        )
    )


def export_training_replay_records(
    *,
    output_path: str = "data/training_replay_records.json",
    sample_repository=None,
    label_repository=None,
) -> Path:
    records = build_training_replay_records(
        sample_repository=sample_repository,
        label_repository=label_repository,
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export phase-3 training/replay records from training samples and labels.")
    parser.add_argument(
        "--output",
        default="data/training_replay_records.json",
        help="Output JSON path.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    path = export_training_replay_records(output_path=str(args.output))
    print(str(path))
