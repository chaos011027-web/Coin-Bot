# modules/risk_engine.py
from typing import List, Tuple, Dict, Any, Optional


# ===========================
# 🟢 原有：策略风险等级（供 performance panel）
# ===========================
def get_risk_level(win_rate: float, r_ratio: float) -> dict:
    """
    注意：保留原有逻辑/接口，notifier.performance_panel 依赖它。
    """
    try:
        win_rate = float(win_rate or 0)
        r_ratio = float(r_ratio or 0)
    except Exception:
        win_rate = 0
        r_ratio = 0

    if win_rate >= 60 and r_ratio >= 0.5:
        return {"level": "低风险", "color": "🟢"}
    if win_rate >= 45:
        return {"level": "中风险", "color": "🟡"}
    return {"level": "高风险", "color": "🔴"}


# ===========================
# 🧰 Helpers
# ===========================
def _safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None or x == "":
            return default
        if isinstance(x, str):
            x = x.replace(",", "").strip()
        return int(float(x))
    except Exception:
        return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        if isinstance(x, str):
            x = x.replace(",", "").strip().replace("%", "")
        return float(x)
    except Exception:
        return default


def _uniq_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        if not it:
            continue
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


def _normalize_flag(s: str) -> str:
    s = (s or "").strip().upper()
    if not s:
        return ""
    # 常见无意义标签过滤
    if s in {"NONE", "PASS", "AI_ERROR"}:
        return ""
    return s


# ===========================
# 🧱 Risk Flags 聚合（机器旗标 + 展示提示）
# ===========================
def build_risk_flags_final(
    token_data: Dict[str, Any],
    decision: Optional[Dict[str, Any]] = None,
    score_data: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], List[str]]:
    """
    统一风险来源，输出：
    - risk_flags_final: 机器可用（用于风控/统计/阈值）
    - risk_hints_final: 人类可读（用于 Notifier 展示）
    """
    token_data = token_data or {}
    decision = decision or {}
    score_data = score_data or {}

    flags: List[str] = []
    hints: List[str] = []

    # --- 1) GMGN 结构化字段 ---
    gmgn_rat = _safe_int(token_data.get("gmgn_rat", 0))
    gmgn_bundle = _safe_int(token_data.get("gmgn_bundle", 0))
    gmgn_sniper = _safe_int(token_data.get("gmgn_sniper", 0))

    if gmgn_rat > 0:
        flags.append("RAT_FARM")
        hints.append(f"🐀老鼠仓x{gmgn_rat}")
    if gmgn_bundle >= 50:
        flags.append("BUNDLE_HIGH")
        hints.append(f"📦捆绑偏高({gmgn_bundle})")
    if gmgn_sniper >= 80:
        flags.append("SNIPER_MANY")
        hints.append(f"🔫狙击过多({gmgn_sniper})")

    # --- 2) Top10 / 流动性 / 市值（来自 token_data）---
    top10 = _safe_float(token_data.get("top10_ratio", 0))
    liq = _safe_float(token_data.get("liquidity_usd", 0))
    mcap = _safe_float(token_data.get("cap_usd") or token_data.get("mcap") or token_data.get("fdv") or 0)

    if top10 >= 60:
        flags.append("HIGH_CONCENTRATION_FATAL")
        hints.append(f"⛔Top10控盘{top10:.1f}%")
    elif top10 >= 50:
        flags.append("HIGH_CONCENTRATION")
        hints.append(f"⚠️Top10控盘{top10:.1f}%")

    # 极低流动性：只做提示（最终是否熔断由 FinalGate 决定）
    if liq > 0 and liq < 800:
        flags.append("LOW_LIQ_FATAL")
        hints.append(f"⛔流动性极低(${int(liq)})")
    elif liq > 0 and liq < 2000:
        flags.append("LOW_LIQ")
        hints.append(f"⚠️流动性偏低(${int(liq)})")

    # 池子占比异常
    if mcap > 100_000 and liq > 0:
        ratio = liq / mcap
        if ratio < 0.01:
            flags.append("LIQ_RATIO_LT_1PCT")
            hints.append("⛔池子占比<1%")

    # --- 3) AI 风险旗标（只能追加）---
    ai_flags = decision.get("risk_flags", [])
    if isinstance(ai_flags, list):
        for f in ai_flags:
            nf = _normalize_flag(str(f))
            if nf:
                flags.append(nf)
                hints.append(f"🤖{nf}")

    # --- 4) ScoreEngine 的 summary/breakdown（做兜底提取）---
    # score_engine 的 breakdown/summary 是你结构化评分的真实依据之一
    summary = str(score_data.get("summary") or "")
    breakdown = score_data.get("breakdown")
    # summary 里出现关键词就补一个提示（不强制作为 fatal）
    if "池子太薄" in summary:
        flags.append("THIN_LIQ")
        hints.append("⚠️池子太薄")
    if "市值过低" in summary:
        flags.append("LOW_MCAP")
        hints.append("⚠️市值过低")

    # breakdown 如果是 dict: {item: score_delta} 或 list，都尽量容错
    if isinstance(breakdown, dict):
        for k, v in breakdown.items():
            k = str(k)
            vv = _safe_float(v, 0)
            if vv <= -15:
                hints.append(f"⚠️{k}")
    elif isinstance(breakdown, list):
        for it in breakdown:
            s = str(it)
            if s:
                hints.append(f"⚠️{s}")

    flags = _uniq_keep_order([f for f in flags if f])
    hints = _uniq_keep_order([h for h in hints if h])

    return flags, hints


