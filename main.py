import asyncio
import logging
import sys
import time
import re
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery

from modules.listener import start as start_listener
from modules.data_fetcher import (
    get_market_data,
    get_gmgn_analytics,
    get_helius_security,
    get_rugcheck_data,
    get_goplus_security,
    background_fetcher,
    close_fetchers,
    fetcher,
    prepare_fetcher_profiles,
)
from modules.brain import brain
from modules.notifier import (
    notify_user_fast,
    update_user_message,
    send_thread_reply,
    build_ai_report_text,
    build_milestone_text,
)
from modules.database import db
from modules.bitquery_client import bitquery
from modules.insightx import insightx_agent
from modules.strategy_engine import detect_strategy
from modules.tp_tracker import tp_tracker
from modules.stats_engine import stats_engine
from modules.risk_engine import apply_final_gate
from modules.image_generator import generate_milestone_image
from modules.paper_portfolio_engine import paper_portfolio_engine
from modules.canonical_metrics import (
    apply_canonical_metrics,
    canonical_pipeline_settings,
    canonical_thresholds,
    get_canonical_stage,
    get_confirmed_top10_pct,
    get_decision_liquidity_context,
    get_decision_liquidity_usd,
)
from config.settings import ADMIN_CHAT_ID

logger = logging.getLogger("Main")

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"run_{datetime.now().strftime('%Y-%m-%d')}.log"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="ignore")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
    force=True,
)


def spawn_task(coro, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)

    def _handle_task_result(t: asyncio.Task):
        try:
            t.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"💥 后台任务 [{name}] 发生致命崩溃: {e}", exc_info=True)

    task.add_done_callback(_handle_task_result)
    return task


_avatar_enrichment_queue: asyncio.Queue[tuple[str, int, int]] = asyncio.Queue()
_avatar_enrichment_pending: set[str] = set()
_avatar_enrichment_lock = asyncio.Lock()


async def _enqueue_avatar_enrichment(ca: str, chat_id: int, message_id: int):
    ca = str(ca or "").strip()
    if not ca:
        return
    async with _avatar_enrichment_lock:
        if ca in _avatar_enrichment_pending:
            logger.info("AvatarEnrichment | ca=%s | queued=false | reason=already_pending", ca[:8])
            return
        _avatar_enrichment_pending.add(ca)
    await _avatar_enrichment_queue.put((ca, int(chat_id or 0), int(message_id or 0)))
    logger.info("AvatarEnrichment | ca=%s | queued=true", ca[:8])


async def _avatar_enrichment_loop():
    logger.info("AvatarEnrichment | worker=started")
    while True:
        ca = ""
        got_item = False
        try:
            ca, chat_id, message_id = await _avatar_enrichment_queue.get()
            got_item = True
            record = await db.get_signal_snapshot(ca)
            terminal_states = record.get("terminal_states", {}) if record else {}
            message_snapshot = record.get("message_snapshot") if isinstance((record or {}).get("message_snapshot"), dict) else {}
            effective_chat_id = int(chat_id or terminal_states.get("reply_chat_id") or 0)
            effective_msg_id = int(message_id or (record or {}).get("initial_msg_id") or 0)

            stable_snapshot = dict(terminal_states.get("stable_snapshot") or {}) if isinstance(terminal_states.get("stable_snapshot"), dict) else {}
            snapshot_seed = stable_snapshot or message_snapshot or {}

            token_data = normalize_token_data(ca, snapshot_seed, "AVATAR_ENRICH", effective_chat_id, effective_msg_id)
            token_data = _merge_existing_terminal(token_data, terminal_states)

            def _build_avatar_refresh_payload(image_path: str, image_url: str = "", image_source: str = "") -> dict:
                render_payload = dict(stable_snapshot)
                render_payload = _merge_existing_terminal(render_payload, terminal_states)
                render_payload = _merge_existing_terminal(render_payload, {"stable_snapshot": token_data})
                if not render_payload:
                    render_payload = dict(token_data)

                if image_url:
                    render_payload["token_image_url"] = image_url
                if image_source:
                    render_payload["token_image_source"] = image_source
                if image_path:
                    render_payload["token_image_path"] = image_path
                return render_payload

            def _commit_avatar_patch(render_payload: dict) -> dict:
                terminal_states["token_image_path"] = render_payload.get("token_image_path", terminal_states.get("token_image_path", ""))
                terminal_states["token_image_url"] = render_payload.get("token_image_url", terminal_states.get("token_image_url", ""))
                terminal_states["token_image_source"] = render_payload.get("token_image_source", terminal_states.get("token_image_source", ""))
                patched_snapshot = dict(stable_snapshot)
                patched_snapshot["token_image_path"] = render_payload.get("token_image_path", patched_snapshot.get("token_image_path", ""))
                patched_snapshot["token_image_url"] = render_payload.get("token_image_url", patched_snapshot.get("token_image_url", ""))
                patched_snapshot["token_image_source"] = render_payload.get("token_image_source", patched_snapshot.get("token_image_source", ""))
                terminal_states["stable_snapshot"] = patched_snapshot
                return render_payload

            if token_data.get("token_image_path"):
                logger.info("AvatarEnrichment | ca=%s | skipped=true | reason=already_has_path", ca[:8])
                continue

            stable_avatar_path = ""
            try:
                stable_avatar_path = background_fetcher._existing_avatar_path(ca)
            except Exception:
                stable_avatar_path = ""
            if stable_avatar_path:
                token_data = _commit_avatar_patch(
                    _build_avatar_refresh_payload(
                        stable_avatar_path,
                        str(token_data.get("token_image_url") or terminal_states.get("token_image_url") or ""),
                        str(token_data.get("token_image_source") or terminal_states.get("token_image_source") or "stable_cache"),
                    )
                )
                logger.info("AvatarEnrichment | ca=%s | success=true | source=stable_cache", ca[:8])
                entry_price = _safe_float(
                    (record or {}).get("entry_price")
                    or terminal_states.get("entry_price")
                    or terminal_states.get("milestone_anchor_price"),
                    0.0,
                )
                initial_msg_id = int((record or {}).get("initial_msg_id") or effective_msg_id or 0)
                status = terminal_states.get("signal_state") or (record or {}).get("status")

                if initial_msg_id > 0:
                    await safe_call(
                        db.save_initial_signal(
                            ca,
                            (record or {}).get("source") or "SYSTEM",
                            entry_price,
                            initial_msg_id,
                            terminal_states,
                            status=status,
                        ),
                        3,
                        "AvatarEnrich_DB",
                    )

                if effective_chat_id > 0 and initial_msg_id > 0:
                    decision = {
                        "verdict": terminal_states.get("decision_action") or ACTION_WATCH,
                        "reason": terminal_states.get("decision_reason")
                        or (record or {}).get("ai_narrative")
                        or terminal_states.get("ai_narrative")
                        or "头像已补全，已刷新面板。",
                    }
                    await safe_call(
                        update_user_message(
                            chat_id=effective_chat_id,
                            message_id=initial_msg_id,
                            ca=ca,
                            token_data=token_data,
                            decision=decision,
                        ),
                        12,
                        "AvatarEnrich_Refresh",
                    )
                continue

            avatar_path = await safe_call(
                background_fetcher.ensure_token_avatar(
                    ca,
                    token_data.get("token_image_url", ""),
                    token_data.get("token_image_source", ""),
                ),
                8,
                "AvatarEnrich_Ensure",
            )

            if not avatar_path:
                logger.info(
                    "AvatarTrace | stage=avatar_enrichment_gmgn_warm_probe | ca=%s | enabled=true",
                    ca[:8],
                )
                avatar_prime = await safe_call(
                    background_fetcher.prime_avatar_sources(ca, token_data, allow_warm_probe=True),
                    4,
                    "AvatarEnrich_Prime",
                )
                if isinstance(avatar_prime, tuple) and len(avatar_prime) >= 2:
                    avatar_url = str(avatar_prime[0] or "")
                    avatar_source = str(avatar_prime[1] or "")
                    if avatar_url:
                        token_data["token_image_url"] = avatar_url
                        token_data["token_image_source"] = avatar_source
                avatar_path = await safe_call(
                    background_fetcher.ensure_token_avatar(
                        ca,
                        token_data.get("token_image_url", ""),
                        token_data.get("token_image_source", ""),
                    ),
                    8,
                    "AvatarEnrich_Download",
                )

            if not avatar_path:
                logger.info("AvatarEnrichment | ca=%s | success=false", ca[:8])
                continue

            token_data = _commit_avatar_patch(
                _build_avatar_refresh_payload(
                    avatar_path,
                    str(token_data.get("token_image_url") or terminal_states.get("token_image_url") or ""),
                    str(token_data.get("token_image_source") or terminal_states.get("token_image_source") or ""),
                )
            )

            entry_price = _safe_float(
                (record or {}).get("entry_price")
                or terminal_states.get("entry_price")
                or terminal_states.get("milestone_anchor_price"),
                0.0,
            )
            initial_msg_id = int((record or {}).get("initial_msg_id") or effective_msg_id or 0)
            status = terminal_states.get("signal_state") or (record or {}).get("status")

            if initial_msg_id > 0:
                await safe_call(
                    db.save_initial_signal(
                        ca,
                        (record or {}).get("source") or "SYSTEM",
                        entry_price,
                        initial_msg_id,
                        terminal_states,
                        status=status,
                    ),
                    3,
                    "AvatarEnrich_DB",
                )

            if effective_chat_id > 0 and initial_msg_id > 0:
                decision = {
                    "verdict": terminal_states.get("decision_action") or ACTION_WATCH,
                    "reason": terminal_states.get("decision_reason")
                    or (record or {}).get("ai_narrative")
                    or terminal_states.get("ai_narrative")
                    or "头像已补全，已刷新面板。",
                }
                await safe_call(
                    update_user_message(
                        chat_id=effective_chat_id,
                        message_id=initial_msg_id,
                        ca=ca,
                        token_data=token_data,
                        decision=decision,
                    ),
                    12,
                    "AvatarEnrich_Refresh",
                )

            logger.info("AvatarEnrichment | ca=%s | success=true", ca[:8])
        except Exception as e:
            logger.error(f"AvatarEnrichment | ca={(ca or '')[:8]} | err={e}", exc_info=True)
        finally:
            if ca:
                async with _avatar_enrichment_lock:
                    _avatar_enrichment_pending.discard(ca)
            if got_item:
                _avatar_enrichment_queue.task_done()


def _load_json_file(path: str) -> Optional[dict]:
    try:
        p = Path(path)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _paper_portfolio_call(method_name: str, *args, **kwargs) -> dict:
    """
    兼容不同版本的 PaperPortfolioEngine。
    即使缺少 on_final_close / on_tp_event，也不要把主循环打崩。
    """
    try:
        fn = getattr(paper_portfolio_engine, method_name, None)
        if callable(fn):
            ret = fn(*args, **kwargs)
            return ret if isinstance(ret, dict) else {"ok": bool(ret), "raw": ret}

        alt_names = {
            "on_final_close": ["close_position", "final_close", "close_trade", "close"],
            "on_tp_event": ["take_profit", "partial_take_profit", "tp_event", "reduce_position"],
        }.get(method_name, [])

        for alt in alt_names:
            alt_fn = getattr(paper_portfolio_engine, alt, None)
            if not callable(alt_fn):
                continue
            try:
                ret = alt_fn(*args, **kwargs)
            except TypeError:
                ret = alt_fn(*args)
            return ret if isinstance(ret, dict) else {"ok": bool(ret), "raw": ret, "fallback_method": alt}

        logger.warning(f"⚠️ PaperPortfolioEngine 缺少方法: {method_name}，本次仅跳过纸面账户记账，不影响主流程。")
        return {"ok": False, "reason": f"missing_method:{method_name}"}
    except Exception as e:
        logger.warning(f"⚠️ PaperPortfolio 调用失败 [{method_name}]: {e}", exc_info=True)
        return {"ok": False, "reason": f"error:{method_name}:{e}"}


# === LightGBM 预测模型全局加载 ===
try:
    import numpy as np
    import lightgbm as lgb
    from modules.feature_engine import calculate_ml_features

    LGB_AVAILABLE = True
    MODEL_PATH = "models/meme_strategy_v1.txt"
    MODEL_METRICS_PATH = "models/meme_strategy_v1_metrics.json"
    MODEL_FEATURES_PATH = "models/meme_strategy_v1_features.json"

    if os.path.exists(MODEL_PATH):
        lgb_model = lgb.Booster(model_file=MODEL_PATH)
        model_metrics = _load_json_file(MODEL_METRICS_PATH) or {}
        model_features = _load_json_file(MODEL_FEATURES_PATH) or {}

        logger.info("🧠 LightGBM 本地模型文件已加载入内存。")
        if model_metrics:
            logger.info(
                "📊 LightGBM 训练指标: "
                f"acc={model_metrics.get('accuracy')} | "
                f"precision={model_metrics.get('precision')} | "
                f"recall={model_metrics.get('recall')} | "
                f"f1={model_metrics.get('f1')} | "
                f"auc={model_metrics.get('roc_auc')}"
            )
        if model_features:
            logger.info(f"🧩 LightGBM 特征顺序: {model_features.get('feature_columns', [])}")
    else:
        lgb_model = None
        logger.info("⏳ 未检测到 LightGBM 模型文件，当前不启用机器学习预测。")
except ImportError as e:
    LGB_AVAILABLE = False
    lgb_model = None
    logger.warning(f"⚠️ 缺少机器学习依赖 ({e})，AI 预测辅助将处于离线状态。")
# ==================================

main_router = Router()
_in_flight_signals = {}
_in_flight_lock = asyncio.Lock()


def _is_missing(v: Any) -> bool:
    return v is None or v == ""


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "")
        if s.endswith("%"):
            s = s[:-1].strip()
        if not s:
            return default
        return float(s)
    except Exception:
        return default


