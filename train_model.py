import os
import json
import logging
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import numpy as np
import lightgbm as lgb

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - TrainModel - %(levelname)s - %(message)s",
)
logger = logging.getLogger("TrainModel")

MODEL_DIR = Path("models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = MODEL_DIR / "meme_strategy_v1.txt"
METRICS_PATH = MODEL_DIR / "meme_strategy_v1_metrics.json"
FEATURES_PATH = MODEL_DIR / "meme_strategy_v1_features.json"

DATASET_CANDIDATES = [
    Path("data/ml_training_dataset.csv"),
    Path("ml_training_dataset.csv"),
]

# 必须与 main.py 在线预测时的特征顺序严格一致
FEATURE_COLUMNS = [
    "market_cap_at_snap",     # 对应 main.py 里的 cap_usd
    "liquidity_at_snap",      # 对应 main.py 里的 liquidity_usd
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
    raise FileNotFoundError(
        f"找不到训练集文件。已检查: {[str(p) for p in DATASET_CANDIDATES]}"
    )


def load_dataset(path: Path) -> pd.DataFrame:
    logger.info(f"📥 读取训练集: {path}")
    df = pd.read_csv(path)

    missing = [c for c in FEATURE_COLUMNS + [LABEL_COLUMN] if c not in df.columns]
    if missing:
        raise ValueError(f"训练集缺少必要字段: {missing}")

    # 仅保留需要的列
    df = df[FEATURE_COLUMNS + [LABEL_COLUMN]].copy()

    # 强制数值化
    for col in FEATURE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df[LABEL_COLUMN] = pd.to_numeric(df[LABEL_COLUMN], errors="coerce")

    # 过滤无效 label
    df = df[df[LABEL_COLUMN].isin([0, 1])].copy()

    # 填补特征空值
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # label 转 int
    df[LABEL_COLUMN] = df[LABEL_COLUMN].astype(int)

    logger.info(f"✅ 清洗后样本数: {len(df)}")
    if len(df) < 50:
        raise ValueError(f"样本数过少（{len(df)}），不建议训练 LightGBM。")

    pos = int(df[LABEL_COLUMN].sum())
    neg = int(len(df) - pos)
    logger.info(f"📊 标签分布: 正样本={pos}, 负样本={neg}")

    if pos == 0 or neg == 0:
        raise ValueError("标签只有单一类别，无法训练二分类模型。")

    return df


def split_xy(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    X = df[FEATURE_COLUMNS].copy()
    y = df[LABEL_COLUMN].copy()
    return X, y


def build_model() -> lgb.LGBMClassifier:
    # 这里先给稳定默认参数，后续再交给 Optuna 搜索
    return lgb.LGBMClassifier(
        objective="binary",
        boosting_type="gbdt",
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=31,
        max_depth=-1,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.0,
        reg_lambda=0.0,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )


def evaluate_model(model: lgb.LGBMClassifier, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    prob = model.predict_proba(X_test)[:, 1]
    pred = (prob >= 0.5).astype(int)

    metrics = {
        "accuracy": float(accuracy_score(y_test, pred)),
        "precision": float(precision_score(y_test, pred, zero_division=0)),
        "recall": float(recall_score(y_test, pred, zero_division=0)),
        "f1": float(f1_score(y_test, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, prob)) if len(set(y_test)) > 1 else 0.0,
        "confusion_matrix": confusion_matrix(y_test, pred).tolist(),
        "test_samples": int(len(y_test)),
    }
    return metrics


def save_outputs(model: lgb.LGBMClassifier, metrics: dict):
    booster = model.booster_
    booster.save_model(str(MODEL_PATH))

    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    with open(FEATURES_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "feature_columns": FEATURE_COLUMNS,
                "label_column": LABEL_COLUMN,
                "model_path": str(MODEL_PATH),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    logger.info(f"💾 模型已保存: {MODEL_PATH}")
    logger.info(f"💾 指标已保存: {METRICS_PATH}")
    logger.info(f"💾 特征定义已保存: {FEATURES_PATH}")


def train_meme_hunter_model():
    dataset_path = resolve_dataset_path()
    df = load_dataset(dataset_path)
    X, y = split_xy(df)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y,
    )

    logger.info(
        f"🧪 数据切分完成: train={len(X_train)}, test={len(X_test)}"
    )

    model = build_model()
    logger.info("🚀 开始训练 LightGBM 模型...")

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_test, y_test)],
        eval_metric="binary_logloss",
    )

    metrics = evaluate_model(model, X_test, y_test)

    logger.info("📈 训练完成，评估结果如下：")
    for k, v in metrics.items():
        logger.info(f"  - {k}: {v}")

    save_outputs(model, metrics)
    return metrics


def main():
    try:
        metrics = train_meme_hunter_model()
        print("\n" + "=" * 80)
        print("LightGBM Training Finished")
        print("=" * 80)
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.exception(f"💥 训练失败: {e}")
        raise


if __name__ == "__main__":
    main()