# ===========================
# 🔥 FinalGate：最终裁决层（不改“信息”，只改“权限”）
# ===========================
def apply_final_gate(
    token_data: Dict[str, Any],
    decision: Optional[Dict[str, Any]],
    pos_info: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """
    输入: token_data, AI decision, pos_info
    输出: (decision, pos_info, fatal_risks_hints)

    设计原则：
    - 不影响已有功能：不依赖外部模块，不改变 token_data 的结构要求
    - 不否定 AI：保留 reason/score 作为“信息”
    - 但当触发红线：限制行为（PASS/仓位0/熔断标记）
    """
    token_data = token_data or {}
    decision = decision or {"score": 0, "verdict": "PASS", "risk_flags": [], "reason": "AI异常/缺失"}
    pos_info = pos_info or {"size": "0%", "level": "未知", "reason": "无"}

    fatal_hints: List[str] = []

    # 取硬指标（类型安全）
    rat_count = _safe_int(token_data.get("gmgn_rat", 0))
    top10 = _safe_float(token_data.get("top10_ratio", 0))
    liq = _safe_float(token_data.get("liquidity_usd", 0))
    mcap = _safe_float(token_data.get("cap_usd") or token_data.get("mcap") or token_data.get("fdv") or 0)

    # 红线 A：老鼠仓（结构化字段 >0 直接熔断）
    if rat_count > 0:
        fatal_hints.append(f"老鼠仓x{rat_count}")

    # 红线 B：Top10 极度控盘（>=60 熔断，50-60 强限权）
    strong_limit = False
    if top10 >= 60.0:
        fatal_hints.append(f"Top10控盘{top10:.1f}%")
    elif top10 >= 50.0:
        strong_limit = True

    # 红线 C：极低流动性（<800 熔断；800-2000 强限权）
    if liq > 0 and liq < 800:
        fatal_hints.append(f"流动性过低(${int(liq)})")
    elif liq > 0 and liq < 2000:
        strong_limit = True

    # 红线 D：大市值微池子（结构异常，倾向熔断）
    if mcap > 100_000 and liq > 0 and (liq / mcap) < 0.01:
        fatal_hints.append("池子占比<1%")

    # GMGN：捆绑/狙击极端时（不直接熔断，强限权）
    bundle = _safe_int(token_data.get("gmgn_bundle", 0))
    sniper = _safe_int(token_data.get("gmgn_sniper", 0))
    if bundle >= 120 or sniper >= 120:
        strong_limit = True

    # === 执行裁决 ===
    if fatal_hints:
        # 熔断：覆盖行为
        decision["verdict"] = "PASS"
        decision["reason"] = f"【风控拦截】触发红线: {', '.join(fatal_hints)}"

        pos_info["size"] = "0%"
        pos_info["level"] = "⛔ 熔断"
        pos_info["reason"] = "触发FinalGate风控拦截"

        return decision, pos_info, fatal_hints

    if strong_limit:
        # 强限权：不熔断，但禁止 BUY + 仓位上限
        if str(decision.get("verdict", "")).upper() == "BUY":
            decision["verdict"] = "WATCH"
            # 保留原 reason，同时追加说明
            old_reason = str(decision.get("reason") or "").strip()
            suffix = "【风控限权】结构风险偏高，禁止BUY"
            decision["reason"] = (old_reason + "｜" + suffix) if old_reason else suffix

        # 仓位上限：如果原本是高仓位，压到 0-1%
        pos_info["size"] = "0-1%"
        pos_info["level"] = "⚠️ 风控限权"
        old_pr = str(pos_info.get("reason") or "").strip()
        pos_info["reason"] = (old_pr + "｜" + "结构风险偏高") if old_pr else "结构风险偏高"

    return decision, pos_info, fatal_hints
