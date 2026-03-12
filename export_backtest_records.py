import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - ExportBacktestRecords - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ExportBacktestRecords")

STATE_CANDIDATES = [
    Path("data/paper_portfolio_state.json"),
    Path("paper_portfolio_state.json"),
]
STATS_CANDIDATES = [
    Path("data/strategy_performance.json"),
    Path("strategy_performance.json"),
]
TP_TRACKER_CANDIDATES = [
    Path("data/tp_tracker.json"),
    Path("tp_tracker.json"),
]
DEFAULT_OUTPUT = Path("data/strategy_backtest_records.json")


# =========================
# low-level helpers
# =========================
def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _safe_json_obj(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _normalize_reason(reasons: List[str]) -> str:
    uniq: List[str] = []
    seen = set()
    for r in reasons:
        s = str(r or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    if not uniq:
        return "BACKTEST_EXIT"
    if len(uniq) == 1:
        return uniq[0]
    return " | ".join(uniq)


def _as_ts(v: Any, default: float = 0.0) -> float:
    if hasattr(v, "timestamp"):
        try:
            return float(v.timestamp())
        except Exception:
            return default
    return _safe_float(v, default)


# =========================
# source resolvers
# =========================
def resolve_existing_path(candidates: List[Path], cli_path: str = "") -> Optional[Path]:
    if cli_path:
        path = Path(cli_path)
        if path.exists():
            return path
        raise FileNotFoundError(f"指定路径不存在: {path}")
    for path in candidates:
        if path.exists():
            return path
    return None


# =========================
# source A: paper portfolio
# =========================
def load_closed_legs(state_path: Path) -> List[Dict[str, Any]]:
    logger.info("📥 读取 PaperPortfolio 状态文件: %s", state_path)
    with open(state_path, "r", encoding="utf-8") as f:
        raw = json.load(f) or {}

    closed_legs = raw.get("closed_legs", []) or []
    if not isinstance(closed_legs, list):
        raise ValueError("paper_portfolio_state.json 中的 closed_legs 不是列表。")
    return closed_legs


def _group_key(leg: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        str(leg.get("ca") or "").strip(),
        str(leg.get("symbol") or "UNK").strip(),
        str(leg.get("strategy") or "MIXED").upper().strip(),
        round(_safe_float(leg.get("opened_at"), 0.0), 6),
        round(_safe_float(leg.get("entry_price"), 0.0), 12),
        round(_safe_float(leg.get("entry_mcap"), 0.0), 6),
    )


def aggregate_closed_legs_to_records(closed_legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}

    for leg in closed_legs:
        ca = str(leg.get("ca") or "").strip()
        entry_price = _safe_float(leg.get("entry_price"), 0.0)
        qty = _safe_float(leg.get("qty"), 0.0)

        if not ca:
            continue
        if entry_price <= 0 and _safe_float(leg.get("entry_mcap"), 0.0) <= 0:
            continue
        if qty <= 0:
            continue

        grouped.setdefault(_group_key(leg), []).append(leg)

    records: List[Dict[str, Any]] = []
    for legs in grouped.values():
        first = legs[0]
        total_qty = sum(_safe_float(x.get("qty"), 0.0) for x in legs)
        total_gross_exit_sol = sum(_safe_float(x.get("gross_exit_sol"), 0.0) for x in legs)
        total_invested_sol = sum(_safe_float(x.get("invested_sol"), 0.0) for x in legs)
        total_cost_sol = sum(_safe_float(x.get("total_cost_sol"), 0.0) for x in legs)
        total_net_pnl_sol = sum(_safe_float(x.get("net_pnl_sol"), 0.0) for x in legs)

        entry_price = _safe_float(first.get("entry_price"), 0.0)
        entry_mcap = _safe_float(first.get("entry_mcap"), 0.0)

        weighted_exit_price = (total_gross_exit_sol / total_qty) if total_qty > 0 else 0.0
        weighted_exit_mcap_num = 0.0
        weighted_exit_mcap_den = 0.0
        for leg in legs:
            q = _safe_float(leg.get("qty"), 0.0)
            em = _safe_float(leg.get("exit_mcap"), 0.0)
            if q > 0 and em > 0:
                weighted_exit_mcap_num += em * q
                weighted_exit_mcap_den += q
        weighted_exit_mcap = weighted_exit_mcap_num / weighted_exit_mcap_den if weighted_exit_mcap_den > 0 else 0.0

        record = {
            "ca": str(first.get("ca") or "").strip(),
            "symbol": str(first.get("symbol") or "UNK").strip(),
            "strategy": str(first.get("strategy") or "MIXED").upper().strip(),
            "opened_at": _safe_float(first.get("opened_at"), 0.0),
            "closed_at": max(_safe_float(x.get("closed_at"), 0.0) for x in legs),
            "entry_price": entry_price,
            "exit_price": round(weighted_exit_price, 12),
            "entry_mcap": entry_mcap,
            "exit_mcap": round(weighted_exit_mcap, 6),
            "exit_reason": _normalize_reason([str(x.get("exit_reason") or "") for x in legs]),
            "qty": round(total_qty, 12),
            "invested_sol": round(total_invested_sol, 12),
            "gross_exit_sol": round(total_gross_exit_sol, 12),
            "total_cost_sol": round(total_cost_sol, 12),
            "net_pnl_sol": round(total_net_pnl_sol, 12),
            "partial_legs": int(len(legs)),
            "generated_from": "paper_portfolio_state.closed_legs",
        }

        if record["entry_price"] <= 0 and record["entry_mcap"] > 0 and record["exit_mcap"] > 0:
            record["entry_price"] = 1.0
            record["exit_price"] = round(record["exit_mcap"] / record["entry_mcap"], 12)

        if record["entry_price"] <= 0 or record["exit_price"] <= 0:
            continue

        records.append(record)

    records.sort(key=lambda x: (x.get("opened_at", 0.0), x.get("closed_at", 0.0)))
    return records


# =========================
# source B: stats + tp_tracker + db
# =========================
def load_json_file(path: Path, label: str) -> Any:
    logger.info("📥 读取 %s: %s", label, path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def flatten_stats_records(stats_raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(stats_raw, dict):
        return []

    flat: List[Dict[str, Any]] = []
    seen = set()
    for strategy, rows in stats_raw.items():
        if not isinstance(rows, list):
            continue
        sid = str(strategy or "MIXED").upper().strip() or "MIXED"
        for row in rows:
            if not isinstance(row, dict):
                continue
            ca = str(row.get("ca") or "").strip()
            closed_at = _safe_float(row.get("time"), 0.0)
            result = str(row.get("result") or "").strip() or "CLOSED_UNKNOWN"
            pnl = _safe_float(row.get("pnl"), 0.0)
            if not ca or closed_at <= 0:
                continue
            key = (sid, ca, round(closed_at, 6), result, round(pnl, 6))
            if key in seen:
                continue
            seen.add(key)
            flat.append(
                {
                    "strategy": sid,
                    "ca": ca,
                    "closed_at": closed_at,
                    "result": result,
                    "pnl": pnl,
                }
            )
    flat.sort(key=lambda x: (x["closed_at"], x["ca"]))
    return flat


async def load_db_context(cas: List[str]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    if not cas:
        return {}, {}

    try:
        from modules.database import db
    except Exception as e:
        logger.warning("⚠️ 无法导入 modules.database，跳过数据库补全: %s", e)
        return {}, {}

    signals: Dict[str, Dict[str, Any]] = {}
    snapshots: Dict[str, List[Dict[str, Any]]] = {}

    try:
        signal_rows = await db.fetch(
            """
            SELECT ca, source, status, rank_score, ai_narrative, entry_price, last_notified_price,
                   initial_msg_id, terminal_states
            FROM signals_snapshot
            WHERE ca = ANY($1::varchar[])
            """,
            cas,
        )
        for row in signal_rows:
            item = dict(row)
            item["terminal_states"] = _safe_json_obj(item.get("terminal_states"))
            signals[str(item.get("ca") or "").strip()] = item
    except Exception as e:
        logger.warning("⚠️ 读取 signals_snapshot 失败，继续使用本地数据: %s", e)

    try:
        snap_rows = await db.fetch(
            """
            SELECT ca, snapshot_time, time_stage, price_usd, market_cap_at_snap, liquidity_at_snap,
                   smart_money_delta, maker_vol_ratio, overhang_ratio, breakout_vol_ratio, label
            FROM golden_dog_morphology
            WHERE ca = ANY($1::varchar[])
            ORDER BY ca ASC, snapshot_time ASC
            """,
            cas,
        )
        for row in snap_rows:
            item = dict(row)
            item["snapshot_ts"] = _as_ts(item.get("snapshot_time"), 0.0)
            ca = str(item.get("ca") or "").strip()
            snapshots.setdefault(ca, []).append(item)
    except Exception as e:
        logger.warning("⚠️ 读取 golden_dog_morphology 失败，继续使用本地数据: %s", e)

    try:
        await db.close_pool()
    except Exception:
        pass

    return signals, snapshots


def _find_first_snapshot(snaps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for s in snaps or []:
        if _safe_float(s.get("price_usd"), 0.0) > 0 or _safe_float(s.get("market_cap_at_snap"), 0.0) > 0:
            return s
    return snaps[0] if snaps else None


def _find_snapshot_near(snaps: List[Dict[str, Any]], ts: float) -> Optional[Dict[str, Any]]:
    if not snaps:
        return None
    if ts <= 0:
        return snaps[-1]

    before = [s for s in snaps if _safe_float(s.get("snapshot_ts"), 0.0) <= ts]
    if before:
        return before[-1]

    # 如果全都在之后，拿最近的一条
    return min(snaps, key=lambda s: abs(_safe_float(s.get("snapshot_ts"), 0.0) - ts))


def reconstruct_records_from_stats(
    stats_records: List[Dict[str, Any]],
    tp_data: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    snapshots: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    for row in stats_records:
        ca = str(row.get("ca") or "").strip()
        if not ca:
            continue

        strategy = str(row.get("strategy") or "MIXED").upper().strip() or "MIXED"
        closed_at = _safe_float(row.get("closed_at"), 0.0)
        result = str(row.get("result") or "CLOSED_UNKNOWN")
        pnl_pct = _safe_float(row.get("pnl"), 0.0)

        tp = tp_data.get(ca, {}) if isinstance(tp_data, dict) else {}
        signal = signals.get(ca, {}) if isinstance(signals, dict) else {}
        terminal = _safe_json_obj(signal.get("terminal_states"))
        snaps = snapshots.get(ca, []) if isinstance(snapshots, dict) else []
        entry_snap = _find_first_snapshot(snaps)
        close_snap = _find_snapshot_near(snaps, closed_at)

        opened_at = _safe_float(tp.get("created_at"), 0.0)
        if opened_at <= 0:
            opened_at = _safe_float(entry_snap.get("snapshot_ts") if entry_snap else 0.0, 0.0)
        if opened_at <= 0:
            opened_at = max(0.0, closed_at - 60.0)

        entry_price = _safe_float(tp.get("entry") or tp.get("entry_price"), 0.0)
        if entry_price <= 0:
            entry_price = _safe_float(signal.get("entry_price"), 0.0)
        if entry_price <= 0 and entry_snap:
            entry_price = _safe_float(entry_snap.get("price_usd"), 0.0)

        entry_mcap = _safe_float(tp.get("initial_mcap"), 0.0)
        if entry_mcap <= 0:
            entry_mcap = _safe_float(terminal.get("cap_usd"), 0.0)
        if entry_mcap <= 0 and entry_snap:
            entry_mcap = _safe_float(entry_snap.get("market_cap_at_snap"), 0.0)

        tp_status = str(tp.get("status") or "").upper()
        tp_updated = _safe_float(tp.get("updated_at"), 0.0)
        use_tp_close = tp_status in {"WIN", "LOSS", "CLOSED"} and tp_updated > 0

        exit_price = 0.0
        if use_tp_close:
            exit_price = _safe_float(tp.get("current_price"), 0.0)
        if exit_price <= 0 and close_snap:
            exit_price = _safe_float(close_snap.get("price_usd"), 0.0)
        if exit_price <= 0 and entry_price > 0:
            exit_price = max(1e-12, entry_price * (1.0 + pnl_pct / 100.0))

        exit_mcap = 0.0
        if use_tp_close:
            exit_mcap = _safe_float(tp.get("current_mcap"), 0.0)
        if exit_mcap <= 0 and close_snap:
            exit_mcap = _safe_float(close_snap.get("market_cap_at_snap"), 0.0)
        if exit_mcap <= 0 and entry_mcap > 0 and entry_price > 0 and exit_price > 0:
            exit_mcap = entry_mcap * (exit_price / entry_price)

        symbol = str(terminal.get("symbol") or tp.get("symbol") or "UNK").strip() or "UNK"

        if entry_price <= 0 and entry_mcap > 0 and exit_mcap > 0:
            entry_price = 1.0
            exit_price = max(1e-12, exit_mcap / entry_mcap)

        if entry_price <= 0 or exit_price <= 0:
            continue
        if closed_at <= 0:
            closed_at = max(opened_at, tp_updated)
        if closed_at < opened_at:
            closed_at = opened_at

        out.append(
            {
                "ca": ca,
                "symbol": symbol,
                "strategy": strategy,
                "opened_at": round(opened_at, 6),
                "closed_at": round(closed_at, 6),
                "entry_price": round(entry_price, 12),
                "exit_price": round(exit_price, 12),
                "entry_mcap": round(entry_mcap, 6),
                "exit_mcap": round(exit_mcap, 6),
                "exit_reason": result,
                "pnl_percent": round(pnl_pct, 6),
                "generated_from": "stats+tp_tracker+signals_snapshot+golden_dog_morphology",
            }
        )

    out.sort(key=lambda x: (x.get("opened_at", 0.0), x.get("closed_at", 0.0), x.get("ca", "")))
    return out


def reconstruct_records_from_tp_only(
    tp_data: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
    snapshots: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(tp_data, dict):
        return out

    for ca, tp in tp_data.items():
        ca = str(ca or "").strip()
        if not ca or not isinstance(tp, dict):
            continue

        status = str(tp.get("status") or "").upper()
        if status not in {"WIN", "LOSS", "CLOSED"}:
            continue

        signal = signals.get(ca, {}) if isinstance(signals, dict) else {}
        terminal = _safe_json_obj(signal.get("terminal_states"))
        snaps = snapshots.get(ca, []) if isinstance(snapshots, dict) else []
        entry_snap = _find_first_snapshot(snaps)
        close_snap = _find_snapshot_near(snaps, _safe_float(tp.get("updated_at"), 0.0))

        opened_at = _safe_float(tp.get("created_at"), 0.0)
        closed_at = _safe_float(tp.get("updated_at"), opened_at)
        entry_price = _safe_float(tp.get("entry") or tp.get("entry_price"), 0.0)
        if entry_price <= 0:
            entry_price = _safe_float(signal.get("entry_price"), 0.0)
        if entry_price <= 0 and entry_snap:
            entry_price = _safe_float(entry_snap.get("price_usd"), 0.0)

        exit_price = _safe_float(tp.get("current_price"), 0.0)
        if exit_price <= 0 and close_snap:
            exit_price = _safe_float(close_snap.get("price_usd"), 0.0)

        entry_mcap = _safe_float(tp.get("initial_mcap"), 0.0)
        if entry_mcap <= 0:
            entry_mcap = _safe_float(terminal.get("cap_usd"), 0.0)
        if entry_mcap <= 0 and entry_snap:
            entry_mcap = _safe_float(entry_snap.get("market_cap_at_snap"), 0.0)

        exit_mcap = _safe_float(tp.get("current_mcap"), 0.0)
        if exit_mcap <= 0 and close_snap:
            exit_mcap = _safe_float(close_snap.get("market_cap_at_snap"), 0.0)
        if exit_mcap <= 0 and entry_mcap > 0 and entry_price > 0 and exit_price > 0:
            exit_mcap = entry_mcap * (exit_price / entry_price)

        if entry_price <= 0 and entry_mcap > 0 and exit_mcap > 0:
            entry_price = 1.0
            exit_price = max(1e-12, exit_mcap / entry_mcap)

        if entry_price <= 0 or exit_price <= 0:
            continue
        if closed_at < opened_at:
            closed_at = opened_at

        pnl_pct = (exit_price - entry_price) / entry_price * 100.0 if entry_price > 0 else 0.0
        symbol = str(terminal.get("symbol") or tp.get("symbol") or "UNK").strip() or "UNK"
        exit_reason = f"TP_TRACKER_{status}"

        out.append(
            {
                "ca": ca,
                "symbol": symbol,
                "strategy": str(tp.get("strategy_id") or tp.get("strategy") or "MIXED").upper().strip() or "MIXED",
                "opened_at": round(opened_at, 6),
                "closed_at": round(closed_at, 6),
                "entry_price": round(entry_price, 12),
                "exit_price": round(exit_price, 12),
                "entry_mcap": round(entry_mcap, 6),
                "exit_mcap": round(exit_mcap, 6),
                "exit_reason": exit_reason,
                "pnl_percent": round(pnl_pct, 6),
                "generated_from": "tp_tracker+signals_snapshot+golden_dog_morphology",
            }
        )

    out.sort(key=lambda x: (x.get("opened_at", 0.0), x.get("closed_at", 0.0), x.get("ca", "")))
    return out


# =========================
# export I/O
# =========================
def save_records(records: List[Dict[str, Any]], output_path: Path, generated_from: str, meta: Optional[Dict[str, Any]] = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "records": records,
        "records_count": len(records),
        "generated_from": generated_from,
        "meta": meta or {},
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("💾 已导出 backtest records: %s", output_path)


async def build_records_auto(state_cli: str = "", stats_cli: str = "", tp_cli: str = "") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    meta: Dict[str, Any] = {}

    state_path = resolve_existing_path(STATE_CANDIDATES, state_cli)
    if state_path:
        try:
            closed_legs = load_closed_legs(state_path)
            if closed_legs:
                records = aggregate_closed_legs_to_records(closed_legs)
                if records:
                    meta.update({
                        "source_path": str(state_path),
                        "closed_legs": len(closed_legs),
                    })
                    return records, {
                        "generated_from": "paper_portfolio_state.closed_legs",
                        **meta,
                    }
                logger.warning("⚠️ 找到 closed_legs，但聚合后没有可用 records，继续尝试 fallback。")
            else:
                logger.info("ℹ️ PaperPortfolio 状态文件存在，但 closed_legs 为空，继续尝试 fallback。")
        except Exception as e:
            logger.warning("⚠️ PaperPortfolio 导出失败，继续尝试 fallback: %s", e)

    stats_path = resolve_existing_path(STATS_CANDIDATES, stats_cli)
    tp_path = resolve_existing_path(TP_TRACKER_CANDIDATES, tp_cli)

    stats_raw = load_json_file(stats_path, "StatsEngine") if stats_path else {}
    tp_raw = load_json_file(tp_path, "TPTracker") if tp_path else {}
    stats_records = flatten_stats_records(stats_raw)

    all_cas = sorted(
        {
            str(x.get("ca") or "").strip() for x in stats_records if str(x.get("ca") or "").strip()
        }
        | {
            str(k or "").strip() for k in (tp_raw.keys() if isinstance(tp_raw, dict) else []) if str(k or "").strip()
        }
    )

    signals, snapshots = await load_db_context(all_cas)

    if stats_records:
        records = reconstruct_records_from_stats(stats_records, tp_raw if isinstance(tp_raw, dict) else {}, signals, snapshots)
        if records:
            meta.update(
                {
                    "stats_path": str(stats_path) if stats_path else "",
                    "tp_tracker_path": str(tp_path) if tp_path else "",
                    "stats_records": len(stats_records),
                    "cas": len(all_cas),
                }
            )
            return records, {
                "generated_from": "stats+tp_tracker+signals_snapshot+golden_dog_morphology",
                **meta,
            }

    tp_records = reconstruct_records_from_tp_only(tp_raw if isinstance(tp_raw, dict) else {}, signals, snapshots)
    if tp_records:
        meta.update(
            {
                "tp_tracker_path": str(tp_path) if tp_path else "",
                "cas": len(all_cas),
            }
        )
        return tp_records, {
            "generated_from": "tp_tracker+signals_snapshot+golden_dog_morphology",
            **meta,
        }

    raise ValueError(
        "未能导出任何 backtest records。当前三条路径都没有形成可用闭环："
        "1) paper_portfolio_state.json 没有 closed_legs；"
        "2) strategy_performance.json 没有可配对的平仓记录；"
        "3) tp_tracker.json 里也没有已关闭仓位。"
    )


async def async_main(args: argparse.Namespace) -> None:
    records, meta = await build_records_auto(
        state_cli=args.state,
        stats_cli=args.stats,
        tp_cli=args.tp_tracker,
    )

    output_path = Path(args.output)
    save_records(records, output_path, meta.get("generated_from", "unknown"), meta=meta)

    print("\n" + "=" * 80)
    print("Backtest Records Export Finished")
    print("=" * 80)
    print(
        json.dumps(
            {
                "output_path": str(output_path),
                "records_count": len(records),
                "generated_from": meta.get("generated_from", "unknown"),
                "meta": meta,
                "sample": records[:2],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="自动导出策略回测 records（优先 PaperPortfolio，失败则 fallback 到 Stats/TPTracker/DB）")
    parser.add_argument("--state", default="", help="可选，自定义 paper_portfolio_state.json 路径")
    parser.add_argument("--stats", default="", help="可选，自定义 strategy_performance.json 路径")
    parser.add_argument("--tp-tracker", default="", help="可选，自定义 tp_tracker.json 路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="导出 records 的目标路径")
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