def _safe_pct_text(v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return ""
        if s.endswith("%"):
            return s
        try:
            return f"{float(s):.2f}%"
        except Exception:
            return s
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return ""


TRUSTED_TOP10_SOURCES = {"BITQUERY", "SOLANA_RPC", "HELIUS"}
SIGNAL_STATE_NEW = "NEW_SIGNAL"
SIGNAL_STATE_OBSERVING = "OBSERVING"
SIGNAL_STATE_ARMED = "ARMED"
SIGNAL_STATE_ENTERED = "ENTERED"
ALLOWED_SIGNAL_STATES = {
    SIGNAL_STATE_NEW,
    SIGNAL_STATE_OBSERVING,
    SIGNAL_STATE_ARMED,
    SIGNAL_STATE_ENTERED,
}
ACTION_PASS = "PASS"
ACTION_WATCH = "WATCH"
ACTION_PROBE = "PROBE"
ACTION_ENTER = "ENTER"
ACTION_EXIT = "EXIT"
VERDICT_ALIASES = {
    "BUY": ACTION_ENTER,
    "SELL": ACTION_EXIT,
    "HOLD": ACTION_WATCH,
}


def _is_trusted_top10_source(src: Any) -> bool:
    return str(src or "").upper() in TRUSTED_TOP10_SOURCES


def _normalize_signal_state(state: Any, default: str = SIGNAL_STATE_NEW) -> str:
    text = str(state or default).upper().strip()
    return text if text in ALLOWED_SIGNAL_STATES else default


def _normalize_verdict(verdict: Any, default: str = ACTION_WATCH) -> str:
    text = str(verdict or default).upper().strip()
    text = VERDICT_ALIASES.get(text, text)
    return text if text in {ACTION_PASS, ACTION_WATCH, ACTION_PROBE, ACTION_ENTER, ACTION_EXIT} else default


def _tracker_signal_state(ca: str) -> str:
    pos = tp_tracker.data.get(ca, {}) if getattr(tp_tracker, "data", None) else {}
    status = str(pos.get("status", "")).upper()
    signal_state = _normalize_signal_state(pos.get("signal_state"), SIGNAL_STATE_NEW)
    if status == "ACTIVE":
        return SIGNAL_STATE_ENTERED
    if status == "ARMED":
        return SIGNAL_STATE_ARMED
    if status == "OBSERVE":
        return SIGNAL_STATE_OBSERVING
    return signal_state


def _runtime_signal_state(ca: str, terminal_states: Optional[dict] = None, record: Optional[dict] = None) -> str:
    tracker_state = _tracker_signal_state(ca)
    if tracker_state != SIGNAL_STATE_NEW:
        return tracker_state

    terminal = terminal_states if isinstance(terminal_states, dict) else {}
    if _normalize_signal_state(terminal.get("signal_state"), ""):
        return _normalize_signal_state(terminal.get("signal_state"), SIGNAL_STATE_NEW)

    if isinstance(record, dict) and _normalize_signal_state(record.get("status"), ""):
        return _normalize_signal_state(record.get("status"), SIGNAL_STATE_NEW)

    return SIGNAL_STATE_NEW


def _apply_runtime_metadata(token_data: dict, *, signal_state: Optional[str] = None, decision_action: Optional[str] = None) -> dict:
    token_data = token_data or {}
    canonical_stage = get_canonical_stage(token_data)
    liq_ctx = get_decision_liquidity_context(token_data)
    meta = token_data.get("canonical_metadata") if isinstance(token_data.get("canonical_metadata"), dict) else {}
    if canonical_stage:
        token_data["canonical_stage"] = canonical_stage
    if meta:
        token_data["canonical_metadata"] = meta
    if signal_state:
        token_data["signal_state"] = _normalize_signal_state(signal_state, SIGNAL_STATE_NEW)
    if decision_action:
        token_data["decision_action"] = _normalize_verdict(decision_action, ACTION_WATCH)
    token_data["decision_liquidity_strict"] = liq_ctx["strict_mode"]
    token_data["decision_liquidity_enter_ready"] = liq_ctx["formal_enter_ready"]
    token_data["decision_liquidity_source"] = liq_ctx["display_source"]
    return token_data


def _log_canonical_state(ca: str, token_data: dict, action: str, signal_state: str):
    liq_ctx = get_decision_liquidity_context(token_data)
    logger.info(
        "CanonicalState | ca=%s | state=%s | action=%s | stage=%s | entity_adjusted=%s | strict_liq=%s | enter_ready=%s | liq_source=%s",
        ca[:8],
        signal_state,
        action,
        token_data.get("canonical_stage") or "",
        token_data.get("top10_entity_adjusted"),
        liq_ctx["strict_mode"],
        liq_ctx["formal_enter_ready"],
        liq_ctx["display_source"] or "",
    )


def _log_liquidity_trace(stage: str, ca: str, token_data: dict):
    td = token_data or {}
    liq_ctx = get_decision_liquidity_context(td)
    logger.info(
        "LiquidityTrace | stage=%s | ca=%s | cap_usd=%s | liquidity_usd=%s | pair_liquidity_usd=%s | "
        "exit_liquidity_usd=%s | decision_liq=%s | formal_enter_liq=%s | display_source=%s | "
        "formal_enter_ready=%s | market_data_ready=%s | liquidity_data_ready=%s | liquidity_source_error=%s",
        stage,
        ca[:8],
        _safe_float(td.get("cap_usd"), 0.0),
        _safe_float(td.get("liquidity_usd"), 0.0),
        _safe_float(td.get("pair_liquidity_usd"), 0.0),
        _safe_float(td.get("exit_liquidity_usd"), 0.0),
        _safe_float(get_decision_liquidity_usd(td), 0.0),
        _safe_float(liq_ctx.get("formal_enter_liquidity_usd"), 0.0),
        str(liq_ctx.get("display_source") or ""),
        bool(liq_ctx.get("formal_enter_ready")),
        bool(liq_ctx.get("market_data_ready")),
        bool(liq_ctx.get("liquidity_data_ready")),
        str(liq_ctx.get("liquidity_source_error") or ""),
    )


def _log_strict_trace(stage: str, ca: str, token_data: dict):
    td = token_data or {}
    liq_ctx = get_decision_liquidity_context(td)
    logger.info(
        "StrictTrace | stage=%s | ca=%s | pair=%s | exit=%s | formal_enter_liq=%s | display_source=%s",
        stage,
        ca[:8],
        _safe_float(td.get("pair_liquidity_usd"), 0.0),
        _safe_float(td.get("exit_liquidity_usd"), 0.0),
        _safe_float(liq_ctx.get("formal_enter_liquidity_usd"), 0.0),
        str(liq_ctx.get("display_source") or ""),
    )


def _suspicious_low_pair_threshold_usd() -> float:
    return _safe_float(os.getenv("SUSPICIOUS_LOW_PAIR_FALLBACK_USD"), 20.0)


def _append_liquidity_error(token_data: dict, marker: str):
    if not marker:
        return
    current = str((token_data or {}).get("liquidity_source_error") or "")
    parts = [part.strip() for part in current.split(",") if part.strip()]
    if marker not in parts:
        parts.append(marker)
    token_data["liquidity_source_error"] = ",".join(parts)


def _remove_liquidity_error(token_data: dict, marker: str):
    current = str((token_data or {}).get("liquidity_source_error") or "")
    parts = [part.strip() for part in current.split(",") if part.strip() and part.strip() != marker]
    token_data["liquidity_source_error"] = ",".join(parts)


def _log_liquidity_decision_trace(stage: str, ca: str, token_data: dict, source: str, accepted: bool, suspicious: bool, overridden_by_gmgn: bool):
    logger.info(
        "LiquidityDecisionTrace | stage=%s | ca=%s | source=%s | accepted=%s | suspicious=%s | overridden_by_gmgn=%s",
        stage,
        ca[:8],
        source,
        accepted,
        suspicious,
        overridden_by_gmgn,
    )


def _apply_liquidity_display_guard(token_data: dict, stage: str = "") -> dict:
    td = token_data or {}
    ca = str(td.get("ca") or "")
    threshold = _suspicious_low_pair_threshold_usd()
    pair_liq = _safe_float(td.get("pair_liquidity_usd"), 0.0)
    exit_liq = _safe_float(td.get("exit_liquidity_usd"), 0.0)
    gmgn_header_liq = _safe_float(td.get("gmgn_header_liquidity_usd"), 0.0)
    suspicious = exit_liq <= 0 and gmgn_header_liq <= 0 and 0 < pair_liq <= threshold
    overridden_by_gmgn = False
    source = "exit" if exit_liq > 0 else ("gmgn_header" if gmgn_header_liq > 0 else "pair_fallback")

    if suspicious:
        td["suspicious_low_pair_fallback"] = True
        td["suspicious_low_pair_value_usd"] = pair_liq
        if _safe_float(td.get("liquidity_usd"), 0.0) <= threshold:
            td["liquidity_usd"] = None
        td["pair_liquidity_usd"] = None
        _append_liquidity_error(td, "SUSPICIOUS_LOW_PAIR_FALLBACK")
    else:
        overridden_by_gmgn = bool(td.get("suspicious_low_pair_fallback")) and gmgn_header_liq > 0
        td["suspicious_low_pair_fallback"] = False
        if gmgn_header_liq > 0:
            if _safe_float(td.get("pair_liquidity_usd"), 0.0) <= 0:
                td["pair_liquidity_usd"] = gmgn_header_liq
            if _safe_float(td.get("liquidity_usd"), 0.0) <= 0 or overridden_by_gmgn:
                td["liquidity_usd"] = gmgn_header_liq
        _remove_liquidity_error(td, "SUSPICIOUS_LOW_PAIR_FALLBACK")

    accepted = bool(exit_liq > 0 or gmgn_header_liq > 0 or _safe_float(td.get("pair_liquidity_usd"), 0.0) > threshold)
    _log_liquidity_decision_trace(stage or "guard", ca, td, source, accepted, suspicious, overridden_by_gmgn)
    return td


def _log_safety_canonical_trace(stage: str, ca: str, token_data: dict):
    td = token_data or {}
    logger.info(
        "SafetyCanonicalTrace | stage=%s | ca=%s | dex_paid=%s | burned=%s | locked=%s | mint=%s | freeze=%s",
        stage,
        ca[:8],
        td.get("dex_paid"),
        td.get("is_burned"),
        td.get("is_locked"),
        td.get("mint_authority_present"),
        td.get("freeze_authority_present"),
    )


def _sanitize_ai_reason_by_metrics(decision: Optional[dict], token_data: dict) -> dict:
    out = dict(decision or {})
    thresholds = canonical_thresholds()
    liq = _safe_float(get_decision_liquidity_usd(token_data), 0.0)
    mcap = _safe_float(token_data.get("cap_usd") or token_data.get("mcap") or token_data.get("fdv"), 0.0)
    liq_ratio = (liq / mcap) if mcap > 0 and liq > 0 else 0.0
    liq_danger = _safe_float(thresholds.get("liquidity_danger_usd"), 2000.0)
    liq_ratio_warn = _safe_float(thresholds.get("liquidity_ratio_warn"), 0.03)

    if liq < liq_danger:
        return out
    if mcap > 0 and liq_ratio < liq_ratio_warn:
        return out

    replacements = {
        "reason": "继续观察，等待放量确认",
        "ai_entry": "等待放量确认后再评估入场",
        "ai_exit": "继续观察流动性与成交延续",
        "ai_chart_read": "量价仍需进一步确认",
    }
    flagged_patterns = (
        "流动性不足",
        "流动性较低",
        "池子太薄",
        "流动性偏低",
        "池子偏薄",
    )
    changed_fields = []
    for field, replacement in replacements.items():
        text = str(out.get(field) or "")
        if not text or not any(pattern in text for pattern in flagged_patterns):
            continue
        out[field] = replacement
        changed_fields.append(field)

    if changed_fields:
        logger.info(
            "AILiquiditySanitize | ca=%s | liq=%.2f | liq_ratio=%.4f | fields=%s",
            str(token_data.get("ca") or "")[:8],
            liq,
            liq_ratio,
            ",".join(changed_fields),
        )

    return out


def _sanitize_top10_pending_reason(decision: Optional[dict], token_data: dict) -> dict:
    out = dict(decision or {})
    if not bool((token_data or {}).get("top10_pending_gmgn_review")):
        return out

    replacements = {
        "reason": "Top10待校正，当前不直接定性",
        "ai_entry": "等待持仓结构进一步确认后再评估入场",
        "ai_exit": "等待持仓结构进一步确认后再评估离场",
        "ai_chart_read": "筹码结构仍待确认，先观察价格与标签变化",
    }
    flagged_patterns = (
        "Top10控盘",
        "前十总持仓",
        "触发红线",
        "筹码过于集中",
        "筹码高度集中",
    )
    for field, replacement in replacements.items():
        text = str(out.get(field) or "")
        if field == "reason" and not text:
            out[field] = replacement
            continue
        if any(pattern in text for pattern in flagged_patterns):
            out[field] = replacement
    return out


def _merge_gmgn_results(base: Optional[dict], extra: Optional[dict]) -> dict:
    merged = dict(base or {})
    extra = extra or {}
    for key, value in extra.items():
        if key == "raw_data":
            raw = dict(merged.get("raw_data") or {})
            if isinstance(value, dict):
                for raw_key, raw_value in value.items():
                    if raw_value is not None:
                        raw[raw_key] = raw_value
            merged["raw_data"] = raw
            continue
        if value in (None, "", {}, []):
            continue
        merged[key] = value
    return merged


async def _prime_first_card_avatar(ca: str, token_data: dict) -> dict:
    td = token_data or {}
    if td.get("token_image_path"):
        logger.info("AvatarTrace | stage=prime_first_card_skip | ca=%s | reason=already_has_path", ca[:8])
        return td

    try:
        stable_avatar_path = fetcher._existing_avatar_path(ca)
    except Exception:
        stable_avatar_path = ""
    if stable_avatar_path:
        td["token_image_path"] = stable_avatar_path
        if not td.get("token_image_source"):
            td["token_image_source"] = "stable_cache"
        logger.info(
            "AvatarTrace | stage=prime_first_card | ca=%s | source=%s | success=%s",
            ca[:8],
            "stable_cache",
            True,
        )
        return td

    overall_deadline = time.perf_counter() + 0.90

    current_url = fetcher._normalize_image_url(td.get("token_image_url") or "")
    current_source = fetcher._normalize_avatar_source(td.get("token_image_source") or "", current_url) or "api"
    if current_url:
        td["token_image_url"] = current_url
        td["token_image_source"] = current_source
        try:
            timeout_left = max(0.05, overall_deadline - time.perf_counter())
            avatar_path = await asyncio.wait_for(
                fetcher.ensure_token_avatar(ca, current_url, current_source, fast_mode=True),
                timeout=timeout_left,
            )
        except asyncio.TimeoutError:
            avatar_path = None
        except Exception:
            avatar_path = None

        logger.info(
            "AvatarTrace | stage=prime_first_card | ca=%s | source=%s | success=%s",
            ca[:8],
            current_source,
            bool(avatar_path),
        )
        if avatar_path:
            td["token_image_path"] = avatar_path
            return td

    probe_budget = overall_deadline - time.perf_counter()
    if probe_budget <= 0.08:
        logger.info("AvatarTrace | stage=prime_first_card_skip | ca=%s | reason=budget_exhausted", ca[:8])
        return td

    tasks = {
        asyncio.create_task(fetcher._fetch_dex_avatar_url(ca)): "dexscreener",
    }
    pending = set(tasks.keys())
    chosen_url = ""
    chosen_source = ""

    try:
        probe_deadline = time.perf_counter() + min(0.32, max(0.12, probe_budget - 0.12))
        while pending and time.perf_counter() < probe_deadline and not chosen_url:
            remaining = max(0.0, probe_deadline - time.perf_counter())
            done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                break
            for task in done:
                try:
                    url, source = task.result()
                except Exception:
                    continue
                url = fetcher._normalize_image_url(url or "")
                source = fetcher._normalize_avatar_source(source or "", url)
                if url and source == "dexscreener":
                    chosen_url = url
                    chosen_source = source
                    break
    finally:
        for task in pending:
            task.cancel()

    if chosen_url:
        td["token_image_url"] = chosen_url
        td["token_image_source"] = chosen_source
        try:
            timeout_left = max(0.05, overall_deadline - time.perf_counter())
            avatar_path = await asyncio.wait_for(
                fetcher.ensure_token_avatar(ca, chosen_url, chosen_source, fast_mode=True),
                timeout=timeout_left,
            )
        except asyncio.TimeoutError:
            avatar_path = None
        except Exception:
            avatar_path = None

        logger.info(
            "AvatarTrace | stage=prime_first_card | ca=%s | source=%s | success=%s",
            ca[:8],
            chosen_source,
            bool(avatar_path),
        )
        if avatar_path:
            td["token_image_path"] = avatar_path
            return td

    logger.info("AvatarTrace | stage=prime_first_card_skip | ca=%s | reason=no_fast_avatar", ca[:8])
    return td


def _needs_market_retry(token_data: dict) -> tuple[bool, str]:
    td = token_data or {}
    cap_usd = _safe_float(td.get("cap_usd"), 0.0)
    decision_liq = _safe_float(get_decision_liquidity_usd(td), 0.0)
    liq_ctx = get_decision_liquidity_context(td)
    display_source = str(liq_ctx.get("display_source") or "").strip()
    market_data_ready = bool(liq_ctx.get("market_data_ready"))
    liquidity_data_ready = bool(liq_ctx.get("liquidity_data_ready"))

    retry_reason = ""
    if cap_usd <= 0:
        retry_reason = "cap_missing"
    elif not market_data_ready and (cap_usd <= 0 or decision_liq <= 0):
        retry_reason = "market_not_ready"
    elif decision_liq <= 0 and not liquidity_data_ready:
        retry_reason = "liq_not_ready"
    elif not display_source:
        retry_reason = "liq_source_empty"
    elif decision_liq <= 0:
        retry_reason = "liq_missing"

    if retry_reason:
        logger.info("MarketRetry | ca=%s | reason=%s", str(td.get("ca") or "")[:8], retry_reason)
        return True, retry_reason
    return False, ""


def _apply_retry_market_patch(token_data: dict, retry_market: dict) -> dict:
    td = token_data or {}
    retry_market = retry_market or {}
    if not isinstance(retry_market, dict):
        return td

    def _pick_first(*values):
        for value in values:
            if value is not None and value != "":
                return value
        return None

    price_usd = _pick_first(retry_market.get("priceUsd"), retry_market.get("price_usd"))
    if _safe_float(price_usd, 0.0) > 0:
        td["price_usd"] = _safe_float(price_usd, 0.0)

    cap_usd = _pick_first(
        retry_market.get("fdv"),
        retry_market.get("cap_usd"),
        retry_market.get("mcap"),
        retry_market.get("marketCap"),
    )
    if _safe_float(cap_usd, 0.0) > 0:
        td["cap_usd"] = _safe_float(cap_usd, 0.0)

    pair_liq_raw = retry_market.get("pair_liquidity_usd")
    if pair_liq_raw in (None, "") and isinstance(retry_market.get("liquidity"), dict):
        pair_liq_raw = retry_market.get("liquidity", {}).get("usd")
    pair_liq = _safe_float(pair_liq_raw, 0.0)
    if pair_liq > 0:
        td["pair_liquidity_usd"] = pair_liq

    exit_liq_raw = _pick_first(
        retry_market.get("exit_liquidity_usd"),
        retry_market.get("birdeye_liquidity_usd"),
    )
    exit_liq = _safe_float(exit_liq_raw, 0.0)
    if exit_liq > 0:
        td["exit_liquidity_usd"] = exit_liq

    liquidity_usd = _pick_first(
        retry_market.get("liquidity_usd"),
        exit_liq if exit_liq > 0 else None,
        pair_liq if pair_liq > 0 else None,
    )
    if _safe_float(liquidity_usd, 0.0) > 0:
        td["liquidity_usd"] = _safe_float(liquidity_usd, 0.0)

    token_age_min = _pick_first(retry_market.get("token_age_min"), None)
    if _safe_float(token_age_min, 0.0) > 0:
        td["token_age_min"] = int(_safe_float(token_age_min, 0.0))
    else:
        created_at = retry_market.get("pairCreatedAt")
        if _safe_float(created_at, 0.0) > 0:
            td["token_age_min"] = int(max(0, (time.time() - float(created_at) / 1000) / 60))

    token_image_url = _pick_first(
        retry_market.get("token_image_url"),
        retry_market.get("logo"),
        (retry_market.get("info") or {}).get("imageUrl") if isinstance(retry_market.get("info"), dict) else None,
        (retry_market.get("baseToken") or {}).get("logoURI") if isinstance(retry_market.get("baseToken"), dict) else None,
    )
    if token_image_url:
        td["token_image_url"] = token_image_url
        if retry_market.get("token_image_source"):
            td["token_image_source"] = retry_market.get("token_image_source")

    symbol = _pick_first(
        retry_market.get("symbol"),
        (retry_market.get("baseToken") or {}).get("symbol") if isinstance(retry_market.get("baseToken"), dict) else None,
    )
    if symbol and str(symbol).strip().upper() != "UNK":
        td["symbol"] = str(symbol).strip()

    final_pair = _safe_float(td.get("pair_liquidity_usd"), 0.0)
    final_exit = _safe_float(td.get("exit_liquidity_usd"), 0.0)
    final_liq = _safe_float(td.get("liquidity_usd"), 0.0)
    if max(final_pair, final_exit, final_liq) > 0:
        td["market_data_ready"] = True
        td["liquidity_data_ready"] = True
        error_text = str(td.get("liquidity_source_error") or "")
        harmless_errors = {
            "LIQUIDITY_UNAVAILABLE",
            "DEXSCREENER_FETCH_FAILED",
            "DEXSCREENER_NO_PAIRS",
            "BIRDEYE_FETCH_FAILED",
            "MARKET_NOT_READY",
            "LIQ_NOT_READY",
            "LIQ_MISSING",
            "LIQ_SOURCE_EMPTY",
        }
        if error_text:
            kept = [
                item for item in (part.strip() for part in error_text.split(","))
                if item and item.upper() not in harmless_errors
            ]
            td["liquidity_source_error"] = ",".join(kept)

    return _apply_liquidity_display_guard(td, "retry_patch")


def _has_material_late_merge_improvement(before: dict, after: dict) -> bool:
    return bool(_late_gmgn_rerun_reasons(before, after))


def _top10_primary_source(token_data: dict) -> str:
    td = token_data or {}
    meta = td.get("canonical_metadata") if isinstance(td.get("canonical_metadata"), dict) else {}
    return str(meta.get("top10_primary_source") or td.get("top10_ratio_source") or "").upper().strip()


def _top10_conflict_reason(token_data: dict) -> str:
    td = token_data or {}
    conflict = td.get("source_conflict") if isinstance(td.get("source_conflict"), dict) else {}
    top10_conflict = conflict.get("top10") if isinstance(conflict.get("top10"), dict) else {}
    return str(top10_conflict.get("reason") or "").strip()


def _has_gmgn_top10_candidate(token_data: dict) -> bool:
    td = token_data or {}
    conflict = td.get("source_conflict") if isinstance(td.get("source_conflict"), dict) else {}
    top10_conflict = conflict.get("top10") if isinstance(conflict.get("top10"), dict) else {}
    candidates = top10_conflict.get("candidates") if isinstance(top10_conflict.get("candidates"), dict) else {}
    return "GMGN" in candidates or not _is_missing(td.get("top10_ratio_gmgn"))


def _is_top10_pending_gmgn_review(token_data: dict, gmgn_pending: bool) -> bool:
    if not gmgn_pending:
        return False
    td = token_data or {}
    primary_source = _top10_primary_source(td)
    conflict_reason = _top10_conflict_reason(td)
    has_gmgn_candidate = _has_gmgn_top10_candidate(td)
    return primary_source == "BITQUERY" and (conflict_reason == "bitquery_only" or not has_gmgn_candidate)


def _gmgn_tag_non_null_count(data: Optional[dict]) -> int:
    src = data if isinstance(data, dict) else {}
    try:
        direct = src.get("gmgn_tag_non_null_count")
        if direct is not None:
            return max(0, int(float(direct)))
    except Exception:
        pass

    keys = [
        "gmgn_smart",
        "gmgn_kol",
        "gmgn_blue_chip",
        "gmgn_sniper",
        "gmgn_phishing_wallets",
        "gmgn_rat",
        "gmgn_dev",
        "gmgn_bundle",
    ]
    count = sum(1 for key in keys if src.get(key) is not None)
    if count > 0:
        return count

    raw = src.get("raw_data") if isinstance(src.get("raw_data"), dict) else {}
    return sum(1 for key in ["smart", "kol", "blue_chip", "sniper", "phishing_wallets", "rat", "dev", "bundle"] if raw.get(key) is not None)


def _gmgn_needs_followup(analytics: Optional[dict]) -> bool:
    data = analytics if isinstance(analytics, dict) else {}
    if not data:
        return False
    if bool(data.get("gmgn_followup_required")):
        return True
    if bool(data.get("gmgn_fast_needs_followup")):
        return True
    if str(data.get("gmgn_result_strength") or "").strip().lower() in {"weak", "partial"}:
        return True
    return _gmgn_tag_non_null_count(data) < 4


def _gmgn_render_pending(late_gmgn_pending: bool, analytics: dict, token_data: dict) -> bool:
    td = token_data or {}
    analytics = analytics or {}

    if late_gmgn_pending:
        return True
    if not analytics:
        return True

    strength = str(analytics.get("gmgn_result_strength") or "").strip().lower()
    if strength in {"weak", "partial"}:
        return True

    if _gmgn_needs_followup(analytics):
        return True

    if _is_missing(td.get("chg_1m")) and _is_missing(td.get("price_change_1m")):
        return True
    if _is_missing(td.get("top10_ratio_gmgn")):
        return True

    if _gmgn_tag_non_null_count(td) < 4:
        return True

    decision_liq = _safe_float(get_decision_liquidity_usd(td), 0.0)
    header_liq = _safe_float(analytics.get("header_liq_usd") or analytics.get("liquidity_usd"), 0.0)
    header_liq_accepted = bool(analytics.get("gmgn_liquidity_accepted")) and header_liq > 0
    if decision_liq <= 0 and not header_liq_accepted:
        return True

    return False


def _late_gmgn_rerun_reasons(before: dict, after: dict) -> list[str]:
    reasons: list[str] = []
    before_td = before or {}
    after_td = after or {}
    old_top10 = get_confirmed_top10_pct(before_td)
    new_top10 = get_confirmed_top10_pct(after_td)
    old_primary = _top10_primary_source(before_td)
    new_primary = _top10_primary_source(after_td)
    old_tags = _gmgn_tag_non_null_count(before_td)
    new_tags = _gmgn_tag_non_null_count(after_td)
    old_liq = _safe_float(get_decision_liquidity_usd(before_td), 0.0)
    new_liq = _safe_float(get_decision_liquidity_usd(after_td), 0.0)
    old_gmgn_top10 = _safe_pct_text(before_td.get("top10_ratio_gmgn")) or ""
    new_gmgn_top10 = _safe_pct_text(after_td.get("top10_ratio_gmgn")) or ""
    old_1m = before_td.get("chg_1m")
    new_1m = after_td.get("chg_1m")
    old_safety = (
        before_td.get("dex_paid"),
        before_td.get("is_burned"),
        before_td.get("is_locked"),
        before_td.get("mint_authority_present"),
        before_td.get("freeze_authority_present"),
    )
    new_safety = (
        after_td.get("dex_paid"),
        after_td.get("is_burned"),
        after_td.get("is_locked"),
        after_td.get("mint_authority_present"),
        after_td.get("freeze_authority_present"),
    )

    if (not old_gmgn_top10 and new_gmgn_top10) or old_top10 != new_top10 or (old_primary == "BITQUERY" and new_primary == "GMGN"):
        reasons.append("gmgn_top10_arrived")
    if (old_tags < 4 and new_tags >= 4) or new_tags > old_tags:
        reasons.append("tags_arrived")
    if (
        _is_missing(before_td.get("token_image_path"))
        and _is_missing(before_td.get("token_image_url"))
        and (not _is_missing(after_td.get("token_image_path")) or not _is_missing(after_td.get("token_image_url")))
    ):
        reasons.append("avatar_arrived")
    if old_liq <= 0 and new_liq > 0:
        reasons.append("liquidity_arrived")
    if old_1m is None and new_1m is not None:
        reasons.append("gmgn_1m_arrived")
    if old_safety != new_safety:
        reasons.append("safety_changed")
    return reasons


def _ensure_runtime_token_ca(token_data: dict, ca: str) -> dict:
    td = token_data or {}
    if ca and not str(td.get("ca") or "").strip():
        td["ca"] = str(ca).strip()
    return td


def _extract_late_gmgn_top10_value(analytics: Optional[dict]) -> Any:
    data = analytics if isinstance(analytics, dict) else {}
    return data.get("top10_ratio") or data.get("gmgn_observed_top10_ratio")


def _late_gmgn_merge_gate_state(analytics: Optional[dict]) -> dict:
    data = analytics if isinstance(analytics, dict) else {}
    popup_reason = str(data.get("popup_reason") or "").strip()
    blocked_reason = str(data.get("blocked_reason") or data.get("gmgn_page_blocked_reason") or "").strip()
    strength = str(data.get("gmgn_result_strength") or "").strip().lower()

    reasons: list[str] = []
    if popup_reason == "overlay_mask":
        reasons.append("overlay_mask")
    if blocked_reason:
        reasons.append(f"blocked:{blocked_reason}")
    if strength in {"weak", "thin"}:
        reasons.append(f"strength:{strength}")
    if "target_ready" in data and data.get("target_ready") is not True:
        reasons.append("target_not_ready")
    if "layout_ready" in data and data.get("layout_ready") is not True:
        reasons.append("layout_not_ready")

    return {
        "blocked": bool(reasons),
        "reason": ",".join(reasons),
        "popup_reason": popup_reason,
        "blocked_reason": blocked_reason,
        "strength": strength,
    }


def _apply_top10_semantic_research(token_data: dict, bq_data: Optional[dict] = None, late_gmgn_value: Any = None) -> dict:
    td = token_data or {}
    bq = bq_data if isinstance(bq_data, dict) else {}

    def _pct_or_none(value: Any) -> Optional[float]:
        if value in (None, "", "—"):
            return None
        try:
            text = str(value).replace(",", "").replace("%", "").strip()
            if not text:
                return None
            return float(text)
        except Exception:
            return None

    holders_count = td.get("bitquery_holders_count")
    if holders_count in (None, ""):
        holders_count = bq.get("bitquery_holders_count")
    if holders_count in (None, ""):
        holders_data = bq.get("bitquery_holders_data")
        if isinstance(holders_data, list):
            holders_count = len(holders_data)
    try:
        holders_count = int(float(holders_count)) if holders_count not in (None, "") else None
    except Exception:
        holders_count = None

    bitquery_ratio = _pct_or_none(td.get("top10_ratio_bitquery"))
    if bitquery_ratio is None:
        bitquery_ratio = _pct_or_none(bq.get("bitquery_top10_ratio"))

    effective_self = _pct_or_none(td.get("top10_effective_pct_self"))
    late_gmgn_pct = _pct_or_none(late_gmgn_value)
    if late_gmgn_pct is None:
        late_gmgn_pct = _pct_or_none(td.get("top10_ratio_gmgn_observed"))
    if late_gmgn_pct is None:
        late_gmgn_pct = _pct_or_none(td.get("top10_ratio_gmgn"))

    gap_bitquery_effective = round(bitquery_ratio - effective_self, 4) if bitquery_ratio is not None and effective_self is not None else None
    gap_bitquery_late = round(bitquery_ratio - late_gmgn_pct, 4) if bitquery_ratio is not None and late_gmgn_pct is not None else None
    gap_effective_late = round(effective_self - late_gmgn_pct, 4) if effective_self is not None and late_gmgn_pct is not None else None
    late_support_gap = round(abs(effective_self - late_gmgn_pct), 4) if effective_self is not None and late_gmgn_pct is not None else None

    reason_parts: list[str] = []
    if bitquery_ratio is not None and bitquery_ratio >= 80.0:
        reason_parts.append("bitquery_ge_80")
    if holders_count is not None and holders_count <= 2:
        reason_parts.append("holders_count_le_2")
    if gap_bitquery_effective is not None and gap_bitquery_effective >= 20.0:
        reason_parts.append("bitquery_minus_effective_ge_20")
    if gap_effective_late is not None and abs(gap_effective_late) <= 5.0:
        reason_parts.append("effective_close_to_late_gmgn")

    suspect = bool(
        bitquery_ratio is not None
        and bitquery_ratio >= 80.0
        and holders_count is not None
        and holders_count <= 2
        and effective_self is not None
        and gap_bitquery_effective is not None
        and gap_bitquery_effective >= 20.0
    )

    if holders_count is not None:
        td["bitquery_holders_count"] = holders_count
    td["top10_semantic_suspect"] = suspect
    td["top10_semantic_suspect_reason"] = ",".join(reason_parts) if suspect else ""
    td["top10_bitquery_gap_vs_effective_self"] = gap_bitquery_effective
    td["top10_bitquery_gap_vs_late_gmgn"] = gap_bitquery_late
    td["top10_effective_gap_vs_late_gmgn"] = gap_effective_late
    td["top10_late_merge_support_gap"] = late_support_gap
    td["top10_late_merge_supported_by_selfcalc"] = bool(
        suspect
        and effective_self is not None
        and late_gmgn_pct is not None
        and late_support_gap is not None
        and late_support_gap <= 3.0
    )

    logger.info(
        "Top10SemanticSuspectTrace | ca=%s | bitquery_ratio=%s | effective_self=%s | late_gmgn_new=%s | holders_count=%s | suspect=%s | support=%s | support_gap=%s | reason=%s",
        str(td.get("ca") or "")[:8],
        bitquery_ratio,
        effective_self,
        late_gmgn_pct,
        holders_count,
        suspect,
        td.get("top10_late_merge_supported_by_selfcalc"),
        late_support_gap,
        td.get("top10_semantic_suspect_reason") or "",
    )
    return td


def _append_late_gmgn_top10_history(
    token_data: dict,
    *,
    old_top10: Any,
    new_top10: Any,
    old_action: str,
    new_action: str,
    reasons: Optional[list[str]] = None,
    limit: int = 6,
) -> dict:
    td = token_data or {}

    def _pct_or_none(value: Any) -> Optional[float]:
        if value in (None, "", "—"):
            return None
        try:
            text = str(value).replace(",", "").replace("%", "").strip()
            if not text:
                return None
            return float(text)
        except Exception:
            return None

    history_raw = td.get("late_gmgn_top10_history")
    history = list(history_raw) if isinstance(history_raw, list) else []
    entry = {
        "new_top10": _pct_or_none(new_top10),
        "old_top10": _pct_or_none(old_top10),
        "old_action": str(old_action or ""),
        "new_action": str(new_action or ""),
        "reasons": list(reasons or []),
        "source": "late_gmgn",
    }
    history.append(entry)
    history = history[-max(1, int(limit)):]

    values = []
    for item in history:
        value = _pct_or_none((item or {}).get("new_top10"))
        if value is not None:
            values.append(value)

    td["late_gmgn_top10_history"] = history
    td["late_gmgn_top10_history_count"] = len(history)
    td["late_gmgn_top10_last_value"] = values[-1] if values else None
    td["late_gmgn_top10_min_value"] = min(values) if values else None
    td["late_gmgn_top10_max_value"] = max(values) if values else None

    logger.info(
        "LateGMGNHistoryTrace | ca=%s | history_count=%s | last_value=%s | min_value=%s | max_value=%s",
        str(td.get("ca") or "")[:8],
        td.get("late_gmgn_top10_history_count"),
        td.get("late_gmgn_top10_last_value"),
        td.get("late_gmgn_top10_min_value"),
        td.get("late_gmgn_top10_max_value"),
    )
    return td


def _top10_research_terminal_patch(token_data: dict) -> dict:
    td = token_data or {}
    patch: dict = {}
    for key in [
        "bitquery_holders_count",
        "top10_semantic_suspect",
        "top10_semantic_suspect_reason",
        "top10_bitquery_gap_vs_effective_self",
        "top10_bitquery_gap_vs_late_gmgn",
        "top10_effective_gap_vs_late_gmgn",
        "top10_late_merge_supported_by_selfcalc",
        "top10_late_merge_support_gap",
        "late_gmgn_merge_blocked",
        "late_gmgn_merge_block_reason",
        "late_gmgn_top10_history_count",
        "late_gmgn_top10_last_value",
        "late_gmgn_top10_min_value",
        "late_gmgn_top10_max_value",
    ]:
        if td.get(key) is not None:
            patch[key] = td.get(key)
    if isinstance(td.get("late_gmgn_top10_history"), list):
        patch["late_gmgn_top10_history"] = td.get("late_gmgn_top10_history")
    return patch


def _merge_existing_terminal(token_data: dict, terminal: Optional[dict]) -> dict:
    terminal = terminal or {}
    stable = terminal.get("stable_snapshot") or {}

    def _is_placeholder_text(v: Any) -> bool:
        if v is None:
            return True
        text = str(v).strip()
        if not text:
            return True
        upper = text.upper()
        if upper in {"?", "❓", "UNK"}:
            return True
        if "待校正" in text:
            return True
        return False

    def _is_placeholder_metric(v: Any) -> bool:
        if _is_placeholder_text(v):
            return True
        return _safe_float(v, 0.0) <= 0

    for src in (stable, terminal):
        if not src:
            continue

        if _is_placeholder_text(token_data.get("name")) and not _is_placeholder_text(src.get("name")):
            token_data["name"] = src.get("name")

        if token_data.get("symbol") == "UNK" and src.get("symbol"):
            token_data["symbol"] = src.get("symbol")

        base_price = src.get("price_usd") or src.get("entry_price")
        if _safe_float(token_data.get("price_usd"), 0.0) <= 0 and _safe_float(base_price, 0.0) > 0:
            token_data["price_usd"] = _safe_float(base_price)

        for k in ["cap_usd", "liquidity_usd", "pair_liquidity_usd", "exit_liquidity_usd", "token_age_min", "gmgn_header_liquidity_usd", "suspicious_low_pair_value_usd"]:
            if _safe_float(token_data.get(k), 0.0) <= 0 and _safe_float(src.get(k), 0.0) > 0:
                token_data[k] = src.get(k)

        for k in ["volume_h24", "buy_sell_ratio"]:
            if _is_placeholder_metric(token_data.get(k)) and _safe_float(src.get(k), 0.0) > 0:
                token_data[k] = src.get(k)

        for k in ["token_image_url", "token_image_path", "chart_screenshot"]:
            if _is_missing(token_data.get(k)) and not _is_missing(src.get(k)):
                token_data[k] = src.get(k)
        if _is_missing(token_data.get("token_image_source")) and not _is_missing(src.get("token_image_source")):
            token_data["token_image_source"] = src.get("token_image_source")

        if _is_placeholder_text(token_data.get("top10_ratio")) and not _is_placeholder_text(src.get("top10_ratio")):
            token_data["top10_ratio"] = src.get("top10_ratio")
        if _is_placeholder_text(token_data.get("top10_ratio_source")) and not _is_placeholder_text(src.get("top10_ratio_source")):
            token_data["top10_ratio_source"] = src.get("top10_ratio_source")

        for k in [
            "top10_raw_pct",
            "top10_adjusted_pct",
            "top10_ratio_bitquery",
            "top10_ratio_gmgn",
            "top10_ratio_gmgn_observed",
            "top10_raw_pct_self",
            "top10_owner_pct_self",
            "top10_effective_pct_self",
            "top10_effective_value_usd_self",
            "top1_effective_pct_self",
            "top1_effective_value_usd_self",
            "top10_holder_count_raw_self",
            "top10_holder_count_owner_self",
            "top10_holder_count_effective_self",
            "canonical_stage",
            "top10_adjustment_semantics",
            "top10_entity_adjusted",
            "top10_pending_gmgn_review",
            "bitquery_holders_count",
            "top10_semantic_suspect",
            "top10_semantic_suspect_reason",
            "top10_bitquery_gap_vs_effective_self",
            "top10_bitquery_gap_vs_late_gmgn",
            "top10_effective_gap_vs_late_gmgn",
            "top10_late_merge_supported_by_selfcalc",
            "top10_late_merge_support_gap",
            "late_gmgn_merge_blocked",
            "late_gmgn_merge_block_reason",
            "late_gmgn_top10_history_count",
            "late_gmgn_top10_last_value",
            "late_gmgn_top10_min_value",
            "late_gmgn_top10_max_value",
            "decision_liquidity_source",
            "decision_action",
            "decision_reason",
            "signal_state",
        ]:
            if _is_missing(token_data.get(k)) and not _is_missing(src.get(k)):
                token_data[k] = src.get(k)

        if _is_missing(token_data.get("top10_ratio_helius")) and not _is_missing(src.get("top10_ratio_helius")):
            token_data["top10_ratio_helius"] = src.get("top10_ratio_helius")
        if _is_missing(token_data.get("ai_image_read")) and not _is_missing(src.get("ai_image_read")):
            token_data["ai_image_read"] = src.get("ai_image_read")

        if not isinstance(token_data.get("metric_confidence"), dict) and isinstance(src.get("metric_confidence"), dict):
            token_data["metric_confidence"] = src.get("metric_confidence")
        if not isinstance(token_data.get("source_conflict"), dict) and isinstance(src.get("source_conflict"), dict):
            token_data["source_conflict"] = src.get("source_conflict")
        if not isinstance(token_data.get("canonical_metadata"), dict) and isinstance(src.get("canonical_metadata"), dict):
            token_data["canonical_metadata"] = src.get("canonical_metadata")
        if not isinstance(token_data.get("top10_calc_method_self"), dict) and isinstance(src.get("top10_calc_method_self"), dict):
            token_data["top10_calc_method_self"] = src.get("top10_calc_method_self")
        if not isinstance(token_data.get("top10_exclusion_summary_self"), dict) and isinstance(src.get("top10_exclusion_summary_self"), dict):
            token_data["top10_exclusion_summary_self"] = src.get("top10_exclusion_summary_self")
        if not isinstance(token_data.get("late_gmgn_top10_history"), list) and isinstance(src.get("late_gmgn_top10_history"), list):
            token_data["late_gmgn_top10_history"] = src.get("late_gmgn_top10_history")

        for k in ["chg_1m", "chg_5m", "chg_15m", "chg_30m", "chg_1h", "chg_3h", "chg_6h", "chg_24h"]:
            if token_data.get(k) is None and src.get(k) is not None:
                token_data[k] = src.get(k)

        for k in [
            "gmgn_smart",
            "gmgn_kol",
            "gmgn_blue_chip",
            "gmgn_sniper",
            "gmgn_phishing_wallets",
            "gmgn_rat",
            "gmgn_dev",
            "gmgn_bundle",
        ]:
            if token_data.get(k) is None and src.get(k) is not None:
                token_data[k] = src.get(k)

        for k in ["gmgn_tags_present", "gmgn_result_strength", "gmgn_liquidity_accepted", "suspicious_low_pair_fallback"]:
            if token_data.get(k) is None and src.get(k) is not None:
                token_data[k] = src.get(k)
        for k in ["gmgn_popup_reason", "gmgn_blocked_reason", "gmgn_target_ready", "gmgn_layout_ready"]:
            if token_data.get(k) is None and src.get(k) is not None:
                token_data[k] = src.get(k)
        if token_data.get("gmgn_tag_non_null_count") is None and src.get("gmgn_tag_non_null_count") is not None:
            token_data["gmgn_tag_non_null_count"] = src.get("gmgn_tag_non_null_count")

        if _is_missing(token_data.get("gmgn_liquidity_reason")) and not _is_missing(src.get("gmgn_liquidity_reason")):
            token_data["gmgn_liquidity_reason"] = src.get("gmgn_liquidity_reason")

        for k in ["is_burned", "is_locked", "dex_paid", "mint_authority_present", "freeze_authority_present"]:
            if token_data.get(k) is None and src.get(k) is not None:
                token_data[k] = src.get(k)

    return token_data



def _apply_helius_security(token_data: dict, helius_sec: Optional[dict]) -> dict:
    if not helius_sec:
        return token_data

    hs = dict(helius_sec)
    helius_top10 = hs.pop("top10_ratio", None)
    token_data.update(hs)

    if not _is_missing(helius_top10):
        token_data["top10_ratio_helius"] = _safe_pct_text(helius_top10)

    return token_data



def _resolve_canonical_metrics(token_data: dict, analytics: Optional[dict], bq_data: Optional[dict]) -> dict:
    return apply_canonical_metrics(token_data, analytics or {}, bq_data or {})


def _resolve_top10_ratio(token_data: dict, analytics: Optional[dict], bq_data: Optional[dict]) -> dict:
    return _resolve_canonical_metrics(token_data, analytics, bq_data)



def _build_stable_snapshot(token_data: dict, analytics: Optional[dict] = None) -> dict:
    analytics = analytics or {}
    keys = [
        "symbol", "name", "price_usd", "cap_usd", "liquidity_usd", "pair_liquidity_usd", "exit_liquidity_usd", "volume_h24", "buy_sell_ratio",
        "chg_1m", "chg_5m", "chg_15m", "chg_30m", "chg_1h", "chg_3h", "chg_6h", "chg_24h",
        "token_image_url", "token_image_path", "token_image_source", "is_burned", "is_locked", "token_age_min",
        "gmgn_tags_present", "gmgn_result_strength", "gmgn_tag_non_null_count",
        "gmgn_header_liquidity_usd",
        "gmgn_liquidity_accepted", "gmgn_liquidity_reason",
        "suspicious_low_pair_fallback", "suspicious_low_pair_value_usd",
        "gmgn_smart", "gmgn_kol", "gmgn_blue_chip", "gmgn_sniper", "gmgn_phishing_wallets",
        "gmgn_rat", "gmgn_dev", "gmgn_bundle", "mint_authority_present", "freeze_authority_present",
        "dex_paid",
    ]
    snap = {k: token_data.get(k) for k in keys if token_data.get(k) is not None}

    trusted_src = str(token_data.get("top10_ratio_source") or "").upper()
    canonical_meta = token_data.get("canonical_metadata") if isinstance(token_data.get("canonical_metadata"), dict) else {}
    source_conflict = token_data.get("source_conflict") if isinstance(token_data.get("source_conflict"), dict) else {}
    top10_conflict = source_conflict.get("top10") if isinstance(source_conflict.get("top10"), dict) else {}
    canonical_gmgn_ok = bool(
        trusted_src == "GMGN"
        and str(canonical_meta.get("top10_primary_source") or "").upper() == "GMGN"
        and not str(canonical_meta.get("gmgn_top10_blocked_reason") or "").strip()
        and str(top10_conflict.get("reason") or "") in {"gmgn_preferred_over_bitquery", "gmgn_only"}
    )
    if (_is_trusted_top10_source(trusted_src) or canonical_gmgn_ok) and not _is_missing(token_data.get("top10_ratio")):
        snap["top10_ratio"] = token_data.get("top10_ratio")
        snap["top10_ratio_source"] = trusted_src
    if token_data.get("top10_raw_pct") is not None:
        snap["top10_raw_pct"] = token_data.get("top10_raw_pct")
    if token_data.get("top10_adjusted_pct") is not None:
        snap["top10_adjusted_pct"] = token_data.get("top10_adjusted_pct")
    if token_data.get("top10_raw_pct_self") is not None:
        snap["top10_raw_pct_self"] = token_data.get("top10_raw_pct_self")
    if token_data.get("top10_owner_pct_self") is not None:
        snap["top10_owner_pct_self"] = token_data.get("top10_owner_pct_self")
    if token_data.get("top10_effective_pct_self") is not None:
        snap["top10_effective_pct_self"] = token_data.get("top10_effective_pct_self")
    if token_data.get("top10_effective_value_usd_self") is not None:
        snap["top10_effective_value_usd_self"] = token_data.get("top10_effective_value_usd_self")
    if token_data.get("top1_effective_pct_self") is not None:
        snap["top1_effective_pct_self"] = token_data.get("top1_effective_pct_self")
    if token_data.get("top1_effective_value_usd_self") is not None:
        snap["top1_effective_value_usd_self"] = token_data.get("top1_effective_value_usd_self")
    if token_data.get("top10_holder_count_raw_self") is not None:
        snap["top10_holder_count_raw_self"] = token_data.get("top10_holder_count_raw_self")
    if token_data.get("top10_holder_count_owner_self") is not None:
        snap["top10_holder_count_owner_self"] = token_data.get("top10_holder_count_owner_self")
    if token_data.get("top10_holder_count_effective_self") is not None:
        snap["top10_holder_count_effective_self"] = token_data.get("top10_holder_count_effective_self")
    if isinstance(token_data.get("top10_calc_method_self"), dict):
        snap["top10_calc_method_self"] = token_data.get("top10_calc_method_self")
    if isinstance(token_data.get("top10_exclusion_summary_self"), dict):
        snap["top10_exclusion_summary_self"] = token_data.get("top10_exclusion_summary_self")
    if token_data.get("bitquery_holders_count") is not None:
        snap["bitquery_holders_count"] = token_data.get("bitquery_holders_count")
    if token_data.get("top10_semantic_suspect") is not None:
        snap["top10_semantic_suspect"] = token_data.get("top10_semantic_suspect")
    if token_data.get("top10_semantic_suspect_reason") is not None:
        snap["top10_semantic_suspect_reason"] = token_data.get("top10_semantic_suspect_reason")
    if token_data.get("top10_bitquery_gap_vs_effective_self") is not None:
        snap["top10_bitquery_gap_vs_effective_self"] = token_data.get("top10_bitquery_gap_vs_effective_self")
    if token_data.get("top10_bitquery_gap_vs_late_gmgn") is not None:
        snap["top10_bitquery_gap_vs_late_gmgn"] = token_data.get("top10_bitquery_gap_vs_late_gmgn")
    if token_data.get("top10_effective_gap_vs_late_gmgn") is not None:
        snap["top10_effective_gap_vs_late_gmgn"] = token_data.get("top10_effective_gap_vs_late_gmgn")
    if token_data.get("top10_late_merge_supported_by_selfcalc") is not None:
        snap["top10_late_merge_supported_by_selfcalc"] = token_data.get("top10_late_merge_supported_by_selfcalc")
    if token_data.get("top10_late_merge_support_gap") is not None:
        snap["top10_late_merge_support_gap"] = token_data.get("top10_late_merge_support_gap")
    if not _is_missing(token_data.get("top10_ratio_gmgn_observed")):
        snap["top10_ratio_gmgn_observed"] = token_data.get("top10_ratio_gmgn_observed")
    if token_data.get("late_gmgn_merge_blocked") is not None:
        snap["late_gmgn_merge_blocked"] = token_data.get("late_gmgn_merge_blocked")
    if token_data.get("late_gmgn_merge_block_reason") is not None:
        snap["late_gmgn_merge_block_reason"] = token_data.get("late_gmgn_merge_block_reason")
    if token_data.get("gmgn_popup_reason") is not None:
        snap["gmgn_popup_reason"] = token_data.get("gmgn_popup_reason")
    if token_data.get("gmgn_blocked_reason") is not None:
        snap["gmgn_blocked_reason"] = token_data.get("gmgn_blocked_reason")
    if token_data.get("gmgn_target_ready") is not None:
        snap["gmgn_target_ready"] = token_data.get("gmgn_target_ready")
    if token_data.get("gmgn_layout_ready") is not None:
        snap["gmgn_layout_ready"] = token_data.get("gmgn_layout_ready")
    if isinstance(token_data.get("late_gmgn_top10_history"), list):
        snap["late_gmgn_top10_history"] = token_data.get("late_gmgn_top10_history")
    if token_data.get("late_gmgn_top10_history_count") is not None:
        snap["late_gmgn_top10_history_count"] = token_data.get("late_gmgn_top10_history_count")
    if token_data.get("late_gmgn_top10_last_value") is not None:
        snap["late_gmgn_top10_last_value"] = token_data.get("late_gmgn_top10_last_value")
    if token_data.get("late_gmgn_top10_min_value") is not None:
        snap["late_gmgn_top10_min_value"] = token_data.get("late_gmgn_top10_min_value")
    if token_data.get("late_gmgn_top10_max_value") is not None:
        snap["late_gmgn_top10_max_value"] = token_data.get("late_gmgn_top10_max_value")
    if isinstance(token_data.get("metric_confidence"), dict):
        snap["metric_confidence"] = token_data.get("metric_confidence")
    if isinstance(token_data.get("source_conflict"), dict):
        snap["source_conflict"] = token_data.get("source_conflict")
    if isinstance(token_data.get("canonical_metadata"), dict):
        snap["canonical_metadata"] = token_data.get("canonical_metadata")
    if token_data.get("canonical_stage") is not None:
        snap["canonical_stage"] = token_data.get("canonical_stage")
    if token_data.get("top10_adjustment_semantics") is not None:
        snap["top10_adjustment_semantics"] = token_data.get("top10_adjustment_semantics")
    if token_data.get("top10_entity_adjusted") is not None:
        snap["top10_entity_adjusted"] = token_data.get("top10_entity_adjusted")
    if token_data.get("top10_pending_gmgn_review") is not None:
        snap["top10_pending_gmgn_review"] = token_data.get("top10_pending_gmgn_review")
    if token_data.get("decision_liquidity_source") is not None:
        snap["decision_liquidity_source"] = token_data.get("decision_liquidity_source")
    if token_data.get("decision_liquidity_enter_ready") is not None:
        snap["decision_liquidity_enter_ready"] = token_data.get("decision_liquidity_enter_ready")
    if token_data.get("signal_state") is not None:
        snap["signal_state"] = token_data.get("signal_state")
    if token_data.get("decision_action") is not None:
        snap["decision_action"] = token_data.get("decision_action")
    if token_data.get("decision_reason") is not None:
        snap["decision_reason"] = token_data.get("decision_reason")

    if not _is_missing(token_data.get("top10_ratio_bitquery")):
        snap["top10_ratio_bitquery"] = token_data.get("top10_ratio_bitquery")
    if not _is_missing(token_data.get("top10_ratio_gmgn")):
        snap["top10_ratio_gmgn"] = token_data.get("top10_ratio_gmgn")
    if not _is_missing(token_data.get("top10_ratio_helius")):
        snap["top10_ratio_helius"] = token_data.get("top10_ratio_helius")

    screenshot = analytics.get("screenshot") or token_data.get("chart_screenshot")
    if screenshot:
        snap["chart_screenshot"] = screenshot

    return snap



def _build_analytics_for_ai(analytics: Optional[dict], terminal_states: Optional[dict]) -> dict:
    out = dict(analytics or {})
    terminal_states = terminal_states or {}
    stable = terminal_states.get("stable_snapshot") or {}
    screenshot = out.get("screenshot") or stable.get("chart_screenshot") or terminal_states.get("chart_screenshot")
    if screenshot and os.path.exists(screenshot):
        out["screenshot"] = screenshot
    return out


def _apply_gmgn_analytics(token_data: dict, analytics: Optional[dict], *, patch_timeframes_only_when_missing: bool = True) -> dict:
    if not analytics:
        return token_data

    def _prefer_positive_flag(current: Optional[bool], incoming: Optional[bool]) -> Optional[bool]:
        if incoming is None:
            return current
        if current is None:
            return incoming
        if current is True:
            return True
        if current is False and incoming is True:
            return True
        return current

    if token_data.get("symbol") == "UNK" and analytics.get("symbol"):
        token_data["symbol"] = analytics.get("symbol")

    logo = analytics.get("logo") or analytics.get("token_image_url")
    if logo and not token_data.get("token_image_url"):
        token_data["token_image_url"] = logo
        if analytics.get("token_image_source"):
            token_data["token_image_source"] = analytics.get("token_image_source")
    elif analytics.get("token_image_source") and not token_data.get("token_image_source"):
        token_data["token_image_source"] = analytics.get("token_image_source")

    if analytics.get("token_image_path") and not token_data.get("token_image_path"):
        token_data["token_image_path"] = analytics.get("token_image_path")

    if analytics.get("price") and _safe_float(token_data.get("price_usd"), 0.0) <= 0:
        token_data["price_usd"] = _safe_float(analytics.get("price"))

    mcap_val = analytics.get("fdv") or analytics.get("market_cap") or analytics.get("mcap")
    if _safe_float(token_data.get("cap_usd"), 0.0) <= 0 and _safe_float(mcap_val, 0.0) > 0:
        token_data["cap_usd"] = _safe_float(mcap_val)

    liq_val = analytics.get("header_liq_usd") or analytics.get("liquidity_usd") or analytics.get("liquidity")
    liq_accepted = bool(analytics.get("gmgn_liquidity_accepted"))
    if liq_accepted and _safe_float(liq_val, 0.0) > 0:
        token_data["gmgn_header_liquidity_usd"] = _safe_float(liq_val)
        if _safe_float(token_data.get("pair_liquidity_usd"), 0.0) <= 0:
            token_data["pair_liquidity_usd"] = _safe_float(liq_val)
    if analytics.get("gmgn_liquidity_reason"):
        token_data["gmgn_liquidity_reason"] = analytics.get("gmgn_liquidity_reason")
    token_data["gmgn_liquidity_accepted"] = liq_accepted

    creation_time = (
        analytics.get("pool_creation_timestamp")
        or analytics.get("open_timestamp")
        or analytics.get("creation_timestamp")
    )
    if creation_time and _safe_float(token_data.get("token_age_min")) <= 0:
        token_data["token_age_min"] = int(max(0, (time.time() - float(creation_time)) / 60))

    time_keys = [
        ("1m", "m1"), ("5m", "m5"), ("15m", "m15"), ("30m", "m30"),
        ("1h", "h1"), ("3h", "h3"), ("6h", "h6"), ("24h", "h24"),
    ]
    gmgn_prefer_keys = {"chg_1m", "chg_5m", "chg_1h", "chg_24h"}
    raw_data = analytics.get("raw_data") or {}
    for src_key, alt_key in time_keys:
        dst = f"chg_{src_key}"
        new_v = analytics.get(dst)
        if new_v is None:
            new_v = analytics.get(f"price_change_{alt_key}")
        if new_v is None:
            new_v = analytics.get(f"price_change_{src_key}")
        if new_v is None:
            new_v = raw_data.get(dst)
        if new_v is None:
            continue
        if patch_timeframes_only_when_missing and token_data.get(dst) is not None and dst not in gmgn_prefer_keys:
            continue
        token_data[dst] = new_v

    merged_burned = _prefer_positive_flag(token_data.get("is_burned"), analytics.get("is_burned"))
    if merged_burned is not None:
        token_data["is_burned"] = merged_burned
    if analytics.get("is_burned") is not None:
        token_data["gmgn_burned_confirmed"] = True

    merged_dex_paid = _prefer_positive_flag(token_data.get("dex_paid"), analytics.get("dex_paid"))
    if merged_dex_paid is not None:
        token_data["dex_paid"] = merged_dex_paid
    if analytics.get("dex_paid") is not None:
        token_data["gmgn_dex_paid_confirmed"] = True

    merged_locked = _prefer_positive_flag(token_data.get("is_locked"), analytics.get("is_locked"))
    if merged_locked is not None:
        token_data["is_locked"] = merged_locked
        if token_data.get("liquidity_locked") is None or (
            token_data.get("liquidity_locked") is False and merged_locked is True
        ):
            token_data["liquidity_locked"] = merged_locked
    if analytics.get("is_locked") is not None:
        token_data["gmgn_locked_confirmed"] = True

    if token_data.get("mint_authority_present") is None and analytics.get("mint_authority_present") is not None:
        token_data["mint_authority_present"] = bool(analytics.get("mint_authority_present"))
    if analytics.get("mint_authority_present") is not None:
        token_data["gmgn_mint_confirmed"] = True
    if token_data.get("freeze_authority_present") is None and analytics.get("freeze_authority_present") is not None:
        token_data["freeze_authority_present"] = bool(analytics.get("freeze_authority_present"))
    if analytics.get("freeze_authority_present") is not None:
        token_data["gmgn_freeze_confirmed"] = True

    if analytics.get("screenshot"):
        token_data["chart_screenshot"] = analytics.get("screenshot")

    raw = raw_data if isinstance(raw_data, dict) else {}
    tag_map = {
        "gmgn_smart": raw.get("smart"),
        "gmgn_kol": raw.get("kol"),
        "gmgn_blue_chip": raw.get("blue_chip"),
        "gmgn_sniper": raw.get("sniper"),
        "gmgn_phishing_wallets": raw.get("phishing_wallets"),
        "gmgn_rat": raw.get("rat"),
        "gmgn_dev": raw.get("dev"),
        "gmgn_bundle": raw.get("bundle"),
    }
    for key, new_v in tag_map.items():
        if new_v is None:
            continue
        try:
            iv = int(float(new_v))
        except Exception:
            continue
        token_data[key] = iv

    if analytics.get("gmgn_tags_present") is not None:
        token_data["gmgn_tags_present"] = bool(analytics.get("gmgn_tags_present"))
    if analytics.get("gmgn_result_strength"):
        token_data["gmgn_result_strength"] = str(analytics.get("gmgn_result_strength"))
    if "popup_reason" in analytics:
        token_data["gmgn_popup_reason"] = str(analytics.get("popup_reason") or "")
    if "blocked_reason" in analytics or analytics.get("gmgn_page_blocked_reason") is not None:
        token_data["gmgn_blocked_reason"] = str(
            analytics.get("blocked_reason") or analytics.get("gmgn_page_blocked_reason") or ""
        )
    if "target_ready" in analytics:
        token_data["gmgn_target_ready"] = analytics.get("target_ready")
    if "layout_ready" in analytics:
        token_data["gmgn_layout_ready"] = analytics.get("layout_ready")
    analytics_tag_count = _gmgn_tag_non_null_count(analytics)
    merged_tag_count = _gmgn_tag_non_null_count(token_data)
    token_data["gmgn_tag_non_null_count"] = max(merged_tag_count, analytics_tag_count)

    gmgn_top10 = _safe_pct_text(analytics.get("top10_ratio"))
    if gmgn_top10:
        token_data["top10_ratio_gmgn"] = gmgn_top10
        token_data["top10_ratio_gmgn_observed"] = gmgn_top10

    token_data = _apply_liquidity_display_guard(token_data, "gmgn_apply")
    _log_safety_canonical_trace("gmgn_apply", str(token_data.get("ca") or ""), token_data)
    return token_data


async def _apply_execution_state_machine(
    ca: str,
    token_data: dict,
    decision: dict,
    *,
    strategy_id: str,
    strategy_config: Optional[dict],
    current_price: float,
    current_mcap: float,
    chat_id: int,
    message_id: int,
) -> tuple[dict, str]:
    decision = decision or {}
    action = _normalize_verdict(decision.get("verdict", ACTION_WATCH), ACTION_WATCH)
    current_state = _runtime_signal_state(ca, token_data, None)
    liq_ctx = get_decision_liquidity_context(token_data)
    strict_block_verdict = _normalize_verdict(
        canonical_pipeline_settings().get("strict_enter_block_verdict", ACTION_PROBE),
        ACTION_PROBE,
    )
    if strict_block_verdict not in {ACTION_WATCH, ACTION_PROBE}:
        strict_block_verdict = ACTION_PROBE

    if action == ACTION_ENTER and not liq_ctx["formal_enter_ready"]:
        action = strict_block_verdict
        decision["verdict"] = action
        old_reason = str(decision.get("reason") or "").strip()
        suffix = "【Strict流动性】缺少正式 exit liquidity，已降级为观察/试探。"
        decision["reason"] = (old_reason + " | " + suffix) if old_reason else suffix

    next_state = current_state

    if current_state == SIGNAL_STATE_ENTERED:
        if action == ACTION_EXIT and current_price > 0:
            _paper_portfolio_call("on_final_close", ca, current_price, current_mcap, reason="AI_EXIT")
            await tp_tracker.reset_to_observing(
                ca,
                current_price,
                anchor_price=current_price,
                reply_chat_id=chat_id,
                reply_msg_id=message_id,
            )
            next_state = SIGNAL_STATE_OBSERVING
        else:
            next_state = SIGNAL_STATE_ENTERED
    elif action == ACTION_ENTER and current_price > 0:
        await tp_tracker.init_position(
            ca=ca,
            entry_price=current_price,
            strategy_id=strategy_id,
            config=strategy_config or {},
            initial_mcap=current_mcap,
            reply_chat_id=chat_id,
            reply_msg_id=message_id,
        )

        existing_open = getattr(paper_portfolio_engine, "open_positions", {}) or {}
        if ca not in existing_open:
            paper_ret = paper_portfolio_engine.open_position(
                ca=ca,
                symbol=str(token_data.get("symbol") or "UNK"),
                strategy=str(strategy_id or "MIXED"),
                entry_price=current_price,
                entry_mcap=current_mcap,
                opened_at=time.time(),
            )
            if paper_ret.get("ok"):
                logger.info(
                    "PaperPortfolio ENTER | ca=%s | strategy=%s | alloc=%s SOL | cash_left=%s SOL",
                    ca[:6],
                    strategy_id,
                    paper_ret.get("allocated_sol"),
                    paper_ret.get("cash_left_sol"),
                )
            else:
                logger.info("PaperPortfolio ENTER skipped | ca=%s | reason=%s", ca[:6], paper_ret.get("reason"))
        next_state = SIGNAL_STATE_ENTERED
    elif action == ACTION_PROBE:
        await tp_tracker.arm_position(
            ca,
            strategy_id,
            strategy_config or {},
            current_price=current_price,
            current_mcap=current_mcap,
            reply_chat_id=chat_id,
            reply_msg_id=message_id,
        )
        next_state = SIGNAL_STATE_ARMED
    else:
        await tp_tracker.ensure_observing(
            ca,
            current_price,
            anchor_price=current_price,
            reply_chat_id=chat_id,
            reply_msg_id=message_id,
        )
        next_state = SIGNAL_STATE_OBSERVING

    token_data["decision_action"] = action
    token_data["signal_state"] = next_state
    _apply_runtime_metadata(token_data, signal_state=next_state, decision_action=action)
    _log_canonical_state(ca, token_data, action, next_state)
    return decision, next_state


async def _late_merge_gmgn_result(
    ca: str,
    gmgn_task: asyncio.Task,
    chat_id: int,
    message_id: int,
):
    try:
        logger.info("LateGMGN | ca=%s | awaiting_result", ca[:8])
        analytics = await gmgn_task
    except Exception as e:
        logger.warning("LateGMGN | ca=%s | task_failed=%s", ca[:8], e)
        return

    analytics = analytics or {}
    needs_full_scan = (
        not analytics.get("screenshot")
        or analytics.get("gmgn_result_strength") in {"weak", "partial"}
        or analytics.get("is_locked") is None
        or analytics.get("dex_paid") is None
        or analytics.get("is_burned") is None
    )
    if needs_full_scan:
        full_analytics = await safe_call(
            get_gmgn_analytics(ca, mode="full", priority="high", route="interactive"),
            45,
            "LateGMGN_Full",
        ) or {}
        analytics = _merge_gmgn_results(analytics, full_analytics)

    if not analytics:
        logger.info("LateGMGN | ca=%s | empty_result", ca[:8])
        return

    record = await db.get_signal_snapshot(ca)
    if not record:
        logger.info("LateGMGN | ca=%s | record_missing", ca[:8])
        return

    terminal_states = record.get("terminal_states", {}) or {}
    token_data = normalize_token_data(ca, {}, "LATE_GMGN", chat_id, message_id)
    token_data = _merge_existing_terminal(token_data, terminal_states)
    token_data = _ensure_runtime_token_ca(token_data, ca)
    before_merge = dict(token_data)
    old_confirmed_top10 = get_confirmed_top10_pct(before_merge)
    old_action = str(terminal_states.get("decision_action") or token_data.get("decision_action") or ACTION_WATCH)
    old_reason = str(
        terminal_states.get("decision_reason")
        or record.get("ai_narrative")
        or terminal_states.get("ai_narrative")
        or ""
    )
    old_tag_count = _gmgn_tag_non_null_count(before_merge)
    old_avatar_path = str(before_merge.get("token_image_path") or "")
    old_avatar_url = str(before_merge.get("token_image_url") or "")
    old_decision_liq = _safe_float(get_decision_liquidity_usd(before_merge), 0.0)
    old_late_gmgn_top10 = before_merge.get("top10_ratio_gmgn")
    new_late_gmgn_top10 = _extract_late_gmgn_top10_value(analytics)

    gate_state = _late_gmgn_merge_gate_state(analytics)
    token_data["late_gmgn_merge_blocked"] = bool(gate_state.get("blocked"))
    token_data["late_gmgn_merge_block_reason"] = str(gate_state.get("reason") or "")
    token_data = _apply_top10_semantic_research(token_data, bq_data=None, late_gmgn_value=new_late_gmgn_top10)

    logger.info(
        "LateGMGNMergeGateTrace | ca=%s | blocked=%s | reason=%s | strength=%s",
        ca[:8],
        bool(gate_state.get("blocked")),
        str(gate_state.get("reason") or ""),
        str(gate_state.get("strength") or ""),
    )
    if gate_state.get("blocked"):
        token_data = _append_late_gmgn_top10_history(
            token_data,
            old_top10=old_late_gmgn_top10,
            new_top10=new_late_gmgn_top10,
            old_action=old_action,
            new_action=old_action,
            reasons=[str(gate_state.get("reason") or "late_merge_blocked")],
        )
        stable_snapshot = _build_stable_snapshot(token_data, analytics)
        terminal_states.update(_top10_research_terminal_patch(token_data))
        terminal_states["stable_snapshot"] = stable_snapshot
        await db.update_terminal_states(ca, terminal_states, status=_runtime_signal_state(ca, terminal_states, record))
        logger.info("LateGMGN | ca=%s | merge_blocked=%s", ca[:8], str(gate_state.get("reason") or ""))
        return

    token_data = _apply_gmgn_analytics(token_data, analytics, patch_timeframes_only_when_missing=True)
    _log_liquidity_trace("late_gmgn_after_apply", ca, token_data)
    _log_safety_canonical_trace("late_gmgn_after_apply", ca, token_data)
    token_data = _resolve_canonical_metrics(token_data, analytics, bq_data=None)
    token_data = _apply_top10_semantic_research(token_data, bq_data=None, late_gmgn_value=token_data.get("top10_ratio_gmgn"))
    _log_liquidity_trace("late_gmgn_after_canonical", ca, token_data)
    _log_strict_trace("canonical", ca, token_data)
    _log_safety_canonical_trace("late_gmgn_after_canonical", ca, token_data)

    current_state = _runtime_signal_state(ca, terminal_states, record)
    current_action = terminal_states.get("decision_action") or token_data.get("decision_action") or ACTION_WATCH
    token_data["top10_pending_gmgn_review"] = False
    token_data["gmgn_render_pending"] = False
    _apply_runtime_metadata(token_data, signal_state=current_state, decision_action=current_action)

    refreshed_avatar_url = ""
    refreshed_avatar_source = ""
    if not token_data.get("token_image_url") and not token_data.get("token_image_path"):
        avatar_refresh = await safe_call(
            fetcher.prime_avatar_sources(ca, token_data),
            4,
            "LateGMGN_AvatarPrime",
        )
        if isinstance(avatar_refresh, tuple) and len(avatar_refresh) >= 2:
            refreshed_avatar_url = str(avatar_refresh[0] or "")
            refreshed_avatar_source = str(avatar_refresh[1] or "")
        if refreshed_avatar_url:
            token_data["token_image_url"] = refreshed_avatar_url
            token_data["token_image_source"] = refreshed_avatar_source

    avatar_path = await safe_call(
        fetcher.ensure_token_avatar(ca, token_data.get("token_image_url", ""), token_data.get("token_image_source", "")),
        10,
        "LateGMGN_Avatar",
    )
    if avatar_path:
        token_data["token_image_path"] = avatar_path
    if not old_avatar_path and not old_avatar_url:
        logger.info(
            "AvatarTrace | stage=late_avatar_refresh | ca=%s | success=%s",
            ca[:8],
            bool(avatar_path or token_data.get("token_image_url")),
        )

    rerun_reasons = _late_gmgn_rerun_reasons(before_merge, token_data)
    new_late_gmgn_top10 = token_data.get("top10_ratio_gmgn")
    if not rerun_reasons:
        token_data = _append_late_gmgn_top10_history(
            token_data,
            old_top10=old_late_gmgn_top10,
            new_top10=new_late_gmgn_top10,
            old_action=old_action,
            new_action=current_action,
            reasons=["no_material_improvement"],
        )
        stable_snapshot = _build_stable_snapshot(token_data, analytics)
        terminal_states.update(_top10_research_terminal_patch(token_data))
        terminal_states["stable_snapshot"] = stable_snapshot
        await db.update_terminal_states(ca, terminal_states, status=current_state)
        logger.info("LateGMGN | ca=%s | no_material_improvement", ca[:8])
        return

    analytics_for_ai = _build_analytics_for_ai(analytics, terminal_states)
    if token_data.get("chart_screenshot") and not analytics_for_ai.get("screenshot"):
        analytics_for_ai["screenshot"] = token_data.get("chart_screenshot")

    decision = _sanitize_top10_pending_reason(
        _sanitize_ai_reason_by_metrics(
            await safe_call(
                brain.analyze_dynamic_strategy(token_data, terminal_states, analytics_for_ai),
                90,
                "LateGMGN_AI_Dynamic",
            )
            or {
                "verdict": current_action,
                "reason": old_reason or "结构化补充结果已合并，已重新评估",
            },
            token_data,
        ),
        token_data,
    )
    decision["verdict"] = _normalize_verdict(decision.get("verdict", current_action), current_action or ACTION_WATCH)
    if "GMGN" in str(decision.get("reason") or ""):
        decision["reason"] = "结构化补充结果已合并，已重新评估"
    decision, pos_info, _ = apply_final_gate(token_data, decision, None)
    token_data["decision_action"] = decision.get("verdict") or current_action
    token_data["decision_reason"] = decision.get("reason") or old_reason
    token_data["pos_info"] = pos_info
    _apply_runtime_metadata(token_data, signal_state=current_state, decision_action=token_data["decision_action"])
    token_data = _append_late_gmgn_top10_history(
        token_data,
        old_top10=old_late_gmgn_top10,
        new_top10=new_late_gmgn_top10,
        old_action=old_action,
        new_action=token_data.get("decision_action") or current_action,
        reasons=rerun_reasons,
    )

    stable_snapshot = _build_stable_snapshot(token_data, analytics_for_ai)
    terminal_states.update(
        {
            "symbol": token_data.get("symbol", terminal_states.get("symbol", "UNK")),
            "token_image_url": token_data.get("token_image_url", terminal_states.get("token_image_url", "")),
            "token_image_path": token_data.get("token_image_path", terminal_states.get("token_image_path", "")),
            "token_image_source": token_data.get("token_image_source", terminal_states.get("token_image_source", "")),
            "dex_paid": token_data.get("dex_paid", terminal_states.get("dex_paid")),
            "is_locked": token_data.get("is_locked", terminal_states.get("is_locked")),
            "is_burned": token_data.get("is_burned", terminal_states.get("is_burned")),
            "mint_authority_present": token_data.get("mint_authority_present", terminal_states.get("mint_authority_present")),
            "freeze_authority_present": token_data.get("freeze_authority_present", terminal_states.get("freeze_authority_present")),
            "cap_usd": token_data.get("cap_usd", terminal_states.get("cap_usd", 0)),
            "liquidity_usd": token_data.get("liquidity_usd", terminal_states.get("liquidity_usd", 0)),
            "pair_liquidity_usd": token_data.get("pair_liquidity_usd", terminal_states.get("pair_liquidity_usd", 0)),
            "exit_liquidity_usd": token_data.get("exit_liquidity_usd", terminal_states.get("exit_liquidity_usd", 0)),
            "gmgn_header_liquidity_usd": token_data.get("gmgn_header_liquidity_usd", terminal_states.get("gmgn_header_liquidity_usd")),
            "gmgn_liquidity_accepted": token_data.get("gmgn_liquidity_accepted", terminal_states.get("gmgn_liquidity_accepted")),
            "gmgn_liquidity_reason": token_data.get("gmgn_liquidity_reason", terminal_states.get("gmgn_liquidity_reason")),
            "top10_raw_pct": token_data.get("top10_raw_pct"),
            "top10_adjusted_pct": token_data.get("top10_adjusted_pct"),
            "top10_ratio_gmgn": token_data.get("top10_ratio_gmgn", terminal_states.get("top10_ratio_gmgn")),
            "metric_confidence": token_data.get("metric_confidence"),
            "source_conflict": token_data.get("source_conflict"),
            "canonical_stage": token_data.get("canonical_stage"),
            "canonical_metadata": token_data.get("canonical_metadata"),
            "top10_adjustment_semantics": token_data.get("top10_adjustment_semantics"),
            "top10_entity_adjusted": token_data.get("top10_entity_adjusted"),
            "chg_1m": token_data.get("chg_1m", terminal_states.get("chg_1m")),
            "chg_5m": token_data.get("chg_5m", terminal_states.get("chg_5m")),
            "chg_15m": token_data.get("chg_15m", terminal_states.get("chg_15m")),
            "chg_30m": token_data.get("chg_30m", terminal_states.get("chg_30m")),
            "chg_1h": token_data.get("chg_1h", terminal_states.get("chg_1h")),
            "chg_3h": token_data.get("chg_3h", terminal_states.get("chg_3h")),
            "chg_6h": token_data.get("chg_6h", terminal_states.get("chg_6h")),
            "chg_24h": token_data.get("chg_24h", terminal_states.get("chg_24h")),
            "gmgn_tags_present": token_data.get("gmgn_tags_present", terminal_states.get("gmgn_tags_present")),
            "gmgn_result_strength": token_data.get("gmgn_result_strength", terminal_states.get("gmgn_result_strength")),
            "gmgn_smart": token_data.get("gmgn_smart", terminal_states.get("gmgn_smart")),
            "gmgn_kol": token_data.get("gmgn_kol", terminal_states.get("gmgn_kol")),
            "gmgn_blue_chip": token_data.get("gmgn_blue_chip", terminal_states.get("gmgn_blue_chip")),
            "gmgn_sniper": token_data.get("gmgn_sniper", terminal_states.get("gmgn_sniper")),
            "gmgn_phishing_wallets": token_data.get("gmgn_phishing_wallets", terminal_states.get("gmgn_phishing_wallets")),
            "gmgn_rat": token_data.get("gmgn_rat", terminal_states.get("gmgn_rat")),
            "gmgn_dev": token_data.get("gmgn_dev", terminal_states.get("gmgn_dev")),
            "gmgn_bundle": token_data.get("gmgn_bundle", terminal_states.get("gmgn_bundle")),
            "decision_liquidity_source": token_data.get("decision_liquidity_source"),
            "decision_liquidity_enter_ready": token_data.get("decision_liquidity_enter_ready"),
            "market_data_ready": token_data.get("market_data_ready"),
            "liquidity_data_ready": token_data.get("liquidity_data_ready"),
            "liquidity_source_error": token_data.get("liquidity_source_error"),
            "chart_screenshot": token_data.get("chart_screenshot", terminal_states.get("chart_screenshot", "")),
            "gmgn_tag_non_null_count": token_data.get("gmgn_tag_non_null_count", terminal_states.get("gmgn_tag_non_null_count")),
            "signal_state": current_state,
            "decision_action": token_data.get("decision_action") or current_action,
            "decision_reason": token_data.get("decision_reason") or old_reason,
            "top10_pending_gmgn_review": False,
            "gmgn_render_pending": False,
            "stable_snapshot": stable_snapshot,
        }
    )
    terminal_states.update(_top10_research_terminal_patch(token_data))

    await db.update_terminal_states(ca, terminal_states, status=current_state)
    logger.info(
        "LateGMGNDecision | ca=%s | rerun=true | old_top10=%s | new_top10=%s | old_action=%s | new_action=%s",
        ca[:8],
        old_confirmed_top10,
        get_confirmed_top10_pct(token_data),
        old_action,
        token_data.get("decision_action") or current_action,
    )
    if old_tag_count < 4 and _gmgn_tag_non_null_count(token_data) >= 4:
        logger.info("LateGMGNDecision | ca=%s | reason=tags_arrived", ca[:8])
    if old_decision_liq <= 0 and _safe_float(get_decision_liquidity_usd(token_data), 0.0) > 0:
        logger.info("LateGMGNDecision | ca=%s | reason=liquidity_arrived", ca[:8])
    if (
        not old_avatar_path
        and not old_avatar_url
        and (token_data.get("token_image_path") or token_data.get("token_image_url"))
    ):
        logger.info("LateGMGNDecision | ca=%s | reason=avatar_arrived", ca[:8])
    for reason in rerun_reasons:
        logger.info("LateGMGNDecision | ca=%s | reason=%s", ca[:8], reason)
    await update_user_message(
        chat_id=chat_id,
        message_id=message_id,
        ca=ca,
        token_data=token_data,
        decision=decision,
    )
    """
        decision={
            "verdict": terminal_states.get("decision_action") or ACTION_WATCH,
            "reason": record.get("ai_narrative") or terminal_states.get("ai_narrative") or "地址标签结果已补齐，已刷新面板。",
        },
    )
    """
    _log_liquidity_trace("late_gmgn_merged", ca, token_data)
    logger.info("LateGMGN | ca=%s | refreshed_message=%s", ca[:8], message_id)


async def _return_none() -> None:
    return None


@main_router.callback_query(F.data.startswith("deep_ai:"))
async def process_deep_ai_callback(cq: CallbackQuery):
    ca = cq.data.split(":")[1]
    await cq.answer("🧠 正在调取大模型矩阵进行深度分析...", show_alert=False)
    spawn_task(trigger_deep_ai_report(ca, cq.message.chat.id, cq.message.message_id), f"DeepAI_{ca[:6]}")


async def trigger_deep_ai_report(ca: str, chat_id: int, msg_id: int):
    try:
        record = await db.get_signal_snapshot(ca)
        terminal_states = record.get("terminal_states", {}) if record else {}

        raw_market, helius_sec, analytics, bq_data = await asyncio.gather(
            safe_call(get_market_data(ca), 12, "DeepAI_Market"),
            safe_call(get_helius_security(ca), 8, "DeepAI_Helius"),
            safe_call(get_gmgn_analytics(ca, mode="full", priority="high", route="interactive"), 30, "DeepAI_GMGN"),
            safe_call(bitquery.fetch_comprehensive_data(ca), 20, "DeepAI_Bitquery"),
        )

        token_data = normalize_token_data(
            ca,
            raw_market or {"symbol": terminal_states.get("symbol", "TOKEN")},
            "DEEP_AI",
            chat_id,
            msg_id,
        )
        token_data = _merge_existing_terminal(token_data, terminal_states)
        token_data = _ensure_runtime_token_ca(token_data, ca)
        token_data = _apply_helius_security(token_data, helius_sec)
        token_data = await _prime_first_card_avatar(ca, token_data)
        token_data = _apply_gmgn_analytics(token_data, analytics, patch_timeframes_only_when_missing=True)
        _log_liquidity_trace("after_gmgn_analytics", ca, token_data)
        token_data = _resolve_canonical_metrics(token_data, analytics, bq_data)
        _apply_runtime_metadata(
            token_data,
            signal_state=_runtime_signal_state(ca, terminal_states, record),
            decision_action=token_data.get("decision_action") or ACTION_WATCH,
        )
        _log_liquidity_trace("after_canonical_metrics", ca, token_data)
        _log_strict_trace("canonical", ca, token_data)

        avatar_path = await safe_call(
            fetcher.ensure_token_avatar(ca, token_data.get("token_image_url", ""), token_data.get("token_image_source", "")),
            10,
            "DeepAI_Avatar",
        )
        if avatar_path:
            token_data["token_image_path"] = avatar_path

        analytics_for_ai = _build_analytics_for_ai(analytics, terminal_states)
        decision = _sanitize_top10_pending_reason(
            _sanitize_ai_reason_by_metrics(
                await brain.analyze_dynamic_strategy(token_data, terminal_states, analytics_for_ai),
                token_data,
            ),
            token_data,
        )

        initial_msg_id = record.get("initial_msg_id") if record and record.get("initial_msg_id") else msg_id
        report_text = build_ai_report_text(ca, token_data, decision)
        await send_thread_reply(chat_id, initial_msg_id, report_text)
        await update_user_message(chat_id=chat_id, message_id=initial_msg_id, ca=ca, token_data=token_data, decision=decision)
    except Exception as e:
        logger.error(f"❌ 深度报告生成失败: {e}", exc_info=True)


async def trigger_milestone_update(ca: str, chat_id: int, record: dict, current_price: float, current_mcap: float, delta: float, trigger_gate: Optional[int] = None):
    try:
        terminal_states = record.get("terminal_states", {}) or {}
        token_data = {
            "symbol": terminal_states.get("symbol", "TOKEN"),
            "price_usd": current_price,
            "cap_usd": current_mcap,
            "ca": ca,
        }
        token_data = _merge_existing_terminal(token_data, terminal_states)
        analytics_for_ai = _build_analytics_for_ai(None, terminal_states)

        decision = _sanitize_top10_pending_reason(
            _sanitize_ai_reason_by_metrics(
                await brain.analyze_dynamic_strategy(token_data, terminal_states, analytics_for_ai),
                token_data,
            ),
            token_data,
        )

        initial_msg_id = record.get("initial_msg_id")
        text = build_milestone_text(ca, token_data, decision, delta)

        if initial_msg_id:
            await send_thread_reply(chat_id, initial_msg_id, text)

        await db.update_milestone(ca, current_price)
    except Exception as e:
        logger.error(f"❌ 战报更新失败: {e}", exc_info=True)


async def safe_call(coro, timeout_s: int, name: str):
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning(f"⏳ {name} 超时({timeout_s}s)")
        return None
    except Exception as e:
        logger.exception(f"💥 {name} 异常: {e}")
        return None


async def get_market_data_force(ca: str):
    try:
        return await fetcher.get_market_data(ca, force=True)
    except TypeError:
        return await get_market_data(ca)
    except Exception:
        return await get_market_data(ca)


def normalize_token_data(ca: str, raw_market: dict, source: str, chat_id: int, msg_id: int):
    raw_market = raw_market or {}

    def _first_present(*values):
        for value in values:
            if value is not None and value != "":
                return value
        return None

    symbol = raw_market.get("symbol", "UNK")
    name = raw_market.get("name", "")

    price_usd = raw_market.get("priceUsd") or raw_market.get("price_usd") or 0
    cap_usd = raw_market.get("fdv") or raw_market.get("cap_usd") or raw_market.get("mcap") or 0

    pair_liq_usd = raw_market.get("pair_liquidity_usd")
    if pair_liq_usd is None and isinstance(raw_market.get("liquidity"), dict):
        pair_liq_usd = raw_market.get("liquidity", {}).get("usd")

    exit_liq_usd = _first_present(
        raw_market.get("exit_liquidity_usd"),
        raw_market.get("birdeye_liquidity_usd"),
    )
    liq_usd = _first_present(raw_market.get("liquidity_usd"), exit_liq_usd, pair_liq_usd)

    vol_h24 = raw_market.get("volume_h24")
    if not vol_h24 and isinstance(raw_market.get("volume"), dict):
        vol_h24 = raw_market.get("volume", {}).get("h24")
    vol_h24 = vol_h24 or 0

    chg_5m = raw_market.get("chg_5m")
    if chg_5m is None:
        pc = raw_market.get("priceChange") or {}
        chg_5m = pc.get("m5")
        chg_1h = pc.get("h1")
        chg_6h = pc.get("h6")
        chg_24h = pc.get("h24")
    else:
        chg_1h = raw_market.get("chg_1h")
        chg_6h = raw_market.get("chg_6h")
        chg_24h = raw_market.get("chg_24h")

    token_data = {
        "ca": ca,
        "symbol": symbol,
        "name": name,
        "chain": "SOL",
        "source": source,
        "chat_id": chat_id,
        "reply_chat_id": chat_id,
        "msg_id": msg_id,
        "price_usd": price_usd,
        "cap_usd": cap_usd,
        "pair_liquidity_usd": pair_liq_usd,
        "exit_liquidity_usd": exit_liq_usd,
        "birdeye_liquidity_usd": raw_market.get("birdeye_liquidity_usd"),
        "liquidity_usd": liq_usd,
        "dex_id": raw_market.get("dex_id"),
        "market_data_ready": raw_market.get("market_data_ready"),
        "liquidity_data_ready": raw_market.get("liquidity_data_ready"),
        "liquidity_source_error": raw_market.get("liquidity_source_error"),
        "volume_h24": vol_h24,
        "dex_paid": raw_market.get("dex_paid"),
        "is_locked": raw_market.get("is_locked"),
        "liquidity_locked": raw_market.get("liquidity_locked", raw_market.get("is_locked")),
        "is_burned": raw_market.get("is_burned"),
        "token_age_min": raw_market.get("token_age_min", 0),
        "buys_24h": raw_market.get("buys_24h", 0),
        "sells_24h": raw_market.get("sells_24h", 0),
        "buy_sell_ratio": raw_market.get("buy_sell_ratio", 0.0),
        "chg_1m": raw_market.get("chg_1m"),
        "chg_5m": chg_5m,
        "chg_15m": raw_market.get("chg_15m"),
        "chg_30m": raw_market.get("chg_30m"),
        "chg_1h": chg_1h,
        "chg_3h": raw_market.get("chg_3h"),
        "chg_6h": chg_6h,
        "chg_24h": chg_24h,
        "token_image_url": raw_market.get("token_image_url") or raw_market.get("logo"),
        "token_image_path": raw_market.get("token_image_path"),
        "token_image_source": raw_market.get("token_image_source"),
    }
    token_data = _apply_liquidity_display_guard(token_data, "normalize")
    _log_liquidity_trace("normalize_token_data", ca, token_data)
    _log_strict_trace("normalize", ca, token_data)
    return token_data



def _apply_lp_status_shadow_fields(token_data: dict, shadow_payload: Optional[dict]) -> dict:
    td = dict(token_data or {})
    shadow = shadow_payload if isinstance(shadow_payload, dict) else {}

    for stale_key in (
        "is_burned",
        "is_locked",
        "liquidity_locked",
        "lp_burned_pct",
        "lp_locked_pct",
        "lp_status_source",
        "lp_status_confidence",
        "lp_status_reason",
        "lp_status_phase",
        "lp_status_phase_conflict",
        "lp_status_source_conflict",
        "lp_status_conflict_reason",
    ):
        td.pop(stale_key, None)

    for key in (
        "lp_burned_pct",
        "lp_locked_pct",
        "lp_status_source",
        "lp_status_confidence",
        "lp_status_reason",
        "lp_status_phase",
        "lp_status_phase_conflict",
        "lp_status_source_conflict",
        "lp_status_conflict_reason",
    ):
        if key in shadow:
            td[key] = shadow.get(key)

    return td

async def fetch_token_info_fastpath_stage1_shadow(ca: str, source: str, chat_id: int, msg_id: int) -> dict:
    ca = str(ca or "").strip()
    if not ca:
        return {}

    raw_fast = await safe_call(fetcher.get_token_info_stage1_shadow(ca), 12, "TokenInfoStage1Shadow")
    if not isinstance(raw_fast, dict) or not raw_fast:
        raw_fast = {
            "symbol": "UNK",
            "fastpath_shadow_stage": "stage1_ultra_fast",
            "slow_followup_required": True,
            "stage1_source_status": {"dex": "error", "metadata": "error", "basic_rpc": "error"},
            "stage1_source_errors": ["stage1_shadow_call_failed"],
            "stage1_partial_degraded": True,
            "lp_status_phase": "unknown",
            "lp_status_source": "stage1_ultra_fast",
            "lp_status_confidence": 0.0,
            "lp_status_reason": "stage1 shadow call failed",
            "lp_status_phase_conflict": False,
            "lp_status_source_conflict": False,
            "lp_status_conflict_reason": "",
        }

    token_data = normalize_token_data(ca, raw_fast, source, chat_id, msg_id)
    token_data = _apply_lp_status_shadow_fields(token_data, raw_fast)

    token_data.pop("top10_ratio", None)
    token_data.pop("top10_ratio_source", None)
    token_data.pop("is_burned", None)
    token_data.pop("is_locked", None)
    token_data.pop("liquidity_locked", None)

    for key in [
        "market_data_ready",
        "liquidity_data_ready",
        "liquidity_source_error",
        "estimated_pair_liquidity_usd",
        "supply_raw",
        "supply_ui",
        "largest_accounts_present",
        "largest_accounts_sample_count",
        "top10_ratio_pending_exclusion_filter",
        "slow_followup_required",
        "authority_fields_pending",
        "metadata_json_uri",
        "fastpath_shadow_stage",
        "stage1_source_status",
        "stage1_source_errors",
        "stage1_partial_degraded",
        "basic_rpc_partial",
        "basic_rpc_reason",
    ]:
        if key in raw_fast:
            token_data[key] = raw_fast.get(key)

    canonical_meta = token_data.get("canonical_metadata") if isinstance(token_data.get("canonical_metadata"), dict) else {}
    canonical_meta["fastpath_mode"] = "api_rpc_ultra_fast_stage1"
    canonical_meta["slow_followup_pending"] = True
    canonical_meta["page_fields_pending"] = True
    canonical_meta["stage1_partial_degraded"] = bool(raw_fast.get("stage1_partial_degraded"))
    token_data["canonical_metadata"] = canonical_meta

    token_data = _apply_liquidity_display_guard(token_data, "stage1_shadow")
    _log_liquidity_trace("fetch_token_info_fastpath_stage1_shadow", ca, token_data)
    _log_strict_trace("stage1_shadow", ca, token_data)
    return token_data


async def enrich_token_info_fastpath_stage2_shadow(
    ca: str,
    source: str,
    chat_id: int,
    msg_id: int,
    stage1_token_data: Optional[dict] = None,
    known_exclude_owners: Optional[set[str]] = None,
) -> dict:
    ca = str(ca or "").strip()
    if not ca:
        return {}

    base = dict(stage1_token_data or {})
    if not base:
        base = await fetch_token_info_fastpath_stage1_shadow(ca, source, chat_id, msg_id)

    followup = await safe_call(
        fetcher.get_token_info_stage2_shadow(ca, stage1_payload=base, known_exclude_owners=known_exclude_owners),
        20,
        "TokenInfoStage2Shadow",
    )
    if not isinstance(followup, dict):
        followup = {
            "fastpath_shadow_stage": "stage2_followup_enrich",
            "slow_followup_required": True,
            "stage2_source_status": {
                "rugcheck": "error",
                "goplus": "error",
                "top10_finalize": "error",
            },
            "stage2_source_errors": ["stage2_shadow_call_failed"],
            "stage2_partial_degraded": True,
        }

    merged = dict(base)
    merged = _apply_lp_status_shadow_fields(merged, followup)

    merged.pop("is_burned", None)
    merged.pop("is_locked", None)
    merged.pop("liquidity_locked", None)

    for key in [
        "rugcheck_score",
        "is_honeypot",
        "is_blacklisted",
        "is_mintable",
        "transfer_pausable",
        "top10_ratio_pending_exclusion_filter",
        "top10_finalize_reason",
        "top10_raw_pct_self",
        "top10_owner_pct_self",
        "top10_effective_pct_self",
        "top10_effective_value_usd_self",
        "top1_effective_pct_self",
        "top1_effective_value_usd_self",
        "top10_calc_method_self",
        "top10_exclusion_summary_self",
        "top10_holder_count_raw_self",
        "top10_holder_count_owner_self",
        "top10_holder_count_effective_self",
        "fastpath_shadow_stage",
        "slow_followup_required",
        "stage2_source_status",
        "stage2_source_errors",
        "stage2_partial_degraded",
    ]:
        if key in followup:
            merged[key] = followup.get(key)

    top10_source = str(followup.get("top10_ratio_source") or "").strip().upper()
    if (
        top10_source in {"SOLANA_RPC", "BITQUERY", "HELIUS"}
        and not followup.get("top10_ratio_pending_exclusion_filter")
        and not _is_missing(followup.get("top10_ratio"))
    ):
        merged["top10_ratio"] = _safe_pct_text(followup.get("top10_ratio"))
        merged["top10_ratio_source"] = top10_source
    else:
        merged.pop("top10_ratio", None)
        merged.pop("top10_ratio_source", None)

    canonical_meta = merged.get("canonical_metadata") if isinstance(merged.get("canonical_metadata"), dict) else {}
    canonical_meta["fastpath_mode"] = "api_rpc_stage2_followup"
    canonical_meta["slow_followup_pending"] = False
    canonical_meta["stage2_partial_degraded"] = bool(followup.get("stage2_partial_degraded"))
    merged["canonical_metadata"] = canonical_meta

    _log_liquidity_trace("enrich_token_info_fastpath_stage2_shadow", ca, merged)
    _log_strict_trace("stage2_shadow", ca, merged)
    return merged

async def fetch_token_info_fastpath(
    ca: str,
    source: str,
    chat_id: int,
    msg_id: int,
    known_exclude_owners: Optional[set[str]] = None,
) -> dict:
    ca = str(ca or "").strip()
    if not ca:
        return {}

    def _strip_non_canonical_page_fields(payload: dict) -> dict:
        out = dict(payload or {})
        explicit_page_keys = {
            "raw_data",
            "screenshot",
            "chart_screenshot",
            "page_text",
            "visible_text",
            "combined_text",
            "header_block",
            "safety_block",
            "holder_tags_block",
            "top10_context",
        }
        for key in list(out.keys()):
            low = str(key or "").lower()
            if key in explicit_page_keys:
                out.pop(key, None)
                continue
            if low.startswith("gmgn_"):
                out.pop(key, None)
                continue
            if low.startswith("observed_"):
                out.pop(key, None)
                continue
            if low.startswith("page_"):
                out.pop(key, None)
                continue
        return out

    compat_fn = getattr(fetcher, "get_token_info_fastpath", None)

    if callable(compat_fn):
        token_data = await safe_call(
            compat_fn(ca),
            30,
            "FetchTokenInfoFastpathCompat",
        )
        if not isinstance(token_data, dict):
            token_data = {}
    else:
        stage1_fn = globals().get("fetch_token_info_fastpath_stage1_shadow")
        stage2_fn = globals().get("enrich_token_info_fastpath_stage2_shadow")
        if callable(stage1_fn) and callable(stage2_fn):
            stage1 = await stage1_fn(ca, source, chat_id, msg_id)
            token_data = await stage2_fn(
                ca,
                source,
                chat_id,
                msg_id,
                stage1_token_data=stage1,
                known_exclude_owners=known_exclude_owners,
            )
            if not isinstance(token_data, dict):
                token_data = dict(stage1 or {})
        else:
            token_data = {}

    token_data = dict(token_data or {})

    helius_security = token_data.get("helius_security")
    if isinstance(helius_security, dict):
        for key in ("mint_authority_present", "freeze_authority_present"):
            if token_data.get(key) is None and helius_security.get(key) is not None:
                token_data[key] = helius_security.get(key)

    canonical_meta = token_data.get("canonical_metadata")
    if not isinstance(canonical_meta, dict):
        canonical_meta = {}

    canonical_meta["fastpath_mode"] = "api_rpc_only"
    canonical_meta["page_fields_pending"] = True
    token_data["canonical_metadata"] = canonical_meta

    top10_source = str(token_data.get("top10_ratio_source") or "").strip().upper()
    top10_ratio = token_data.get("top10_ratio")
    pending_filter = bool(token_data.get("top10_ratio_pending_exclusion_filter"))

    if (
        top10_source in {"SOLANA_RPC", "BITQUERY", "HELIUS"}
        and top10_ratio not in (None, "", "?", "❓", "UNK")
        and not pending_filter
    ):
        token_data["top10_ratio"] = _safe_pct_text(top10_ratio)
        token_data["top10_ratio_source"] = top10_source
    else:
        token_data.pop("top10_ratio", None)
        token_data.pop("top10_ratio_source", None)

    token_data = _strip_non_canonical_page_fields(token_data)
    token_data = _apply_lp_status_shadow_fields(token_data, token_data)

    token_data.pop("is_burned", None)
    token_data.pop("is_locked", None)
    token_data.pop("liquidity_locked", None)

    return token_data

async def build_first_card_fastpath_shadow(
    ca: str,
    source: str,
    chat_id: int,
    msg_id: int,
) -> dict:
    ca = str(ca or "").strip()
    if not ca:
        return {}

    token_data = await fetch_token_info_fastpath(ca, source, chat_id, msg_id)

    avatar_prime = getattr(fetcher, "_prime_first_card_avatar_fastpath", None)
    if callable(avatar_prime):
        primed = await safe_call(
            avatar_prime(ca, token_data),
            2,
            "FirstCardAvatarFastpathShadow",
        )
        if isinstance(primed, dict) and primed:
            token_data.update(primed)

    token_data = _apply_lp_status_shadow_fields(token_data, token_data)
    token_data.pop("is_burned", None)
    token_data.pop("is_locked", None)
    token_data.pop("liquidity_locked", None)
    return token_data

def simple_gatekeeper(token_data: dict) -> bool:
    try:
        liq = float(get_decision_liquidity_usd(token_data) or 0)
        mcap = float(token_data.get("cap_usd") or 0)

        if liq < 500:
            logger.info(f"⚠️ Gatekeeper: 池子极小 (${liq:.0f}) - ALLOWED")
        if mcap < 1000:
            logger.info(f"⚠️ Gatekeeper: 市值极小 (${mcap:.0f}) - ALLOWED")

        return True
    except Exception:
        return True


async def process_new_signal(ca: str, source: str, chat_id: int, msg_id: int, raw_message: str = ""):
    ca = (ca or "").strip()
    if not ca:
        return

    now = time.time()
    async with _in_flight_lock:
        for k, ts in list(_in_flight_signals.items()):
            if now - ts > 600:
                _in_flight_signals.pop(k, None)
        last_ts = _in_flight_signals.get(ca)
        if last_ts and (now - last_ts < 30):
            logger.info(f"🛡️ 防暴盾生效: {ca[:6]}... 已静默拦截并发！")
            return
        _in_flight_signals[ca] = now

    logger.info(f"⚡ 开始处理信号: CA={ca} | 来源={source}")

    try:
        is_dm = ("DM_USER" in str(source) or source == "MANUAL_QUERY")

        if not is_dm:
            try:
                record = await asyncio.wait_for(db.get_signal_snapshot(ca), timeout=3.0)
                if record:
                    terminal_states = record.get("terminal_states", {}) or {}
                    try:
                        price_res = await fetcher.get_price_only(ca)
                        price = price_res[0] if isinstance(price_res, tuple) else float(price_res)
                        mcap = price_res[1] if isinstance(price_res, tuple) else 0.0

                        logger.info(f"🔎 [价格嗅探] CA: {ca[:6]}... | 最新现价: ${price:.6f}")

                        initial_price = float(record.get("entry_price") or 0)
                        last_notified_price = float(record.get("last_notified_price") or initial_price)

                        if price <= 0:
                            logger.info(f"♻️ {ca} 价格异常(初始:{initial_price}, 现价:{price})，静默拦截。")
                            return

                        if initial_price <= 0:
                            terminal_states["milestone_anchor_price"] = price
                            terminal_states.setdefault("entry_price", price)
                            stable = terminal_states.get("stable_snapshot") or {}
                            if _safe_float(stable.get("price_usd"), 0.0) <= 0:
                                stable["price_usd"] = price
                            terminal_states["stable_snapshot"] = stable
                            await safe_call(
                                db.save_initial_signal(ca, "SYSTEM", price, record.get("initial_msg_id") or msg_id, terminal_states),
                                2,
                                "DB_AnchorHeal",
                            )
                            logger.info(f"🩹 {ca} 里程碑锚点缺失，已用现价自愈为 1.00x 基准。")
                            return

                        current_multiplier = price / initial_price
                        peak_multiplier = max(1.0, last_notified_price / initial_price if initial_price > 0 else 1.0)
                        next_gate = max(2, int(peak_multiplier) + 1)
                        gate_tolerance = 0.10
                        gate_hit = current_multiplier >= max(1.0, next_gate - gate_tolerance)

                        if gate_hit:
                            logger.info(
                                f"🎉 [里程碑突破] {ca[:8]} 从 {peak_multiplier:.2f}x 飙升至 {current_multiplier:.2f}x！(突破 {next_gate}x 大关)"
                            )
                            spawn_task(
                                trigger_milestone_update(ca, chat_id, record, price, mcap, current_multiplier, next_gate),
                                f"Milestone_{ca[:6]}",
                            )
                            return
                        else:
                            logger.info(f"♻️ {ca} 已存在，当前 {current_multiplier:.2f}x，未突破 {next_gate}x 整数关口，静默拦截。")
                            return

                    except Exception as e:
                        logger.error(f"❌ 战报验价及整数倍计算失败: {e}")
                        return
            except Exception as e:
                logger.warning(f"⚠️ 数据库查重超时跳过: {e}")

        logger.info(f"⏳ 开始抓取 ({ca[:4]}...) 核心数据...")

        early_anchor_price = 0.0
        early_anchor_res = await safe_call(fetcher.get_price_only(ca), 3, "PriceOnly")
        if isinstance(early_anchor_res, tuple) and len(early_anchor_res) >= 1:
            early_anchor_price = _safe_float(early_anchor_res[0], 0.0)
        else:
            early_anchor_price = _safe_float(early_anchor_res, 0.0)

        token_data, helius_sec = await asyncio.gather(
            safe_call(
                fetch_token_info_fastpath_stage1_shadow(ca, source, chat_id, msg_id),
                12,
                "FirstCard_Stage1",
            ),
            safe_call(get_helius_security(ca), 5, "Helius"),
        )

        if not isinstance(token_data, dict) or not token_data:
            token_data = normalize_token_data(ca, {"symbol": "UNK"}, source, chat_id, msg_id)

        token_data = _apply_helius_security(token_data, helius_sec)
        token_data = await _prime_first_card_avatar(ca, token_data)
        if not token_data.get("token_image_path"):
            first_card_prime = await safe_call(
                fetcher.prime_avatar_sources(ca, token_data, allow_warm_probe=False),
                0.9,
                "FirstCard_AvatarPrime",
            )
            if isinstance(first_card_prime, tuple) and len(first_card_prime) >= 2:
                prime_url = str(first_card_prime[0] or "")
                prime_source = str(first_card_prime[1] or "")
                if prime_url:
                    token_data["token_image_url"] = prime_url
                    token_data["token_image_source"] = prime_source
                    prime_avatar_path = await safe_call(
                        fetcher.ensure_token_avatar(
                            ca,
                            prime_url,
                            source=prime_source,
                            fast_mode=True,
                        ),
                        0.9,
                        "FirstCard_AvatarPrime_Ensure",
                    )
                    logger.info(
                        "AvatarTrace | stage=first_card_sync_prime | ca=%s | source=%s | success=%s",
                        ca[:8],
                        prime_source or "",
                        bool(prime_avatar_path),
                    )
                    if prime_avatar_path:
                        token_data["token_image_path"] = prime_avatar_path
        stage1_followup_seed = dict(token_data)
        gmgn_preheat_task = asyncio.create_task(
            get_gmgn_analytics(ca, mode="fast", priority="high", route="interactive"),
            name=f"GMGNSeed_{ca[:6]}",
        )
        preheated_gmgn = await safe_call(asyncio.shield(gmgn_preheat_task), 1.6, "GMGN_FirstCard") or {}
        if preheated_gmgn:
            token_data = _apply_gmgn_analytics(token_data, preheated_gmgn, patch_timeframes_only_when_missing=True)
            _log_liquidity_trace("first_card_gmgn_apply", ca, token_data)
            _log_safety_canonical_trace("first_card_gmgn_apply", ca, token_data)

        # 首卡阶段不等待 GMGN / Bitquery / 头像落盘。
        # Top10 若没有可信来源，直接留空，等待深度链回写。
        token_data = _resolve_canonical_metrics(token_data, preheated_gmgn, None)
        _apply_runtime_metadata(token_data, signal_state=SIGNAL_STATE_NEW, decision_action=ACTION_WATCH)
        _log_canonical_state(ca, token_data, ACTION_WATCH, SIGNAL_STATE_NEW)
        _log_safety_canonical_trace("first_card_after_canonical", ca, token_data)

        if preheated_gmgn and token_data.get("token_image_url") and not token_data.get("token_image_path"):
            post_gmgn_avatar_path = await safe_call(
                fetcher.ensure_token_avatar(
                    ca,
                    token_data.get("token_image_url", ""),
                    token_data.get("token_image_source", ""),
                    fast_mode=True,
                ),
                0.6,
                "FirstCard_PostGMGN_Avatar",
            )
            logger.info(
                "AvatarTrace | stage=first_card_post_gmgn_materialize | ca=%s | success=%s",
                ca[:8],
                bool(post_gmgn_avatar_path),
            )
            if post_gmgn_avatar_path:
                token_data["token_image_path"] = post_gmgn_avatar_path

        simple_gatekeeper(token_data)

        ext_pnl = None
        if raw_message:
            m = re.search(r"(?:涨幅|Increase|Profit)[:：]?\s*([0-9\.,]+)%", raw_message, re.IGNORECASE)
            if not m:
                m = re.search(r"\+([0-9\.,]+)%", raw_message)
            if m:
                ext_pnl = m.group(1)

        token_data["external_pnl"] = ext_pnl

        try:
            await asyncio.wait_for(
                db.execute(
                    "INSERT INTO tokens_meta (ca, symbol, name) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                    ca,
                    token_data.get("symbol"),
                    token_data.get("name"),
                ),
                timeout=2.0,
            )
        except Exception:
            pass

        strat_res = detect_strategy(token_data)
        if isinstance(strat_res, tuple):
            token_data["strategy_id"] = str(strat_res[0])
        else:
            token_data["strategy_id"] = str(strat_res)

        logger.info("🚀 准备下发初期战报卡片...")
        fast_msg_id = await notify_user_fast(ca=ca, token_data=token_data)
        if not fast_msg_id:
            logger.error("❌ notify_user_fast 未返回 msg_id，发卡片失败！")
            return
        if not token_data.get("token_image_path"):
            spawn_task(_enqueue_avatar_enrichment(ca, chat_id, fast_msg_id), f"AvatarQueue_{ca[:6]}")

        try:
            entry_price = early_anchor_price if early_anchor_price > 0 else _safe_float(token_data.get("price_usd"), 0.0)
            if entry_price <= 0:
                pr = await safe_call(fetcher.get_price_only(ca), 3, "AnchorRetry")
                if isinstance(pr, tuple) and len(pr) >= 1:
                    entry_price = _safe_float(pr[0], entry_price)
                else:
                    entry_price = _safe_float(pr, entry_price)

            terminal_states_fast = {
                "symbol": token_data.get("symbol", "UNK"),
                "name": token_data.get("name") or "",
                "entry_price": entry_price,
                "milestone_anchor_price": entry_price,
                "cap_usd": _safe_float(token_data.get("cap_usd"), 0.0),
                "liquidity_usd": _safe_float(token_data.get("liquidity_usd"), 0.0),
                "pair_liquidity_usd": _safe_float(token_data.get("pair_liquidity_usd"), 0.0),
                "exit_liquidity_usd": _safe_float(token_data.get("exit_liquidity_usd"), 0.0),
                "top10_raw_pct": token_data.get("top10_raw_pct"),
                "top10_adjusted_pct": token_data.get("top10_adjusted_pct"),
                "metric_confidence": token_data.get("metric_confidence"),
                "source_conflict": token_data.get("source_conflict"),
                "canonical_stage": token_data.get("canonical_stage"),
                "canonical_metadata": token_data.get("canonical_metadata"),
                "top10_adjustment_semantics": token_data.get("top10_adjustment_semantics"),
                "top10_entity_adjusted": token_data.get("top10_entity_adjusted"),
                "decision_liquidity_source": token_data.get("decision_liquidity_source"),
                "decision_liquidity_enter_ready": token_data.get("decision_liquidity_enter_ready"),
                "signal_state": SIGNAL_STATE_OBSERVING,
                "decision_action": ACTION_WATCH,
                "token_image_url": token_data.get("token_image_url", ""),
                "token_image_path": token_data.get("token_image_path", ""),
                "is_burned": token_data.get("is_burned"),
                "is_locked": token_data.get("is_locked"),
                "dex_paid": token_data.get("dex_paid"),
                "reply_chat_id": chat_id,
                "stable_snapshot": _build_stable_snapshot(token_data),
            }
            await safe_call(
                db.save_initial_signal(
                    ca,
                    "SYSTEM",
                    entry_price,
                    fast_msg_id,
                    terminal_states_fast,
                    status=SIGNAL_STATE_OBSERVING,
                ),
                2,
                "DB_FastSave",
            )
            await safe_call(
                tp_tracker.ensure_observing(
                    ca,
                    entry_price,
                    anchor_price=entry_price,
                    reply_chat_id=chat_id,
                    reply_msg_id=fast_msg_id,
                ),
                2,
                "TP_ObserveInit",
            )
        except Exception:
            pass

        spawn_task(
            run_deep_analysis(
                ca,
                token_data,
                fast_msg_id,
                chat_id,
                use_insightx=(not is_dm),
                stage1_token_data=stage1_followup_seed,
                preheated_gmgn_task=gmgn_preheat_task,
            ),
            f"DeepAnalysis_{ca[:6]}",
        )

    except Exception as e:
        logger.exception(f"💥 process_new_signal 核心处理崩溃: {e}")


async def _legacy_run_deep_analysis_direct_enter(ca: str, token_data: dict, message_id: int, chat_id: int, use_insightx: bool = False):
    try:
        existing_record = await db.get_signal_snapshot(ca)
        existing_terminal = existing_record.get("terminal_states", {}) if existing_record else {}
        token_data = _merge_existing_terminal(token_data or {}, existing_terminal)
        token_data = _ensure_runtime_token_ca(token_data, ca)

        rug_task = safe_call(get_rugcheck_data(ca), 8, "RugCheck")
        bq_task = safe_call(bitquery.fetch_comprehensive_data(ca), 20, "Bitquery")
        goplus_task = safe_call(get_goplus_security(ca), 10, "GoPlus")
        gmgn_live_task = asyncio.create_task(
            get_gmgn_analytics(ca, mode="fast", priority="high", route="interactive"),
            name=f"GMGN_{ca[:6]}",
        )
        gmgn_task = safe_call(asyncio.shield(gmgn_live_task), 25, "GMGN")
        ix_task = safe_call(insightx_agent.fetch_deep_analysis(ca), 15, "InsightX") if use_insightx else _return_none()

        rug_data, bq_data, goplus_data, analytics, ix_data = await asyncio.gather(
            rug_task,
            bq_task,
            goplus_task,
            gmgn_task,
            ix_task,
        )
        analytics = analytics or {}
        late_gmgn_pending = False
        late_gmgn_task = None
        if not analytics and gmgn_live_task.done():
            try:
                analytics = gmgn_live_task.result() or {}
            except Exception as e:
                logger.warning("GMGN budget wait finished with error | ca=%s | err=%s", ca[:8], e)
                analytics = {}
        if not analytics:
            late_gmgn_pending = True
            if gmgn_live_task.done():
                late_gmgn_task = asyncio.create_task(
                    get_gmgn_analytics(ca, mode="full", priority="high", route="interactive"),
                    name=f"GMGNFollow_{ca[:6]}",
                )
        elif _gmgn_needs_followup(analytics):
            late_gmgn_pending = True
            if gmgn_live_task.done():
                late_gmgn_task = asyncio.create_task(
                    get_gmgn_analytics(ca, mode="full", priority="high", route="interactive"),
                    name=f"GMGNFollow_{ca[:6]}",
                )

        need_market_retry, retry_reason = _needs_market_retry(token_data)
        if need_market_retry:
            logger.info("🔄 启动二次挽救机制: 重试 DexScreener 以修复0值...")
            retry_market = await safe_call(get_market_data_force(ca), 5, "MarketRetry")
            if retry_market:
                token_data = _apply_retry_market_patch(token_data, retry_market)
                _log_liquidity_trace("market_retry_patch", ca, token_data)
                _log_strict_trace("retry_patch", ca, token_data)

        if rug_data:
            token_data["is_burned"] = (_safe_float(rug_data.get("lp_burned_pct"), 0) > 95)
            token_data["is_locked"] = (_safe_float(rug_data.get("lp_locked_pct"), 0) > 95)

        if goplus_data and goplus_data.get("is_honeypot"):
            token_data["risk_flags"] = token_data.get("risk_flags", []) + ["🚨 貔貅盘(GoPlus)"]

        token_data = _apply_gmgn_analytics(token_data, analytics, patch_timeframes_only_when_missing=True)
        _log_liquidity_trace("after_gmgn_analytics", ca, token_data)
        _log_safety_canonical_trace("after_gmgn_analytics", ca, token_data)
        token_data = _resolve_canonical_metrics(token_data, analytics, bq_data)
        token_data = _apply_top10_semantic_research(token_data, bq_data, token_data.get("top10_ratio_gmgn"))
        _apply_runtime_metadata(
            token_data,
            signal_state=_runtime_signal_state(ca, existing_terminal, existing_record),
            decision_action=token_data.get("decision_action") or ACTION_WATCH,
        )
        token_data["top10_pending_gmgn_review"] = _is_top10_pending_gmgn_review(token_data, late_gmgn_pending)
        token_data["gmgn_render_pending"] = _gmgn_render_pending(late_gmgn_pending, analytics, token_data)
        if token_data["top10_pending_gmgn_review"]:
            logger.info(
                "Top10PendingGMGN | ca=%s | primary=%s | reason=%s",
                ca[:8],
                _top10_primary_source(token_data) or "NONE",
                _top10_conflict_reason(token_data) or "pending_review",
            )
        _log_liquidity_trace("after_canonical_metrics", ca, token_data)
        _log_strict_trace("canonical", ca, token_data)
        _log_safety_canonical_trace("after_canonical_metrics", ca, token_data)

        avatar_path = await safe_call(
            fetcher.ensure_token_avatar(ca, token_data.get("token_image_url", ""), token_data.get("token_image_source", "")),
            10,
            "AvatarCache",
        )
        if avatar_path:
            token_data["token_image_path"] = avatar_path

        analytics_for_ai = _build_analytics_for_ai(analytics, existing_terminal)
        if token_data.get("chart_screenshot") and not analytics_for_ai.get("screenshot"):
            analytics_for_ai["screenshot"] = token_data.get("chart_screenshot")

        curr_price = _safe_float(token_data.get("price_usd"), 0.0)
        curr_mcap = _safe_float(token_data.get("cap_usd"), 0.0)

        if curr_price > 0:
            strat_res = detect_strategy(token_data)
            strategy_id = str(strat_res[0]) if isinstance(strat_res, tuple) else str(strat_res)
            config = strat_res[1] if isinstance(strat_res, tuple) else {}
            token_data["strategy_id"] = strategy_id

            await tp_tracker.init_position(
                ca=ca,
                entry_price=curr_price,
                strategy_id=strategy_id,
                config=config,
                initial_mcap=curr_mcap,
                reply_chat_id=chat_id,
                reply_msg_id=message_id,
            )
            await tp_tracker.observe_price(ca, curr_price)
            token_data["baseline"] = await tp_tracker.get_baseline_metrics(ca, current_price=curr_price)

            existing_open = getattr(paper_portfolio_engine, "open_positions", {}) or {}
            if ca not in existing_open:
                paper_ret = paper_portfolio_engine.open_position(
                    ca=ca,
                    symbol=str(token_data.get("symbol") or "UNK"),
                    strategy=str(strategy_id or "MIXED"),
                    entry_price=curr_price,
                    entry_mcap=curr_mcap,
                    opened_at=time.time(),
                )
                if paper_ret.get("ok"):
                    logger.info(
                        f"📒 PaperPortfolio 开仓成功: {ca[:6]}... | strategy={strategy_id} | "
                        f"alloc={paper_ret.get('allocated_sol')} SOL | cash_left={paper_ret.get('cash_left_sol')} SOL"
                    )
                else:
                    logger.info(f"📒 PaperPortfolio 未开仓: {ca[:6]}... | reason={paper_ret.get('reason')}")
            else:
                logger.info(f"📒 PaperPortfolio 已存在持仓，跳过重复开仓: {ca[:6]}...")

        if ix_data:
            token_data["insightx"] = {
                "gini": ix_data.get("gini_coefficient"),
                "smart_money": ix_data.get("smart_money_count"),
                "is_bundled": ix_data.get("bundled_sniper"),
                "partial": ix_data.get("insightx_partial"),
                "rate_limited": ix_data.get("insightx_rate_limited"),
            }
            if ix_data.get("bundled_sniper"):
                token_data["risk_flags"] = token_data.get("risk_flags", []) + ["🚨 疑似老鼠仓(InsightX)"]

        if LGB_AVAILABLE and lgb_model:
            try:
                features = calculate_ml_features(token_data, analytics_for_ai or {}, {})
                ml_features_array = np.array([[
                    _safe_float(token_data.get("cap_usd"), 0),
                    _safe_float(get_decision_liquidity_usd(token_data), 0),
                    _safe_float(features.get("smart_money_delta"), 0),
                    _safe_float(features.get("maker_vol_ratio"), 0),
                    _safe_float(features.get("overhang_ratio"), 0),
                    _safe_float(features.get("breakout_vol_ratio"), 0),
                ]])

                win_prob = lgb_model.predict(ml_features_array)[0]
                token_data["lgb_win_prob"] = win_prob

                if win_prob > 0.85:
                    token_data["risk_flags"] = token_data.get("risk_flags", []) + [f"🎯 AI预测极高胜率 ({win_prob:.1%})"]
                elif win_prob < 0.20:
                    token_data["risk_flags"] = token_data.get("risk_flags", []) + [f"🗑️ AI预测极低胜率 ({win_prob:.1%})"]
            except Exception as e:
                logger.error(f"⚠️ LightGBM 预测执行失败: {e}")

        temp_decision = {"verdict": ACTION_WATCH, "reason": "🧠 核心数据已就绪，AI 正在进行深度模型推演，请稍候..."}
        await update_user_message(chat_id=chat_id, message_id=message_id, ca=ca, token_data=token_data, decision=temp_decision)

        static_res = await safe_call(brain.analyze_static_narrative(token_data, analytics_for_ai), 90, "AI_Static") or {}
        if static_res.get("ai_image_read"):
            token_data["ai_image_read"] = static_res.get("ai_image_read")

        stable_snapshot = _build_stable_snapshot(token_data, analytics_for_ai)
        terminal_states = {
            "ai_narrative": static_res.get("ai_narrative") or "静态脑样本不足，暂以盘面与筹码为主。",
            "ai_image_read": static_res.get("ai_image_read") or "头像/社交样本不足，暂不下视觉结论。",
            "entry_price": curr_price,
            "milestone_anchor_price": _safe_float((existing_terminal or {}).get("milestone_anchor_price"), _safe_float((existing_terminal or {}).get("entry_price"), curr_price)) or curr_price,
            "is_burned": token_data.get("is_burned"),
            "is_locked": token_data.get("is_locked"),
            "dex_paid": token_data.get("dex_paid"),
            "symbol": token_data.get("symbol", "UNK"),
            "token_image_url": token_data.get("token_image_url", ""),
            "token_image_path": token_data.get("token_image_path", ""),
            "cap_usd": token_data.get("cap_usd", 0),
            "liquidity_usd": token_data.get("liquidity_usd", 0),
            "pair_liquidity_usd": token_data.get("pair_liquidity_usd", 0),
            "exit_liquidity_usd": token_data.get("exit_liquidity_usd", 0),
            "top10_raw_pct": token_data.get("top10_raw_pct"),
            "top10_adjusted_pct": token_data.get("top10_adjusted_pct"),
            "metric_confidence": token_data.get("metric_confidence"),
            "source_conflict": token_data.get("source_conflict"),
            "top10_pending_gmgn_review": token_data.get("top10_pending_gmgn_review"),
            "reply_chat_id": chat_id,
            "chart_screenshot": analytics_for_ai.get("screenshot", ""),
            "stable_snapshot": stable_snapshot,
        }
        terminal_states.update(_top10_research_terminal_patch(token_data))

        decision = _sanitize_top10_pending_reason(
            _sanitize_ai_reason_by_metrics(
                await safe_call(brain.analyze_dynamic_strategy(token_data, terminal_states, analytics_for_ai), 90, "AI_Dynamic") or {},
                token_data,
            ),
            token_data,
        )
        decision, pos_info, _ = apply_final_gate(token_data, decision, None)
        token_data["decision_reason"] = decision.get("reason", "")
        terminal_states["decision_reason"] = token_data["decision_reason"]
        token_data["pos_info"] = pos_info

        try:
            await db.save_initial_signal(ca, "SYSTEM", terminal_states["milestone_anchor_price"], message_id, terminal_states)
            await asyncio.wait_for(
                db.update_signal_analysis(
                    ca,
                    float(decision.get("score", 0)),
                    decision.get("reason", ""),
                ),
                timeout=2.0,
            )
        except Exception as e:
            logger.error(f"⚠️ 保存初始状态失败: {e}")

        await update_user_message(chat_id=chat_id, message_id=message_id, ca=ca, token_data=token_data, decision=decision)
        if late_gmgn_pending:
            logger.info("LateGMGN | ca=%s | scheduled", ca[:8])
            spawn_task(
                _late_merge_gmgn_result(ca, late_gmgn_task or gmgn_live_task, chat_id, message_id),
                f"LateGMGN_{ca[:6]}",
            )
        spawn_task(evolve_database(ca, token_data, analytics or {}, ix_data or {}), f"EvolveDB_{ca[:6]}")

    except Exception as e:
        logger.exception(f"💥 run_deep_analysis 异常: {e}")


async def run_deep_analysis(
    ca: str,
    token_data: dict,
    message_id: int,
    chat_id: int,
    use_insightx: bool = False,
    stage1_token_data: Optional[dict] = None,
    preheated_gmgn_task: Optional[asyncio.Task] = None,
):
    try:
        existing_record = await db.get_signal_snapshot(ca)
        existing_terminal = existing_record.get("terminal_states", {}) if existing_record else {}
        token_data = _merge_existing_terminal(token_data or {}, existing_terminal)
        token_data = _ensure_runtime_token_ca(token_data, ca)
        use_stage2_followup = isinstance(stage1_token_data, dict) and bool(stage1_token_data)
        rug_data = None
        goplus_data = None

        if use_stage2_followup:
            stage1_seed = dict(stage1_token_data)
            stage2_source = str(stage1_seed.get("source") or token_data.get("source") or "SYSTEM")
            stage2_chat_id = int(stage1_seed.get("reply_chat_id") or stage1_seed.get("chat_id") or chat_id or 0)
            stage2_msg_id = int(stage1_seed.get("msg_id") or message_id or 0)
            stage2_enriched = await safe_call(
                enrich_token_info_fastpath_stage2_shadow(
                    ca,
                    stage2_source,
                    stage2_chat_id,
                    stage2_msg_id,
                    stage1_token_data=stage1_seed,
                ),
                20,
                "Stage2Followup",
            )
            if isinstance(stage2_enriched, dict) and stage2_enriched:
                token_data = _apply_lp_status_shadow_fields(token_data, stage2_enriched)
                token_data.pop("is_burned", None)
                token_data.pop("is_locked", None)
                token_data.pop("liquidity_locked", None)

                for key in (
                    "rugcheck_score",
                    "is_honeypot",
                    "is_blacklisted",
                    "is_mintable",
                    "transfer_pausable",
                    "top10_ratio_pending_exclusion_filter",
                    "top10_finalize_reason",
                    "top10_raw_pct_self",
                    "top10_owner_pct_self",
                    "top10_effective_pct_self",
                    "top10_effective_value_usd_self",
                    "top1_effective_pct_self",
                    "top1_effective_value_usd_self",
                    "top10_calc_method_self",
                    "top10_exclusion_summary_self",
                    "top10_holder_count_raw_self",
                    "top10_holder_count_owner_self",
                    "top10_holder_count_effective_self",
                    "fastpath_shadow_stage",
                    "slow_followup_required",
                    "stage2_source_status",
                    "stage2_source_errors",
                    "stage2_partial_degraded",
                ):
                    if key in stage2_enriched:
                        token_data[key] = stage2_enriched.get(key)

                stage2_meta = stage2_enriched.get("canonical_metadata")
                if isinstance(stage2_meta, dict):
                    current_meta = token_data.get("canonical_metadata") if isinstance(token_data.get("canonical_metadata"), dict) else {}
                    current_meta.update(stage2_meta)
                    token_data["canonical_metadata"] = current_meta

                stage2_top10_source = str(stage2_enriched.get("top10_ratio_source") or "").strip().upper()
                if (
                    _is_trusted_top10_source(stage2_top10_source)
                    and not stage2_enriched.get("top10_ratio_pending_exclusion_filter")
                    and not _is_missing(stage2_enriched.get("top10_ratio"))
                ):
                    token_data["top10_ratio"] = _safe_pct_text(stage2_enriched.get("top10_ratio"))
                    token_data["top10_ratio_source"] = stage2_top10_source

            bq_task = safe_call(bitquery.fetch_comprehensive_data(ca), 20, "Bitquery")
            gmgn_live_task = preheated_gmgn_task or asyncio.create_task(
                get_gmgn_analytics(ca, mode="fast", priority="high", route="interactive"),
                name=f"GMGN_{ca[:6]}",
            )
            gmgn_task = safe_call(asyncio.shield(gmgn_live_task), 25, "GMGN")
            ix_task = safe_call(insightx_agent.fetch_deep_analysis(ca), 15, "InsightX") if use_insightx else _return_none()

            bq_data, analytics, ix_data = await asyncio.gather(
                bq_task,
                gmgn_task,
                ix_task,
            )
        else:
            rug_task = safe_call(get_rugcheck_data(ca), 8, "RugCheck")
            bq_task = safe_call(bitquery.fetch_comprehensive_data(ca), 20, "Bitquery")
            goplus_task = safe_call(get_goplus_security(ca), 10, "GoPlus")
            gmgn_live_task = preheated_gmgn_task or asyncio.create_task(
                get_gmgn_analytics(ca, mode="fast", priority="high", route="interactive"),
                name=f"GMGN_{ca[:6]}",
            )
            gmgn_task = safe_call(asyncio.shield(gmgn_live_task), 25, "GMGN")
            ix_task = safe_call(insightx_agent.fetch_deep_analysis(ca), 15, "InsightX") if use_insightx else _return_none()

            rug_data, bq_data, goplus_data, analytics, ix_data = await asyncio.gather(
                rug_task,
                bq_task,
                goplus_task,
                gmgn_task,
                ix_task,
            )

        analytics = analytics or {}
        late_gmgn_pending = False
        late_gmgn_task = None
        if not analytics and gmgn_live_task.done():
            try:
                analytics = gmgn_live_task.result() or {}
            except Exception as e:
                logger.warning("GMGN budget wait finished with error | ca=%s | err=%s", ca[:8], e)
                analytics = {}
        elif not analytics and not gmgn_live_task.done():
            late_gmgn_pending = True
        if not analytics:
            late_gmgn_pending = True
            if gmgn_live_task.done():
                late_gmgn_task = asyncio.create_task(
                    get_gmgn_analytics(ca, mode="full", priority="high", route="interactive"),
                    name=f"GMGNFollow_{ca[:6]}",
                )
        elif _gmgn_needs_followup(analytics):
            late_gmgn_pending = True
            if gmgn_live_task.done():
                late_gmgn_task = asyncio.create_task(
                    get_gmgn_analytics(ca, mode="full", priority="high", route="interactive"),
                    name=f"GMGNFollow_{ca[:6]}",
                )

        need_market_retry, retry_reason = _needs_market_retry(token_data)
        if need_market_retry:
            logger.info("启动二次行情补救: 重试 DexScreener")
            retry_market = await safe_call(get_market_data_force(ca), 5, "MarketRetry")
            if retry_market:
                token_data = _apply_retry_market_patch(token_data, retry_market)
                _log_liquidity_trace("market_retry_patch", ca, token_data)
                _log_strict_trace("retry_patch", ca, token_data)

        if use_stage2_followup:
            if token_data.get("is_honeypot"):
                token_data["risk_flags"] = token_data.get("risk_flags", []) + ["🚨 貔貅盘(GoPlus)"]
        else:
            if rug_data:
                token_data["is_burned"] = (_safe_float(rug_data.get("lp_burned_pct"), 0) > 95)
                token_data["is_locked"] = (_safe_float(rug_data.get("lp_locked_pct"), 0) > 95)

            if goplus_data and goplus_data.get("is_honeypot"):
                token_data["risk_flags"] = token_data.get("risk_flags", []) + ["🚨 貔貅盘(GoPlus)"]

        token_data = _apply_gmgn_analytics(token_data, analytics, patch_timeframes_only_when_missing=True)
        if str(token_data.get("token_image_source") or "").strip().lower() in {"gmgn/dom", "gmgn/meta"} and token_data.get("token_image_url"):
            fetcher._cache_gmgn_avatar(ca, token_data.get("token_image_url", ""), token_data.get("token_image_source", ""))
        _log_liquidity_trace("after_gmgn_analytics", ca, token_data)
        _log_safety_canonical_trace("after_gmgn_analytics", ca, token_data)
        token_data = _resolve_canonical_metrics(token_data, analytics, bq_data)
        token_data = _apply_top10_semantic_research(token_data, bq_data, token_data.get("top10_ratio_gmgn"))
        _apply_runtime_metadata(
            token_data,
            signal_state=_runtime_signal_state(ca, existing_terminal, existing_record),
            decision_action=token_data.get("decision_action") or ACTION_WATCH,
        )
        token_data["top10_pending_gmgn_review"] = _is_top10_pending_gmgn_review(token_data, late_gmgn_pending)
        if token_data["top10_pending_gmgn_review"]:
            logger.info(
                "Top10PendingGMGN | ca=%s | primary=%s | reason=%s",
                ca[:8],
                _top10_primary_source(token_data) or "NONE",
                _top10_conflict_reason(token_data) or "pending_review",
            )
        _log_liquidity_trace("after_canonical_metrics", ca, token_data)
        _log_strict_trace("canonical", ca, token_data)
        _log_safety_canonical_trace("after_canonical_metrics", ca, token_data)

        avatar_path = await safe_call(
            fetcher.ensure_token_avatar(ca, token_data.get("token_image_url", ""), token_data.get("token_image_source", "")),
            10,
            "AvatarCache",
        )
        if avatar_path:
            token_data["token_image_path"] = avatar_path

        analytics_for_ai = _build_analytics_for_ai(analytics, existing_terminal)
        if token_data.get("chart_screenshot") and not analytics_for_ai.get("screenshot"):
            analytics_for_ai["screenshot"] = token_data.get("chart_screenshot")

        curr_price = _safe_float(token_data.get("price_usd"), 0.0)
        curr_mcap = _safe_float(token_data.get("cap_usd"), 0.0)

        strat_res = detect_strategy(token_data)
        strategy_id = str(strat_res[0]) if isinstance(strat_res, tuple) else str(strat_res)
        config = strat_res[1] if isinstance(strat_res, tuple) else {}
        token_data["strategy_id"] = strategy_id

        if curr_price > 0:
            await tp_tracker.ensure_observing(
                ca,
                curr_price,
                anchor_price=_safe_float((existing_terminal or {}).get("entry_price"), curr_price) or curr_price,
                reply_chat_id=chat_id,
                reply_msg_id=message_id,
            )
            token_data["baseline"] = await tp_tracker.get_baseline_metrics(ca, current_price=curr_price)

        if ix_data:
            token_data["insightx"] = {
                "gini": ix_data.get("gini_coefficient"),
                "smart_money": ix_data.get("smart_money_count"),
                "is_bundled": ix_data.get("bundled_sniper"),
                "partial": ix_data.get("insightx_partial"),
                "rate_limited": ix_data.get("insightx_rate_limited"),
            }
            if ix_data.get("bundled_sniper"):
                token_data["risk_flags"] = token_data.get("risk_flags", []) + ["🚨 疑似老鼠仓(InsightX)"]

        if LGB_AVAILABLE and lgb_model:
            try:
                features = calculate_ml_features(token_data, analytics_for_ai or {}, {})
                ml_features_array = np.array([[
                    _safe_float(token_data.get("cap_usd"), 0),
                    _safe_float(get_decision_liquidity_usd(token_data), 0),
                    _safe_float(features.get("smart_money_delta"), 0),
                    _safe_float(features.get("maker_vol_ratio"), 0),
                    _safe_float(features.get("overhang_ratio"), 0),
                    _safe_float(features.get("breakout_vol_ratio"), 0),
                ]])

                win_prob = lgb_model.predict(ml_features_array)[0]
                token_data["lgb_win_prob"] = win_prob

                if win_prob > 0.85:
                    token_data["risk_flags"] = token_data.get("risk_flags", []) + [f"🎯 AI预测极高胜率 ({win_prob:.1%})"]
                elif win_prob < 0.20:
                    token_data["risk_flags"] = token_data.get("risk_flags", []) + [f"🗑️ AI预测极低胜率 ({win_prob:.1%})"]
            except Exception as e:
                logger.error(f"LightGBM 预测执行失败: {e}")

        temp_decision = {"verdict": ACTION_WATCH, "reason": "🧠 核心数据已就绪，AI 正在进行深度模型推演，请稍候..."}
        await update_user_message(chat_id=chat_id, message_id=message_id, ca=ca, token_data=token_data, decision=temp_decision)

        static_res = await safe_call(brain.analyze_static_narrative(token_data, analytics_for_ai), 90, "AI_Static") or {}

        stable_snapshot = _build_stable_snapshot(token_data, analytics_for_ai)
        terminal_states = {
            "ai_narrative": static_res.get("ai_narrative") or "静态样本不足，暂以盘面与筹码为主。",
            "ai_image_read": static_res.get("ai_image_read") or "头像/社交样本不足，暂不下视觉结论。",
            "entry_price": curr_price,
            "milestone_anchor_price": _safe_float((existing_terminal or {}).get("milestone_anchor_price"), _safe_float((existing_terminal or {}).get("entry_price"), curr_price)) or curr_price,
            "is_burned": token_data.get("is_burned"),
            "is_locked": token_data.get("is_locked"),
            "dex_paid": token_data.get("dex_paid"),
            "symbol": token_data.get("symbol", "UNK"),
            "token_image_url": token_data.get("token_image_url", ""),
            "token_image_path": token_data.get("token_image_path", ""),
            "cap_usd": token_data.get("cap_usd", 0),
            "liquidity_usd": token_data.get("liquidity_usd", 0),
            "pair_liquidity_usd": token_data.get("pair_liquidity_usd", 0),
            "exit_liquidity_usd": token_data.get("exit_liquidity_usd", 0),
            "top10_raw_pct": token_data.get("top10_raw_pct"),
            "top10_adjusted_pct": token_data.get("top10_adjusted_pct"),
            "metric_confidence": token_data.get("metric_confidence"),
            "source_conflict": token_data.get("source_conflict"),
            "canonical_stage": token_data.get("canonical_stage"),
            "canonical_metadata": token_data.get("canonical_metadata"),
            "top10_adjustment_semantics": token_data.get("top10_adjustment_semantics"),
            "top10_entity_adjusted": token_data.get("top10_entity_adjusted"),
            "decision_liquidity_source": token_data.get("decision_liquidity_source"),
            "decision_liquidity_enter_ready": token_data.get("decision_liquidity_enter_ready"),
            "top10_pending_gmgn_review": token_data.get("top10_pending_gmgn_review"),
            "signal_state": token_data.get("signal_state") or _runtime_signal_state(ca, existing_terminal, existing_record),
            "decision_action": token_data.get("decision_action") or ACTION_WATCH,
            "reply_chat_id": chat_id,
            "chart_screenshot": analytics_for_ai.get("screenshot", ""),
            "stable_snapshot": stable_snapshot,
        }
        terminal_states.update(_top10_research_terminal_patch(token_data))

        decision = _sanitize_top10_pending_reason(
            _sanitize_ai_reason_by_metrics(
                await safe_call(brain.analyze_dynamic_strategy(token_data, terminal_states, analytics_for_ai), 90, "AI_Dynamic") or {},
                token_data,
            ),
            token_data,
        )
        decision["verdict"] = _normalize_verdict(decision.get("verdict", ACTION_WATCH), ACTION_WATCH)
        decision, pos_info, _ = apply_final_gate(token_data, decision, None)
        token_data["decision_reason"] = decision.get("reason", "")
        decision, next_state = await _apply_execution_state_machine(
            ca,
            token_data,
            decision,
            strategy_id=strategy_id,
            strategy_config=config,
            current_price=curr_price,
            current_mcap=curr_mcap,
            chat_id=chat_id,
            message_id=message_id,
        )
        token_data["signal_state"] = next_state
        token_data["pos_info"] = pos_info
        if curr_price > 0:
            token_data["baseline"] = await tp_tracker.get_baseline_metrics(ca, current_price=curr_price)

        stable_snapshot = _build_stable_snapshot(token_data, analytics_for_ai)
        terminal_states.update(
            {
                "signal_state": next_state,
                "decision_action": decision.get("verdict"),
                "decision_reason": token_data.get("decision_reason"),
                "top10_pending_gmgn_review": token_data.get("top10_pending_gmgn_review"),
                "canonical_stage": token_data.get("canonical_stage"),
                "canonical_metadata": token_data.get("canonical_metadata"),
                "top10_adjustment_semantics": token_data.get("top10_adjustment_semantics"),
                "top10_entity_adjusted": token_data.get("top10_entity_adjusted"),
                "decision_liquidity_source": token_data.get("decision_liquidity_source"),
                "decision_liquidity_enter_ready": token_data.get("decision_liquidity_enter_ready"),
                "stable_snapshot": stable_snapshot,
            }
        )
        terminal_states.update(_top10_research_terminal_patch(token_data))

        try:
            await db.save_initial_signal(
                ca,
                "SYSTEM",
                terminal_states["milestone_anchor_price"],
                message_id,
                terminal_states,
                status=next_state,
            )
            await asyncio.wait_for(
                db.update_signal_analysis(
                    ca,
                    float(decision.get("score", 0)),
                    decision.get("reason", ""),
                    status=next_state,
                ),
                timeout=2.0,
            )
        except Exception as e:
            logger.error(f"保存初始状态失败: {e}")

        await update_user_message(chat_id=chat_id, message_id=message_id, ca=ca, token_data=token_data, decision=decision)
        if late_gmgn_pending:
            logger.info("LateGMGN | ca=%s | scheduled", ca[:8])
            spawn_task(
                _late_merge_gmgn_result(ca, late_gmgn_task or gmgn_live_task, chat_id, message_id),
                f"LateGMGN_{ca[:6]}",
            )
        spawn_task(evolve_database(ca, token_data, analytics or {}, ix_data or {}), f"EvolveDB_{ca[:6]}")

    except Exception as e:
        logger.exception(f"run_deep_analysis 异常: {e}")


async def evolve_database(ca: str, token_data: dict, gmgn_data: dict, ix_data: dict):
    try:
        mcap = token_data.get("cap_usd", 0)
        liq = get_decision_liquidity_usd(token_data)
        age = token_data.get("token_age_min", 0)
        holders = {
            "top10_raw_pct": token_data.get("top10_raw_pct"),
            "top10_adjusted_pct": get_confirmed_top10_pct(token_data),
            "bitquery_holders_count": token_data.get("bitquery_holders_count"),
            "top10_raw_pct_self": token_data.get("top10_raw_pct_self"),
            "top10_owner_pct_self": token_data.get("top10_owner_pct_self"),
            "top10_effective_pct_self": token_data.get("top10_effective_pct_self"),
            "top10_effective_value_usd_self": token_data.get("top10_effective_value_usd_self"),
            "top1_effective_pct_self": token_data.get("top1_effective_pct_self"),
            "top1_effective_value_usd_self": token_data.get("top1_effective_value_usd_self"),
            "top10_holder_count_raw_self": token_data.get("top10_holder_count_raw_self"),
            "top10_holder_count_owner_self": token_data.get("top10_holder_count_owner_self"),
            "top10_holder_count_effective_self": token_data.get("top10_holder_count_effective_self"),
            "top10_semantic_suspect": token_data.get("top10_semantic_suspect"),
            "top10_semantic_suspect_reason": token_data.get("top10_semantic_suspect_reason"),
            "top10_bitquery_gap_vs_effective_self": token_data.get("top10_bitquery_gap_vs_effective_self"),
            "top10_bitquery_gap_vs_late_gmgn": token_data.get("top10_bitquery_gap_vs_late_gmgn"),
            "top10_effective_gap_vs_late_gmgn": token_data.get("top10_effective_gap_vs_late_gmgn"),
            "top10_late_merge_supported_by_selfcalc": token_data.get("top10_late_merge_supported_by_selfcalc"),
            "top10_late_merge_support_gap": token_data.get("top10_late_merge_support_gap"),
            "top10_calc_method_self": token_data.get("top10_calc_method_self"),
            "top10_exclusion_summary_self": token_data.get("top10_exclusion_summary_self"),
            "late_gmgn_merge_blocked": token_data.get("late_gmgn_merge_blocked"),
            "late_gmgn_merge_block_reason": token_data.get("late_gmgn_merge_block_reason"),
            "late_gmgn_top10_history": token_data.get("late_gmgn_top10_history"),
            "late_gmgn_top10_history_count": token_data.get("late_gmgn_top10_history_count"),
            "late_gmgn_top10_last_value": token_data.get("late_gmgn_top10_last_value"),
            "late_gmgn_top10_min_value": token_data.get("late_gmgn_top10_min_value"),
            "late_gmgn_top10_max_value": token_data.get("late_gmgn_top10_max_value"),
            "pair_liquidity_usd": token_data.get("pair_liquidity_usd"),
            "exit_liquidity_usd": token_data.get("exit_liquidity_usd"),
            "metric_confidence": token_data.get("metric_confidence"),
            "source_conflict": token_data.get("source_conflict"),
            "canonical_stage": token_data.get("canonical_stage"),
            "canonical_metadata": token_data.get("canonical_metadata"),
            "top10_adjustment_semantics": token_data.get("top10_adjustment_semantics"),
            "top10_entity_adjusted": token_data.get("top10_entity_adjusted"),
            "source": token_data.get("top10_ratio_source") or "",
        }

        await db.execute("""
            INSERT INTO golden_dog_morphology 
            (
                ca, snapshot_time, token_age_mins_at_snap, market_cap_at_snap, liquidity_at_snap,
                top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                metric_confidence, source_conflict, holder_distribution, social_signal
            )
            VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11, $12)
            ON CONFLICT (ca, snapshot_time) DO NOTHING
        """,
            ca,
            age,
            mcap,
            liq,
            token_data.get("top10_raw_pct"),
            get_confirmed_top10_pct(token_data),
            token_data.get("pair_liquidity_usd"),
            token_data.get("exit_liquidity_usd"),
            json.dumps(token_data.get("metric_confidence")) if isinstance(token_data.get("metric_confidence"), dict) else None,
            json.dumps(token_data.get("source_conflict")) if isinstance(token_data.get("source_conflict"), dict) else None,
            json.dumps(holders),
            json.dumps({"ix_data": ix_data}),
        )

        top_holders = gmgn_data.get("top_holders_detail", []) if gmgn_data else []
        for holder in top_holders:
            addr = holder.get("address")
            tags = holder.get("tags", [])
            if addr and tags and any(t in tags for t in ["Smart Money", "KOL", "Sniper", "Dev"]):
                await db.execute("""
                    INSERT INTO smart_wallet_intel (wallet_address, tags, total_trades, avg_entry_mcap)
                    VALUES ($1, $2, 1, $3)
                    ON CONFLICT (wallet_address) DO UPDATE 
                    SET last_active = NOW(), total_trades = smart_wallet_intel.total_trades + 1
                """, addr, json.dumps(tags), mcap)

        clusters = ix_data.get("clusters", []) if ix_data else []
        for cluster in clusters:
            cluster_id = cluster.get("cluster_id", "UNK")
            wallets = cluster.get("wallets", [])
            for w in wallets:
                await db.execute("""
                    INSERT INTO wallet_clusters (cluster_id, wallet_address, discovered_in_token, behavior_tag, risk_level, total_wallets_in_cluster)
                    VALUES ($1, $2, $3, $4, 8, $5)
                    ON CONFLICT (cluster_id, wallet_address) DO NOTHING
                """, str(cluster_id), str(w), ca, "SUSPICIOUS_CLUSTER", len(wallets))

    except Exception as e:
        logger.error(f"🧬 数据库进化失败: {e}")


async def price_monitor_loop():
    logger.info("🕵️‍♂️ 价格及里程碑监控服务已启动... (Jupiter 主查价 + Dex 兜底)")
    while True:
        try:
            await asyncio.sleep(1.5)
            for ca, pos in list(tp_tracker.data.items()):
                if str(pos.get("status", "")).upper() != "ACTIVE":
                    continue

                try:
                    price_res = await fetcher.get_price_only(ca)
                    price_f = price_res[0] if isinstance(price_res, tuple) else float(price_res)
                    mcap_f = price_res[1] if isinstance(price_res, tuple) else 0.0
                except Exception:
                    continue

                if price_f <= 0:
                    continue

                await tp_tracker.observe_price(ca, price_f)
                paper_portfolio_engine.mark_price(ca, price_f, mcap_f)

                event_dict = await tp_tracker.update(ca, price_f, curr_mcap=mcap_f)
                if event_dict and isinstance(event_dict, dict):
                    event_type = event_dict.get("event")
                    t_chat_id = pos.get("reply_chat_id")
                    t_msg_id = pos.get("reply_msg_id")

                    if event_type == "MILESTONE":
                        if t_chat_id and t_msg_id:
                            mult = event_dict.get("multiplier")
                            pnl = event_dict.get("pnl", 0.0)

                            img_path = await asyncio.to_thread(
                                generate_milestone_image,
                                symbol="TOKEN",
                                mcap=mcap_f,
                                multiplier=mult,
                                ca=ca,
                            )
                            if img_path:
                                if hasattr(tp_tracker, "update_custom_image"):
                                    await tp_tracker.update_custom_image(ca, img_path)
                                else:
                                    tp_tracker.data[ca]["custom_image"] = img_path
                                    await tp_tracker._save()

                            report_text = (
                                f"🚀 <b>里程碑突破战报</b>\n\n"
                                f"🎉 代币: <code>{ca}</code>\n"
                                f"📈 当前倍数: <b>{mult}x</b>\n"
                                f"💰 实时收益: <b>{pnl:+.1f}%</b>\n\n"
                                f"AI 持续监控中，利润正在奔跑。"
                            )
                            await send_thread_reply(t_chat_id, t_msg_id, report_text)
                            await refresh_token_panel(ca, t_chat_id, t_msg_id, force_deep=False)

                    elif event_type in ["CLOSED_TP", "CLOSED_SL"]:
                        strategy_id = pos.get("strategy_id", "DEFAULT")
                        pnl_pct = event_dict.get("pnl_percentage", 0.0)

                        stats_engine.record(
                            strategy=strategy_id,
                            result_type=event_type,
                            pnl_percent=pnl_pct,
                            ca=ca,
                        )

                        paper_ret = _paper_portfolio_call("on_final_close", ca, price_f, mcap_f, reason=event_type)
                        if paper_ret.get("ok"):
                            logger.info(
                                f"📒 PaperPortfolio 平仓成功: {ca[:6]}... | reason={event_type} | "
                                f"net_pnl={paper_ret.get('net_pnl_sol')} SOL | cash={paper_ret.get('cash_sol')} SOL"
                            )

                        if t_chat_id and t_msg_id:
                            if event_type == "CLOSED_SL":
                                report_text = (
                                    f"🛑 <b>铁血止损触发</b>\n\n"
                                    f"代币: <code>{ca}</code>\n"
                                    f"操作: <b>市价清仓</b>\n"
                                    f"最终盈亏: <b>{pnl_pct:+.2f}%</b>\n"
                                    f"说明: 留得青山在，不怕没柴烧。"
                                )
                            else:
                                report_text = (
                                    f"🎯 <b>完美止盈落袋</b>\n\n"
                                    f"代币: <code>{ca}</code>\n"
                                    f"操作: <b>全量获利了结</b>\n"
                                    f"最终盈亏: <b>{pnl_pct:+.2f}%</b>\n"
                                    f"说明: 恭喜猎手，利润已安全入库。"
                                )

                            await send_thread_reply(t_chat_id, t_msg_id, report_text)

                    elif str(event_type).startswith("止盈"):
                        pnl_pct = event_dict.get("pnl", 0.0)
                        paper_ret = _paper_portfolio_call("on_tp_event", ca, price_f, mcap_f, str(event_type))
                        if paper_ret.get("ok"):
                            logger.info(
                                f"📒 PaperPortfolio 部分止盈: {ca[:6]}... | {event_type} | "
                                f"net_pnl={paper_ret.get('net_pnl_sol')} SOL | cash={paper_ret.get('cash_sol')} SOL"
                            )

                        if t_chat_id and t_msg_id:
                            report_text = (
                                f"💸 <b>阶段止盈触发</b>\n\n"
                                f"代币: <code>{ca}</code>\n"
                                f"进度: <b>{event_type}</b>\n"
                                f"当前收益: <b>{pnl_pct:+.2f}%</b>\n"
                                f"说明: 已抛售部分仓位锁定利润，剩余仓位继续博取更高倍数。"
                            )
                            await send_thread_reply(t_chat_id, t_msg_id, report_text)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"💥 价格监控主循环发生系统级异常: {e}", exc_info=True)
            await asyncio.sleep(2.0)


