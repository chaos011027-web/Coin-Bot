import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Tuple

import optuna

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - OptunaTuneStrategy - %(levelname)s - %(message)s",
)
logger = logging.getLogger("OptunaTuneStrategy")

RECORD_CANDIDATES = [
    Path("data/strategy_backtest_records.json"),
    Path("data/backtest_records.json"),
]
MODEL_DIR = Path("models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)
BEST_PARAMS_PATH = MODEL_DIR / "strategy_best_params.json"
OPTUNA_SUMMARY_PATH = MODEL_DIR / "strategy_optuna_summary.json"
BEST_BACKTEST_PATH = MODEL_DIR / "strategy_best_backtest.json"

INITIAL_CAPITAL_SOL = 1.0
RESERVE_CASH_SOL = 0.25
MAX_OPEN_POSITIONS = 3
FEE_RATE_PER_SIDE = 0.0030
SLIPPAGE_RATE_PER_SIDE = 0.0040
FIXED_COST_PER_ORDER_SOL = 0.00001
N_TRIALS = 40

try:
    from modules.strategy_engine import DEFAULT_STRATEGY_PARAMS
except Exception:
    from strategy_engine import DEFAULT_STRATEGY_PARAMS

STRATEGIES = ["SMART_TREND", "SNIPER_PLAY", "BUNDLE_CTRL", "MIXED"]


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def resolve_records_path() -> Path:
    for path in RECORD_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "找不到策略回测 records 文件。请先运行 export_backtest_records.py，或自行准备："
        f" {[str(p) for p in RECORD_CANDIDATES]}"
    )


def load_records(path: Path) -> List[Dict[str, Any]]:
    logger.info("📥 读取策略回测 records: %s", path)
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        records = raw.get("records", []) or []
    elif isinstance(raw, list):
        records = raw
    else:
        raise ValueError("records 文件格式无效，应为 list 或 {'records': [...]}。")

    norm: List[Dict[str, Any]] = []
    for r in records:
        rec = {
            "ca": str(r.get("ca") or "").strip(),
            "symbol": str(r.get("symbol") or "UNK").strip(),
            "strategy": str(r.get("strategy") or "MIXED").upper().strip(),
            "opened_at": _safe_float(r.get("opened_at"), 0.0),
            "closed_at": _safe_float(r.get("closed_at"), 0.0),
            "entry_price": _safe_float(r.get("entry_price"), 0.0),
            "exit_price": _safe_float(r.get("exit_price"), 0.0),
            "entry_mcap": _safe_float(r.get("entry_mcap"), 0.0),
            "exit_mcap": _safe_float(r.get("exit_mcap"), 0.0),
            "exit_reason": str(r.get("exit_reason") or "BACKTEST_EXIT"),
        }

        if not rec["ca"]:
            continue
        if rec["opened_at"] <= 0:
            continue
        if rec["closed_at"] <= 0:
            rec["closed_at"] = rec["opened_at"]

        if rec["entry_price"] <= 0 or rec["exit_price"] <= 0:
            if rec["entry_mcap"] > 0 and rec["exit_mcap"] > 0:
                rec["entry_price"] = 1.0
                rec["exit_price"] = rec["exit_mcap"] / rec["entry_mcap"]

        if rec["entry_price"] <= 0 or rec["exit_price"] <= 0:
            continue

        if rec["strategy"] not in STRATEGIES:
            rec["strategy"] = "MIXED"

        norm.append(rec)

    if len(norm) < 10:
        raise ValueError(f"可用 backtest records 过少（{len(norm)} 条），不建议运行 Optuna。")

    norm.sort(key=lambda x: (x["opened_at"], x["closed_at"]))
    logger.info("📊 可用 records: %s", len(norm))
    return norm


def _strategy_default_alloc(strategy: str) -> float:
    cfg = DEFAULT_STRATEGY_PARAMS.get("strategy_configs", {}).get(strategy, {})
    return _safe_float(cfg.get("alloc_pct"), _safe_float(cfg.get("paper_alloc_sol"), 0.08))


