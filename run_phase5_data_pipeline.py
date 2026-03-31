from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict

from export_replay_dataset_bridge import export_replay_dataset_bridge
from export_training_dataset_bridge import export_training_dataset_bridge
from export_training_replay_records import export_training_replay_records
from modules.phase5_pipeline_manifest import build_phase5_pipeline_manifest, write_phase5_pipeline_manifest
from modules.training_label_builder import build_training_labels


DEFAULT_TRAINING_REPLAY_OUTPUT = Path("data/training_replay_records.json")
DEFAULT_TRAINING_DATASET_OUTPUT = Path("data/training_dataset_bridge.csv")
DEFAULT_REPLAY_DATASET_OUTPUT = Path("data/replay_dataset_bridge.json")
DEFAULT_MANIFEST_OUTPUT = Path("data/phase5_pipeline_manifest.json")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _load_training_header(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"training dataset bridge missing: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("training dataset bridge csv missing header")
        return list(reader.fieldnames)


def _load_replay_payload(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"replay dataset bridge missing: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict) and isinstance(raw.get("records"), list):
        rows = raw.get("records") or []
    else:
        raise ValueError("replay dataset bridge payload must be a list or {'records': [...]}")
    return [dict(row) for row in rows]


def run_phase5_consumer_smoke_check(
    *,
    training_dataset_path: str,
    replay_dataset_path: str,
) -> Dict[str, Any]:
    from optuna_tune_model import FEATURE_COLUMNS as OPTUNA_FEATURE_COLUMNS
    from optuna_tune_model import LABEL_COLUMN as OPTUNA_LABEL_COLUMN
    from optuna_tune_model import resolve_dataset_path as resolve_optuna_dataset_path
    from optuna_tune_strategy import resolve_records_path as resolve_replay_records_path
    from train_model import FEATURE_COLUMNS as TRAIN_FEATURE_COLUMNS
    from train_model import LABEL_COLUMN as TRAIN_LABEL_COLUMN
    from train_model import resolve_dataset_path as resolve_train_dataset_path

    training_path = Path(_safe_text(training_dataset_path)).resolve()
    replay_path = Path(_safe_text(replay_dataset_path)).resolve()
    if not training_path.exists():
        raise FileNotFoundError(f"training dataset bridge missing: {training_path}")
    if not replay_path.exists():
        raise FileNotFoundError(f"replay dataset bridge missing: {replay_path}")

    training_header = _load_training_header(training_path)
    required_training_cols = {"sample_id", *TRAIN_FEATURE_COLUMNS, TRAIN_LABEL_COLUMN}
    if not required_training_cols.issubset(set(training_header)):
        raise RuntimeError("training dataset bridge missing required columns for train_model")
    required_optuna_cols = {"sample_id", *OPTUNA_FEATURE_COLUMNS, OPTUNA_LABEL_COLUMN}
    if not required_optuna_cols.issubset(set(training_header)):
        raise RuntimeError("training dataset bridge missing required columns for optuna_tune_model")

    replay_rows = _load_replay_payload(replay_path)
    if not isinstance(replay_rows, list):
        raise RuntimeError("replay dataset bridge payload invalid")

    resolved_train = resolve_train_dataset_path()
    resolved_optuna_train = resolve_optuna_dataset_path()
    resolved_replay = resolve_replay_records_path()

    if resolved_train != training_path:
        raise RuntimeError("train_model resolve_dataset_path mismatch")
    if resolved_optuna_train != training_path:
        raise RuntimeError("optuna_tune_model resolve_dataset_path mismatch")
    if resolved_replay != replay_path:
        raise RuntimeError("optuna_tune_strategy resolve_records_path mismatch")

    return {
        "train_model_dataset_path": str(resolved_train),
        "optuna_tune_model_dataset_path": str(resolved_optuna_train),
        "optuna_tune_strategy_records_path": str(resolved_replay),
        "training_header": training_header,
        "replay_rows_count": len(replay_rows),
    }


def run_phase5_data_pipeline(
    *,
    training_replay_output_path: str = "",
    training_dataset_output_path: str = "",
    replay_dataset_output_path: str = "",
    manifest_output_path: str = "",
    sample_repository=None,
    label_repository=None,
    paper_ledger_repository=None,
) -> Dict[str, Any]:
    training_replay_target = _safe_text(training_replay_output_path) or str(DEFAULT_TRAINING_REPLAY_OUTPUT)
    training_dataset_target = _safe_text(training_dataset_output_path) or str(DEFAULT_TRAINING_DATASET_OUTPUT)
    replay_dataset_target = _safe_text(replay_dataset_output_path) or str(DEFAULT_REPLAY_DATASET_OUTPUT)
    manifest_target = _safe_text(manifest_output_path) or str(DEFAULT_MANIFEST_OUTPUT)

    labels = build_training_labels(
        sample_repository=sample_repository,
        paper_ledger_repository=paper_ledger_repository,
        repository=label_repository,
    )
    if not labels:
        raise RuntimeError("phase5 pipeline generated zero labels")

    training_replay_path = export_training_replay_records(
        output_path=training_replay_target,
        sample_repository=sample_repository,
        label_repository=label_repository,
    )
    training_dataset_path = export_training_dataset_bridge(
        input_path=str(training_replay_path),
        output_path=training_dataset_target,
    )
    replay_dataset_path = export_replay_dataset_bridge(
        input_path=str(training_replay_path),
        output_path=replay_dataset_target,
        paper_ledger_repository=paper_ledger_repository,
    )

    manifest = build_phase5_pipeline_manifest(
        training_replay_records_path=str(training_replay_path),
        training_dataset_path=str(training_dataset_path),
        replay_dataset_path=str(replay_dataset_path),
    )
    consumer_smoke = run_phase5_consumer_smoke_check(
        training_dataset_path=str(training_dataset_path),
        replay_dataset_path=str(replay_dataset_path),
    )

    manifest_payload = dict(manifest)
    manifest_payload["consumer_smoke"] = dict(consumer_smoke)
    manifest_path = write_phase5_pipeline_manifest(manifest_payload, output_path=manifest_target)

    return {
        "labels_count": len(labels),
        "training_replay_records_path": str(Path(training_replay_path).resolve()),
        "training_dataset_path": str(Path(training_dataset_path).resolve()),
        "replay_dataset_path": str(Path(replay_dataset_path).resolve()),
        "manifest_path": str(Path(manifest_path).resolve()),
        "manifest": manifest_payload,
        "consumer_smoke": consumer_smoke,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phase5 data pipeline and emit a checked manifest.")
    parser.add_argument("--training-replay-output", default=str(DEFAULT_TRAINING_REPLAY_OUTPUT))
    parser.add_argument("--training-dataset-output", default=str(DEFAULT_TRAINING_DATASET_OUTPUT))
    parser.add_argument("--replay-dataset-output", default=str(DEFAULT_REPLAY_DATASET_OUTPUT))
    parser.add_argument("--manifest-output", default=str(DEFAULT_MANIFEST_OUTPUT))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase5_data_pipeline(
        training_replay_output_path=str(args.training_replay_output),
        training_dataset_output_path=str(args.training_dataset_output),
        replay_dataset_output_path=str(args.replay_dataset_output),
        manifest_output_path=str(args.manifest_output),
    )
    print(json.dumps(result["manifest"], ensure_ascii=False, indent=2))
