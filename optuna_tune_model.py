import os
import json
import logging
from pathlib import Path
from typing import Dict, Any

import optuna
import pandas as pd
import numpy as np
import lightgbm as lgb

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - OptunaTuneModel - %(levelname)s - %(message)s",
)
logger = logging.getLogger("OptunaTuneModel")

MODEL_DIR = Path("models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

BEST_MODEL_PATH = MODEL_DIR / "meme_strategy_v1.txt"
BEST_METRICS_PATH = MODEL_DIR / "meme_strategy_v1_metrics.json"
BEST_FEATURES_PATH = MODEL_DIR / "meme_strategy_v1_features.json"
OPTUNA_SUMMARY_PATH = MODEL_DIR / "optuna_model_summary.json"

DATASET_CANDIDATES = [
    Path("data/ml_training_dataset.csv"),
    Path("ml_training_dataset.csv"),
]

FEATURE_COLUMNS = [
    "market_cap_at_snap",
    "liquidity_at_snap",
    "smart_money_delta",
    "maker_vol_ratio",
    "overhang_ratio",
    "breakout_vol_ratio",
]
LABEL_COLUMN = "label"


def resolve_dataset_path() -> Path:
    for path in DATASET_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(f"找不到训练集文件。已检查: {[str(p) for p in DATASET_CANDIDATES]}")


def load_dataset(path: Path) -> pd.DataFrame:
    logger.info(f"📥 读取训练集: {path}")
    df = pd.read_csv(path)

    missing = [c for c in FEATURE_COLUMNS + [LABEL_COLUMN] if c not in df.columns]
    if missing:
        raise ValueError(f"训练集缺少必要字段: {missing}")

    df = df[FEATURE_COLUMNS + [LABEL_COLUMN]].copy()

    for col in FEATURE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df[LABEL_COLUMN] = pd.to_numeric(df[LABEL_COLUMN], errors="coerce")

    df = df[df[LABEL_COLUMN].isin([0, 1])].copy()
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df[LABEL_COLUMN] = df[LABEL_COLUMN].astype(int)

    if len(df) < 50:
        raise ValueError(f"样本数过少（{len(df)}），不建议运行 Optuna。")

    pos = int(df[LABEL_COLUMN].sum())
    neg = int(len(df) - pos)
    logger.info(f"📊 标签分布: 正样本={pos}, 负样本={neg}")

    if pos == 0 or neg == 0:
        raise ValueError("标签只有单一类别，无法训练二分类模型。")

    return df


def build_objective(X_train, X_valid, y_train, y_valid):
    def objective(trial: optuna.Trial) -> float:
        params = {
            "objective": "binary",
            "boosting_type": "gbdt",
            "metric": "binary_logloss",
            "verbosity": -1,
            "random_state": 42,
            "n_jobs": -1,
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.08, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 16, 96),
            "max_depth": trial.suggest_int("max_depth", 3, 12),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 80),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.6, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.6, 1.0),
            "bagging_freq": trial.suggest_int("bagging_freq", 1, 7),
            "lambda_l1": trial.suggest_float("lambda_l1", 0.0, 5.0),
            "lambda_l2": trial.suggest_float("lambda_l2", 0.0, 5.0),
            "min_gain_to_split": trial.suggest_float("min_gain_to_split", 0.0, 1.0),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.8, 3.0),
        }

        train_data = lgb.Dataset(X_train, label=y_train)
        valid_data = lgb.Dataset(X_valid, label=y_valid)

        model = lgb.train(
            params,
            train_data,
            num_boost_round=600,
            valid_sets=[valid_data],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50, verbose=False),
            ],
        )

        prob = model.predict(X_valid, num_iteration=model.best_iteration)
        pred = (prob >= 0.5).astype(int)

        precision = precision_score(y_valid, pred, zero_division=0)
        recall = recall_score(y_valid, pred, zero_division=0)
        f1 = f1_score(y_valid, pred, zero_division=0)
        auc = roc_auc_score(y_valid, prob) if len(set(y_valid)) > 1 else 0.0

        # 你当前更需要“能抓到高质量正样本”，所以目标函数偏向 precision + f1 + auc
        score = (precision * 0.45) + (f1 * 0.35) + (auc * 0.20)

        trial.set_user_attr("precision", float(precision))
        trial.set_user_attr("recall", float(recall))
        trial.set_user_attr("f1", float(f1))
        trial.set_user_attr("auc", float(auc))
        trial.set_user_attr("best_iteration", int(model.best_iteration or 0))

        return float(score)

    return objective