class PortfolioBacktester:
    def __init__(
        self,
        alloc_map: Dict[str, float],
        initial_capital_sol: float = INITIAL_CAPITAL_SOL,
        reserve_cash_sol: float = RESERVE_CASH_SOL,
        max_open_positions: int = MAX_OPEN_POSITIONS,
        fee_rate_per_side: float = FEE_RATE_PER_SIDE,
        slippage_rate_per_side: float = SLIPPAGE_RATE_PER_SIDE,
        fixed_cost_per_order_sol: float = FIXED_COST_PER_ORDER_SOL,
    ):
        self.alloc_map = {k: max(0.0, _safe_float(v, _strategy_default_alloc(k))) for k, v in alloc_map.items()}
        self.initial_capital_sol = float(initial_capital_sol)
        self.reserve_cash_sol = float(reserve_cash_sol)
        self.max_open_positions = int(max_open_positions)
        self.fee_rate_per_side = float(fee_rate_per_side)
        self.slippage_rate_per_side = float(slippage_rate_per_side)
        self.fixed_cost_per_order_sol = float(fixed_cost_per_order_sol)
        self.reset()

    def reset(self) -> None:
        self.cash_sol = self.initial_capital_sol
        self.open_positions: Dict[str, Dict[str, Any]] = {}
        self.closed_trades: List[Dict[str, Any]] = []

    def _entry_cost_sol(self, alloc_sol: float) -> float:
        return alloc_sol * (self.fee_rate_per_side + self.slippage_rate_per_side) + self.fixed_cost_per_order_sol

    def _exit_cost_sol(self, gross_exit_sol: float) -> float:
        return gross_exit_sol * (self.fee_rate_per_side + self.slippage_rate_per_side) + self.fixed_cost_per_order_sol

    def _alloc_for(self, strategy: str) -> float:
        return max(0.0, _safe_float(self.alloc_map.get(strategy), _strategy_default_alloc(strategy)))

    def _close_due_positions(self, ts: float) -> None:
        due = [ca for ca, pos in self.open_positions.items() if _safe_float(pos.get("closed_at"), 0.0) <= ts]
        due.sort(key=lambda ca: _safe_float(self.open_positions[ca].get("closed_at"), 0.0))
        for ca in due:
            pos = self.open_positions.pop(ca)
            gross_exit_sol = _safe_float(pos.get("qty"), 0.0) * _safe_float(pos.get("exit_price"), 0.0)
            exit_cost = self._exit_cost_sol(gross_exit_sol)
            invested_sol = _safe_float(pos.get("invested_sol"), 0.0)
            net_pnl_sol = gross_exit_sol - exit_cost - invested_sol
            net_return_pct = (net_pnl_sol / invested_sol * 100.0) if invested_sol > 0 else 0.0
            self.cash_sol += max(0.0, gross_exit_sol - exit_cost)
            self.closed_trades.append(
                {
                    "strategy": pos.get("strategy", "MIXED"),
                    "opened_at": _safe_float(pos.get("opened_at"), 0.0),
                    "closed_at": _safe_float(pos.get("closed_at"), 0.0),
                    "invested_sol": invested_sol,
                    "gross_exit_sol": gross_exit_sol,
                    "total_cost_sol": _safe_float(pos.get("entry_cost_sol"), 0.0) + exit_cost,
                    "net_pnl_sol": net_pnl_sol,
                    "net_return_pct": net_return_pct,
                }
            )

    def run(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.reset()

        for r in records:
            now = _safe_float(r.get("opened_at"), 0.0)
            self._close_due_positions(now)

            ca = str(r.get("ca") or "").strip()
            if not ca or ca in self.open_positions:
                continue
            if len(self.open_positions) >= self.max_open_positions:
                continue
            if self.cash_sol <= self.reserve_cash_sol:
                continue

            entry_price = _safe_float(r.get("entry_price"), 0.0)
            exit_price = _safe_float(r.get("exit_price"), 0.0)
            if entry_price <= 0 or exit_price <= 0:
                continue

            strategy = str(r.get("strategy") or "MIXED").upper()
            alloc_sol = self._alloc_for(strategy)
            free_cap = max(0.0, self.cash_sol - self.reserve_cash_sol)
            alloc_sol = min(alloc_sol, free_cap)
            if alloc_sol <= 0:
                continue

            entry_cost = self._entry_cost_sol(alloc_sol)
            if alloc_sol + entry_cost > self.cash_sol:
                alloc_sol = max(0.0, self.cash_sol - self.reserve_cash_sol - entry_cost)
            if alloc_sol <= 0:
                continue

            qty = alloc_sol / entry_price
            self.cash_sol -= (alloc_sol + entry_cost)
            self.open_positions[ca] = {
                "strategy": strategy,
                "opened_at": now,
                "closed_at": _safe_float(r.get("closed_at"), now),
                "exit_price": exit_price,
                "qty": qty,
                "invested_sol": alloc_sol,
                "entry_cost_sol": entry_cost,
            }

        self._close_due_positions(float("inf"))
        return self.summary()

    def summary(self) -> Dict[str, Any]:
        trades = sorted(self.closed_trades, key=lambda x: _safe_float(x.get("closed_at"), 0.0))
        total_trades = len(trades)
        wins = [t for t in trades if _safe_float(t.get("net_pnl_sol"), 0.0) > 0]
        losses = [t for t in trades if _safe_float(t.get("net_pnl_sol"), 0.0) <= 0]
        total_net = sum(_safe_float(t.get("net_pnl_sol"), 0.0) for t in trades)
        total_cost = sum(_safe_float(t.get("total_cost_sol"), 0.0) for t in trades)

        running = self.initial_capital_sol
        peak = running
        max_dd = 0.0
        for t in trades:
            running += _safe_float(t.get("net_pnl_sol"), 0.0)
            if running > peak:
                peak = running
            dd = (peak - running) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        by_strategy: Dict[str, Dict[str, Any]] = {}
        for t in trades:
            s = str(t.get("strategy") or "MIXED")
            row = by_strategy.setdefault(
                s,
                {"trades": 0, "wins": 0, "net_pnl_sol": 0.0, "cost_sol": 0.0},
            )
            row["trades"] += 1
            pnl = _safe_float(t.get("net_pnl_sol"), 0.0)
            row["net_pnl_sol"] += pnl
            row["cost_sol"] += _safe_float(t.get("total_cost_sol"), 0.0)
            if pnl > 0:
                row["wins"] += 1

        for row in by_strategy.values():
            trades_n = int(row["trades"])
            row["win_rate_pct"] = round((row["wins"] / trades_n * 100.0), 2) if trades_n > 0 else 0.0
            row["net_pnl_sol"] = round(row["net_pnl_sol"], 6)
            row["cost_sol"] = round(row["cost_sol"], 6)

        equity = self.cash_sol
        return {
            "initial_capital_sol": round(self.initial_capital_sol, 6),
            "cash_sol": round(self.cash_sol, 6),
            "equity_sol": round(equity, 6),
            "open_positions": len(self.open_positions),
            "closed_trades": total_trades,
            "win_rate_pct": round((len(wins) / total_trades * 100.0), 2) if total_trades > 0 else 0.0,
            "loss_rate_pct": round((len(losses) / total_trades * 100.0), 2) if total_trades > 0 else 0.0,
            "total_net_pnl_sol": round(total_net, 6),
            "total_cost_sol": round(total_cost, 6),
            "roi_pct": round(((equity - self.initial_capital_sol) / self.initial_capital_sol * 100.0), 2) if self.initial_capital_sol > 0 else 0.0,
            "max_drawdown_pct": round(max_dd * 100.0, 2),
            "by_strategy": by_strategy,
        }


def _default_trade_plan() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for s in STRATEGIES:
        cfg = deepcopy(DEFAULT_STRATEGY_PARAMS.get("strategy_configs", {}).get(s, {}))
        out[s] = {
            "alloc_pct": _safe_float(cfg.get("alloc_pct"), _safe_float(cfg.get("paper_alloc_sol"), 0.08)),
            "sl_pct": _safe_float(cfg.get("sl_pct"), 0.10),
            "tp_targets": list(cfg.get("tp_targets", [])),
        }
    return out


def build_objective(records: List[Dict[str, Any]]):
    defaults = _default_trade_plan()

    def objective(trial: optuna.Trial) -> float:
        alloc_map = {
            "SMART_TREND": trial.suggest_float("alloc_smart_trend", 0.08, 0.30),
            "SNIPER_PLAY": trial.suggest_float("alloc_sniper_play", 0.05, 0.22),
            "BUNDLE_CTRL": trial.suggest_float("alloc_bundle_ctrl", 0.02, 0.12),
            "MIXED": trial.suggest_float("alloc_mixed", 0.03, 0.16),
        }

        summary = PortfolioBacktester(alloc_map=alloc_map).run(records)
        roi = _safe_float(summary.get("roi_pct"), 0.0)
        dd = _safe_float(summary.get("max_drawdown_pct"), 0.0)
        win_rate = _safe_float(summary.get("win_rate_pct"), 0.0)
        trades = _safe_float(summary.get("closed_trades"), 0.0)

        # 目标：更高净值 + 更低回撤 + 不明显牺牲成交覆盖
        score = roi - (dd * 0.65) + (win_rate * 0.10) + min(trades, 50.0) * 0.05

        trial.set_user_attr("roi_pct", roi)
        trial.set_user_attr("max_drawdown_pct", dd)
        trial.set_user_attr("win_rate_pct", win_rate)
        trial.set_user_attr("closed_trades", int(trades))
        trial.set_user_attr("equity_sol", _safe_float(summary.get("equity_sol"), 0.0))

        return float(score)

    return objective


def build_best_params(best_alloc_map: Dict[str, float], best_summary: Dict[str, Any], records_path: Path) -> Dict[str, Any]:
    defaults = _default_trade_plan()

    alloc_map = {k: round(_safe_float(best_alloc_map.get(k), defaults[k]["alloc_pct"]), 4) for k in STRATEGIES}
    sl_map = {k: round(_safe_float(defaults[k]["sl_pct"], 0.10), 4) for k in STRATEGIES}
    tp_map = {k: [round(_safe_float(x, 0.0), 4) for x in defaults[k]["tp_targets"]] for k in STRATEGIES}

    return {
        "generated_by": "optuna_tune_strategy.py",
        "source_records": str(records_path),
        "notes": {
            "alloc_map": "本次 Optuna 基于已有 closed-leg records 的离线组合回测优化。",
            "sl_map": "当前 records 不含完整盘中路径，SL 先沿用默认参数。",
            "tp_map": "当前 records 不含完整盘中路径，TP 先沿用默认参数。",
            "score_thresholds": "当前 records 不含在线打分原始特征，分数阈值先沿用默认参数。",
            "filters": "当前 records 不含完整结构特征，过滤阈值先沿用默认参数。",
        },
        "score_thresholds": {
            "strong_bull_min": _safe_float(DEFAULT_STRATEGY_PARAMS.get("gates", {}).get("smart_trend_min_score"), 78.0),
            "bull_min": _safe_float(DEFAULT_STRATEGY_PARAMS.get("gates", {}).get("sniper_play_min_score"), 66.0),
            "mixed_min": _safe_float(DEFAULT_STRATEGY_PARAMS.get("gates", {}).get("mixed_min_score"), 48.0),
        },
        "filters": {
            "min_liquidity_usd": _safe_float(DEFAULT_STRATEGY_PARAMS.get("gates", {}).get("min_liq_for_trend"), 12000.0),
            "max_top10_pct": _safe_float(DEFAULT_STRATEGY_PARAMS.get("gates", {}).get("warn_top10_max"), 35.0),
            "max_deployer_pct": _safe_float(DEFAULT_STRATEGY_PARAMS.get("gates", {}).get("dev_warn_min"), 8.0),
        },
        "trade_plan": {
            "alloc_map": alloc_map,
            "sl_map": sl_map,
            "tp_map": tp_map,
        },
        "best_backtest": best_summary,
    }


def save_outputs(best_params: Dict[str, Any], best_summary: Dict[str, Any], study: optuna.Study) -> None:
    with open(BEST_PARAMS_PATH, "w", encoding="utf-8") as f:
        json.dump(best_params, f, ensure_ascii=False, indent=2)

    with open(BEST_BACKTEST_PATH, "w", encoding="utf-8") as f:
        json.dump(best_summary, f, ensure_ascii=False, indent=2)

    summary = {
        "best_value": float(study.best_value),
        "best_params": study.best_params,
        "best_trial_number": int(study.best_trial.number),
        "best_trial_user_attrs": study.best_trial.user_attrs,
        "n_trials": len(study.trials),
        "direction": study.direction.name,
        "output_params_path": str(BEST_PARAMS_PATH),
        "output_backtest_path": str(BEST_BACKTEST_PATH),
    }

    with open(OPTUNA_SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info("💾 已保存最优策略参数: %s", BEST_PARAMS_PATH)
    logger.info("💾 已保存最优回测摘要: %s", BEST_BACKTEST_PATH)
    logger.info("💾 已保存 Optuna 摘要: %s", OPTUNA_SUMMARY_PATH)


def main():
    records_path = resolve_records_path()
    records = load_records(records_path)

    study = optuna.create_study(direction="maximize", study_name="strategy_trade_plan_optuna")
    logger.info("🚀 开始 Optuna 策略调参（当前针对 alloc_map 做离线组合优化）...")

    study.optimize(
        build_objective(records),
        n_trials=N_TRIALS,
        show_progress_bar=False,
    )

    logger.info("🏆 Optuna 最优得分: %.6f", study.best_value)
    logger.info("🏆 最优参数: %s", study.best_params)

    best_alloc_map = {
        "SMART_TREND": _safe_float(study.best_params.get("alloc_smart_trend"), _strategy_default_alloc("SMART_TREND")),
        "SNIPER_PLAY": _safe_float(study.best_params.get("alloc_sniper_play"), _strategy_default_alloc("SNIPER_PLAY")),
        "BUNDLE_CTRL": _safe_float(study.best_params.get("alloc_bundle_ctrl"), _strategy_default_alloc("BUNDLE_CTRL")),
        "MIXED": _safe_float(study.best_params.get("alloc_mixed"), _strategy_default_alloc("MIXED")),
    }
    best_summary = PortfolioBacktester(alloc_map=best_alloc_map).run(records)
    best_params = build_best_params(best_alloc_map, best_summary, records_path)
    save_outputs(best_params, best_summary, study)

    print("\n" + "=" * 80)
    print("Optuna Strategy Tuning Finished")
    print("=" * 80)
    print(json.dumps(
        {
            "records_path": str(records_path),
            "records_count": len(records),
            "best_value": study.best_value,
            "best_alloc_map": {k: round(v, 4) for k, v in best_alloc_map.items()},
            "best_backtest": best_summary,
            "output": str(BEST_PARAMS_PATH),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