async def refresh_token_panel(ca: str, chat_id: int, message_id: int, force_deep: bool = True):
    raw_market, helius_sec = await asyncio.gather(
        safe_call(get_market_data(ca), 12, "Market"),
        safe_call(get_helius_security(ca), 12, "Helius"),
    )

    existing_record = await db.get_signal_snapshot(ca)
    existing_terminal = existing_record.get("terminal_states", {}) if existing_record else {}

    token_data = normalize_token_data(ca, raw_market or {}, "REFRESH", chat_id, message_id)
    token_data = _merge_existing_terminal(token_data, existing_terminal)
    token_data = _ensure_runtime_token_ca(token_data, ca)
    token_data = _apply_helius_security(token_data, helius_sec)
    token_data = _resolve_canonical_metrics(token_data, None, None)
    _apply_runtime_metadata(
        token_data,
        signal_state=_runtime_signal_state(ca, existing_terminal, existing_record),
        decision_action=token_data.get("decision_action") or existing_terminal.get("decision_action") or ACTION_WATCH,
    )

    pos = tp_tracker.data.get(ca, {})
    if pos.get("custom_image") and os.path.exists(pos.get("custom_image")):
        token_data["token_image_path"] = pos.get("custom_image")
        token_data["token_image_url"] = ""

    curr_price = _safe_float(token_data.get("price_usd"), 0.0)

    if curr_price > 0 and pos and not (
        _safe_float(pos.get("entry"), 0.0) == 0.0
        and str(pos.get("strategy_id", "")).upper() in {"", "UNKNOWN", "UNK"}
        and str(pos.get("status", "")).upper() == "OBSERVE"
    ):
        await tp_tracker.observe_price(ca, curr_price)
        token_data["baseline"] = await tp_tracker.get_baseline_metrics(ca, current_price=curr_price)

    await update_user_message(chat_id, message_id, ca, token_data, {"verdict": "REFRESH", "reason": "刷新中..."})
    if force_deep:
        spawn_task(run_deep_analysis(ca, token_data, message_id, chat_id, use_insightx=False), f"RefreshDeep_{ca[:6]}")