def train_final_model(best_params: Dict[str, Any], X_train, X_valid, y_train, y_valid):
    params = {
        "objective": "binary",
        "boosting_type": "gbdt",
        "metric": "binary_logloss",
        "verbosity": -1,
        "random_state": 42,
        "n_jobs": -1,
        **best_params,
    }

    train_data = lgb.Dataset(X_train, label=y_train)
    valid_data = lgb.Dataset(X_valid, label=y_valid)

    model = lgb.train(
        params,
        train_data,
        num_boost_round=600,
        valid_sets=[valid_data],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
        ],
    )
    return model


def evaluate_model(model, X_valid, y_valid) -> dict:
    prob = model.predict(X_valid, num_iteration=model.best_iteration)
    pred = (prob >= 0.5).astype(int)

    metrics = {
        "precision": float(precision_score(y_valid, pred, zero_division=0)),
        "recall": float(recall_score(y_valid, pred, zero_division=0)),
        "f1": float(f1_score(y_valid, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_valid, prob)) if len(set(y_valid)) > 1 else 0.0,
        "best_iteration": int(model.best_iteration or 0),
        "validation_samples": int(len(y_valid)),
    }
    return metrics


def save_outputs(model, metrics: dict, best_params: dict, study: optuna.Study):
    model.save_model(str(BEST_MODEL_PATH))

    with open(BEST_METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    with open(BEST_FEATURES_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "feature_columns": FEATURE_COLUMNS,
                "label_column": LABEL_COLUMN,
                "model_path": str(BEST_MODEL_PATH),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    summary = {
        "best_value": float(study.best_value),
        "best_params": best_params,
        "best_trial_number": int(study.best_trial.number),
        "best_trial_user_attrs": study.best_trial.user_attrs,
        "n_trials": len(study.trials),
        "direction": study.direction.name,
    }

    with open(OPTUNA_SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 Optuna 最优模型已保存: {BEST_MODEL_PATH}")
    logger.info(f"💾 模型指标已保存: {BEST_METRICS_PATH}")
    logger.info(f"💾 特征定义已保存: {BEST_FEATURES_PATH}")
    logger.info(f"💾 Optuna 摘要已保存: {OPTUNA_SUMMARY_PATH}")


def main():
    dataset_path = resolve_dataset_path()
    df = load_dataset(dataset_path)

    X = df[FEATURE_COLUMNS].copy()
    y = df[LABEL_COLUMN].copy()

    X_train, X_valid, y_train, y_valid = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y,
    )

    logger.info(f"🧪 数据切分完成: train={len(X_train)}, valid={len(X_valid)}")

    study = optuna.create_study(direction="maximize", study_name="meme_strategy_lgbm")
    logger.info("🚀 开始 Optuna 调参与搜索最优 LightGBM 参数...")

    study.optimize(
        build_objective(X_train, X_valid, y_train, y_valid),
        n_trials=40,
        show_progress_bar=False,
    )

    logger.info(f"🏆 Optuna 最优得分: {study.best_value:.6f}")
    logger.info(f"🏆 最优参数: {study.best_params}")

    final_model = train_final_model(study.best_params, X_train, X_valid, y_train, y_valid)
    metrics = evaluate_model(final_model, X_valid, y_valid)

    logger.info("📈 最终模型验证指标：")
    for k, v in metrics.items():
        logger.info(f"  - {k}: {v}")

    save_outputs(final_model, metrics, study.best_params, study)

    print("\n" + "=" * 80)
    print("Optuna LightGBM Tuning Finished")
    print("=" * 80)
    print(json.dumps(
        {
            "best_value": study.best_value,
            "best_params": study.best_params,
            "metrics": metrics,
        },
        ensure_ascii=False,
        indent=2
    ))


if __name__ == "__main__":
    main()