async def main():
    logger.info("🚀 SolanaHunter V3.6 核心引擎与安全网启动...")

    try:
        pp_summary = paper_portfolio_engine.summary()
        logger.info(
            "📒 PaperPortfolio 已加载: "
            f"cash={pp_summary.get('cash_sol')} SOL | "
            f"equity={pp_summary.get('equity_sol')} SOL | "
            f"open={pp_summary.get('open_positions')} | "
            f"closed={pp_summary.get('closed_trades')} | "
            f"roi={pp_summary.get('roi_pct')}%"
        )
    except Exception as e:
        logger.warning(f"⚠️ PaperPortfolio 启动摘要读取失败: {e}")

    try:
        from modules.commander import dp
        from modules.notifier import refresh_router
        dp.include_router(refresh_router)
        dp.include_router(main_router)
    except Exception as e:
        logger.error(f"路由注册异常: {e}")

    logger.info("⏳ 正在预热双 Fetcher 浏览器环境...")
    warmup_status = await prepare_fetcher_profiles()
    interactive_status = warmup_status.get("interactive", {}) if isinstance(warmup_status, dict) else {}
    background_status = warmup_status.get("background", {}) if isinstance(warmup_status, dict) else {}
    interactive_ready = bool(interactive_status.get("ready"))
    background_ready = bool(background_status.get("ready"))
    if interactive_ready and background_ready:
        logger.info("✅ 双 Fetcher 浏览器环境预热完成。")
    else:
        logger.warning(
            "⚠️ 双 Fetcher 浏览器环境预热部分失败: interactive_ready=%s | interactive_state=%s | interactive_blocked=%s | background_ready=%s | background_state=%s | background_blocked=%s",
            interactive_ready,
            interactive_status.get("active_state") or interactive_status.get("initial_state") or "",
            interactive_status.get("blocked_reason") or "",
            background_ready,
            background_status.get("active_state") or background_status.get("initial_state") or "",
            background_status.get("blocked_reason") or "",
        )
    await db.init_pool()

    try:
        try:
            from modules.watchdog import time_series_patrol_loop
            spawn_task(time_series_patrol_loop(), "WatchdogPatrol")
        except ImportError:
            pass

        spawn_task(_avatar_enrichment_loop(), "AvatarEnrichmentLoop")
        spawn_task(price_monitor_loop(), "PriceMonitorLoop")

        try:
            await start_listener(process_new_signal, refresh_token_panel, trigger_deep_ai_report)
        except TypeError:
            await start_listener(process_new_signal, refresh_token_panel)

    except asyncio.CancelledError:
        logger.info("🛑 收到内部取消信号...")
    except Exception as e:
        logger.exception(f"💥 主程序运行时发生致命错误: {e}")
    finally:
        logger.info("🧹 正在执行全局优雅停机 (Graceful Shutdown)...")
        if fetcher:
            try:
                logger.info("⏳ 正在释放双 Fetcher 浏览器资源...")
                await close_fetchers()
                logger.info("✅ 爬虫与无头浏览器已安全关闭。")
            except Exception as e:
                logger.error(f"关闭爬虫资源时出错: {e}")

        try:
            closer = getattr(insightx_agent, "close", None) or getattr(insightx_agent, "aclose", None)
            if closer:
                r = closer()
                if asyncio.iscoroutine(r):
                    await r
                logger.info("✅ InsightX 客户端已安全关闭。")
        except Exception as e:
            logger.error(f"关闭 InsightX 资源时出错: {e}")

        try:
            paper_portfolio_engine.save()
            logger.info("✅ PaperPortfolio 状态已安全保存。")
        except Exception as e:
            logger.error(f"关闭 PaperPortfolio 资源时出错: {e}")

        if db:
            try:
                await db.close_pool()
                logger.info("✅ 数据库连接池已安全释放。")
            except Exception as e:
                logger.error(f"关闭数据库资源时出错: {e}")

        logger.info("👋 资源清理完成，主程序安全退出。")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 已收到终止命令，开始断开系统连接...")
