import os
import re
import json
import logging
import asyncio
import base64
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from modules.canonical_metrics import (
    canonical_pipeline_settings,
    canonical_thresholds,
    get_canonical_stage,
    get_confirmed_top10_pct,
    get_decision_liquidity_context,
    get_decision_liquidity_usd,
)

try:
    from modules.vision import analyze_chart as gemini_analyze_chart
except Exception:
    gemini_analyze_chart = None

logger = logging.getLogger("Brain")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")

DEFAULT_DECISION: Dict[str, Any] = {
    "score": 0,
    "verdict": "PASS",
    "risk_flags": ["AI_ERROR"],
    "reason": "AI不可用或返回异常",
    "ai_entry": "",
    "ai_exit": "",
    "ai_narrative": "",
    "ai_image_read": "",
    "ai_chart_read": "",
}

ALLOWED_VERDICTS = {"PASS", "WATCH", "PROBE", "ENTER", "EXIT"}
VERDICT_ALIASES = {
    "BUY": "ENTER",
    "SELL": "EXIT",
    "HOLD": "WATCH",
}
TRUSTED_TOP10_SOURCES = {"BITQUERY", "GMGN"}


# ===========================
# Algo Scoring (fallback)
# ===========================
def _to_int(x: Any) -> int:
    try:
        return int(float(x))
    except Exception:
        return 0


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        if isinstance(x, str):
            x = x.replace(",", "").strip().replace("$", "")
            if x.endswith("%"):
                x = x[:-1].strip()
        v = float(x)
        if v != v or v in (float("inf"), float("-inf")):
            return default
        return v
    except Exception:
        return default


def _is_trusted_top10_source(src: Any) -> bool:
    return str(src or "").upper() in TRUSTED_TOP10_SOURCES


def _normalize_verdict(verdict: Any, default: str = "WATCH") -> str:
    text = str(verdict or default).upper().strip()
    text = VERDICT_ALIASES.get(text, text)
    return text if text in ALLOWED_VERDICTS else default


def _top10_pending_gmgn_review(token_data: dict) -> bool:
    return bool((token_data or {}).get("top10_pending_gmgn_review"))


def _get_trusted_top10_value(token_data: dict) -> Optional[float]:
    if _top10_pending_gmgn_review(token_data):
        return None
    return get_confirmed_top10_pct(token_data)


def _get_trusted_top10_text(token_data: dict) -> str:
    if _top10_pending_gmgn_review(token_data):
        return "待校正"
    val = _get_trusted_top10_value(token_data)
    return f"{val:.1f}%" if val is not None else "未知"


def calc_algo_score(token_data: dict) -> Dict[str, Any]:
    """
    只作为 AI 不可用时兜底：稳健 > 激进
    Top10 只在可信来源(BITQUERY/GMGN)下参与评分。
    """
    td = token_data or {}
    thresholds = canonical_thresholds()

    mcap = _to_float(td.get("cap_usd") or td.get("mcap") or td.get("fdv"))
    liq = _to_float(get_decision_liquidity_usd(td))
    vol = _to_float(td.get("volume_h24"))

    sniper = _to_int(td.get("gmgn_sniper"))
    rat = _to_int(td.get("gmgn_rat"))
    bundle = _to_int(td.get("gmgn_bundle"))
    smart = _to_int(td.get("gmgn_smart"))
    dev = _to_int(td.get("gmgn_dev"))

    t10 = _get_trusted_top10_value(td)
    mint_present = td.get("mint_authority_present")
    freeze_present = td.get("freeze_authority_present")
    non_honeypot = td.get("non_honeypot")
    liq_locked = td.get("liquidity_locked")
    if liq_locked is None:
        liq_locked = td.get("is_locked")
    dex_paid = td.get("dex_paid")

    score = 50
    risks: List[str] = []
    details: List[str] = []
    top10_pending = _top10_pending_gmgn_review(td)

    if top10_pending:
        details.append("Top10待校正")
    elif t10 is not None:
        if t10 >= _to_float(thresholds.get("top10_fatal_pct", 60.0)):
            score -= 25
            risks.append("TOP10_60")
            details.append(f"Top10 {t10:.1f}%")
        elif t10 >= _to_float(thresholds.get("top10_danger_pct", 50.0)):
            score -= 12
            risks.append("TOP10_50")
            details.append(f"Top10 {t10:.1f}%")
        else:
            score += 4
            details.append(f"Top10 {t10:.1f}%")

    if mint_present is True:
        score -= 10
        risks.append("MINT_ON")
        details.append("Mint未丢弃")
    elif mint_present is False:
        score += 3
        details.append("Mint已丢弃")

    if freeze_present is True:
        score -= 10
        risks.append("FREEZE_ON")
        details.append("Freeze未丢弃")
    elif freeze_present is False:
        score += 3
        details.append("Freeze已丢弃")

    if non_honeypot is False:
        score -= 18
        risks.append("HONEY")
        details.append("疑似貔貅")
    elif non_honeypot is True:
        score += 2
        details.append("非貔貅")

    if liq_locked is True:
        score += 3
        details.append("流动性锁定")
    elif liq_locked is False:
        score -= 4
        risks.append("NO_LOCK")
        details.append("未锁定")

    if dex_paid is True:
        score += 2
        details.append("Dex付费")
    elif dex_paid is False:
        score -= 1
        details.append("Dex未付费")

    if 0 < mcap < 5_000_000:
        score += 4
        details.append("小市值")

    if 0 < liq < _to_float(thresholds.get("liquidity_warn_usd", 5000.0)):
        score -= 8
        risks.append("LOW_LIQ")
        details.append("流动性偏低")

    if vol > 0 and liq > 0 and (vol / max(liq, 1)) > 5:
        score += 3
        details.append("成交活跃")

    if sniper >= 20:
        score -= 8
        risks.append("SNIPER")
        details.append(f"狙击{sniper}")

    if rat >= 10:
        score -= 12
        risks.append("RAT")
        details.append(f"老鼠仓{rat}")

    if bundle >= 10:
        score -= 8
        risks.append("BUNDLE")
        details.append(f"捆绑{bundle}")

    if dev >= 1:
        score -= 4
        risks.append("DEV_TAG")
        details.append(f"Dev标签{dev}")

    if smart >= 5:
        score += 2
        details.append(f"聪明钱{smart}")

    score = max(0, min(100, int(score)))
    if not risks:
        risks = ["NONE"]

    return {
        "score": score,
        "risk_flags": risks,
        "details": "；".join(details[:8]) if details else "—",
    }


# ===========================
# Brain
# ===========================
class Brain:
    def __init__(self):
        self.client: Optional[AsyncOpenAI] = None
        self.oai_client: Optional[AsyncOpenAI] = None
        self.xai_client: Optional[AsyncOpenAI] = None

        if DEEPSEEK_API_KEY:
            try:
                self.client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
                logger.info("✅ DeepSeek 董事长已就位")
            except Exception as e:
                logger.error(f"❌ DeepSeek 初始化失败: {e}")

        if OPENAI_API_KEY:
            try:
                self.oai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
                logger.info("✅ OpenAI 视觉分析师已就位")
            except Exception as e:
                logger.error(f"❌ OpenAI 初始化失败: {e}")

        if XAI_API_KEY:
            try:
                self.xai_client = AsyncOpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
                logger.info("✅ Grok 情报局长已就位")
            except Exception as e:
                logger.error(f"❌ Grok 初始化失败: {e}")

    # ---------------------------
    # utils
    # ---------------------------
    def _safe_str(self, x: Any, n: int = 160) -> str:
        s = "" if x is None else str(x)
        s = s.replace("\u0000", "").strip()
        return s[:n] if len(s) > n else s

    def _extract_outer_json_object(self, text: str) -> Optional[str]:
        if not text:
            return None
        text = text.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        m = re.search(r"\{[\s\S]*\}", text)
        return m.group(0) if m else None

    def _fix_common_json_issues(self, s: str) -> str:
        s = (s or "").strip()
        s = re.sub(r",\s*}", "}", s)
        s = re.sub(r",\s*]", "]", s)
        return s

    def _encode_image(self, image_path: str) -> str:
        if not image_path or not os.path.exists(image_path):
            return ""
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
        except Exception:
            return ""

    # ---------------------------
    # multimodal sub-agents
    # ---------------------------
    async def _analyze_avatar(self, path: str, symbol: str, url: str = "") -> str:
        """
        头像 / 静态视觉分析
        优先使用本地落盘图；若本地图不存在，则回退到远程 URL。
        """
        if not self.oai_client:
            return "未启用视觉或无头像"

        image_payload = None
        img = self._encode_image(path)
        if img:
            image_payload = {"url": f"data:image/jpeg;base64,{img}"}
        else:
            remote = str(url or "").strip()
            if remote.startswith("http://") or remote.startswith("https://"):
                image_payload = {"url": remote}

        if not image_payload:
            return "未启用视觉或无头像"

        try:
            res = await self.oai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"代币 {symbol} 的头像，是一眼假的劣质图，还是高质量/魔性原创图？用一句简短的话评价。",
                            },
                            {
                                "type": "image_url",
                                "image_url": image_payload,
                            },
                        ],
                    }
                ],
            )
            return self._safe_str(res.choices[0].message.content, 80) or "头像分析为空"
        except Exception as e:
            logger.error(f"头像分析异常: {e}")
            return "头像分析报错"

    async def _analyze_chart_openai(self, path: str) -> str:
        if not self.oai_client or not path:
            return "未启用 OpenAI K线分析"

        img = self._encode_image(path)
        if not img:
            return "K线截图读取失败"

        try:
            res = await self.oai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "作为顶级交易员，一句话分析这张 Dex K线图：处于拉升初盘、洗盘诱空还是典型的暴跌画门？",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{img}"},
                            },
                        ],
                    }
                ],
            )
            return self._safe_str(res.choices[0].message.content, 120) or "OpenAI K线分析为空"
        except Exception as e:
            logger.error(f"OpenAI K线分析异常: {e}")
            return "OpenAI K线分析报错"

    async def _analyze_chart(self, path: str) -> str:
        """
        动态 K线分析
        -> 正确接入 vision.py，作为第二意见引擎
        """
        if not path:
            return "暂无最新K线图"

        tasks = [self._analyze_chart_openai(path)]
        if gemini_analyze_chart:
            tasks.append(gemini_analyze_chart(path))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        openai_res = ""
        gemini_res = ""

        if len(results) >= 1 and not isinstance(results[0], Exception):
            openai_res = self._safe_str(results[0], 120)

        if len(results) >= 2 and not isinstance(results[1], Exception):
            gemini_res = self._safe_str(results[1], 120)

        if openai_res and gemini_res:
            return f"OpenAI:{openai_res} | Gemini:{gemini_res}"
        if openai_res:
            return openai_res
        if gemini_res:
            return gemini_res

        return "K线分析不可用"

    async def _analyze_social(self, symbol: str) -> str:
        if not self.xai_client:
            return "未启用 Grok"
        try:
            res = await self.xai_client.chat.completions.create(
                model="grok-3-mini",
                messages=[
                    {"role": "system", "content": "你是最懂 Crypto X (推特) 文化的 Degen。"},
                    {
                        "role": "user",
                        "content": f"代币名称: {symbol}。用一句极简的 Crypto 黑话评判它在推特可能的潜在热度或危险信号。",
                    },
                ],
            )
            return self._safe_str(res.choices[0].message.content, 80) or "社交分析为空"
        except Exception as e:
            logger.error(f"社交分析异常: {e}")
            return "社交分析报错"

    # ---------------------------
    # decision parsing
    # ---------------------------
    def _parse_decision(
        self,
        raw_text: str,
        algo_score: int,
        algo_verdict: str,
        algo_risks: List[str],
        algo_details: str,
    ) -> Dict[str, Any]:
        if not raw_text:
            return self._fallback_decision(
                algo_score, algo_verdict, algo_risks + ["AI_EMPTY"], f"AI空响应: {algo_details}"
            )

        js = self._extract_outer_json_object(raw_text)
        if not js:
            return self._fallback_decision(
                algo_score, algo_verdict, algo_risks + ["AI_NO_JSON"], f"AI无JSON: {algo_details}"
            )

        js = self._fix_common_json_issues(js)
        try:
            obj = json.loads(js)
        except Exception:
            return self._fallback_decision(
                algo_score, algo_verdict, algo_risks + ["AI_BAD_JSON"], f"JSON解析失败: {algo_details}"
            )

        score = obj.get("score", algo_score)
        verdict = obj.get("verdict", algo_verdict)
        risk_flags = obj.get("risk_flags", algo_risks)
        reason = obj.get("reason", "")

        try:
            score = int(float(score))
        except Exception:
            score = algo_score
        score = max(0, min(100, score))

        verdict = _normalize_verdict(verdict, algo_verdict)

        if not isinstance(risk_flags, list):
            risk_flags = [str(risk_flags)]
        risk_flags = [self._safe_str(x, 24).upper() for x in risk_flags if str(x).strip()]
        if not risk_flags:
            risk_flags = algo_risks or ["NONE"]

        return {
            "score": score,
            "verdict": verdict,
            "risk_flags": risk_flags,
            "reason": self._safe_str(reason, 120) or "信息不足",
            "ai_entry": self._safe_str(obj.get("ai_entry", ""), 220),
            "ai_exit": self._safe_str(obj.get("ai_exit", ""), 220),
            "ai_narrative": self._safe_str(obj.get("ai_narrative", ""), 240),
            "ai_image_read": self._safe_str(obj.get("ai_image_read", ""), 240),
            "ai_chart_read": self._safe_str(obj.get("ai_chart_read", ""), 240),
        }

    def _fallback_decision(self, score: int, verdict: str, risks: List[str], reason: str) -> Dict[str, Any]:
        d = dict(DEFAULT_DECISION)
        d.update(
            {
                "score": score,
                "verdict": verdict,
                "risk_flags": risks,
                "reason": reason,
                "ai_entry": "数据或网络受限：建议观望，等待信号明确再操作。",
                "ai_exit": "严格设置止损，避免剧烈波动带来的滑点亏损。",
            }
        )
        return d

    def _fmt_mcap_label(self, v: float) -> str:
        if v <= 0:
            return "市值待确认"
        if v >= 1_000_000_000:
            return f"${v/1_000_000_000:.2f}B"
        if v >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        if v >= 1_000:
            return f"${v/1_000:.2f}K"
        return f"${v:.0f}"

    def _plan_profile(self, strategy_id: str) -> Dict[str, Any]:
        sid = str(strategy_id or "DEFAULT").upper()
        presets = {
            "SMART_TREND": {"tp_targets": [1.30, 1.60, 2.00], "sl_pct": 0.12},
            "SNIPER_PLAY": {"tp_targets": [1.20, 1.45, 1.80], "sl_pct": 0.10},
            "BUNDLE_CTRL": {"tp_targets": [1.18, 1.35, 1.60], "sl_pct": 0.09},
            "MIXED": {"tp_targets": [1.22, 1.45, 1.75], "sl_pct": 0.10},
            "DEFAULT": {"tp_targets": [1.20, 1.50, 2.00], "sl_pct": 0.10},
        }
        return dict(presets.get(sid, presets["DEFAULT"]))

    def _inject_mcap_trade_plan(self, token_data: dict, decision: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(decision or {})
        current_mcap = _to_float(token_data.get("cap_usd") or token_data.get("mcap") or token_data.get("fdv"))
        if current_mcap <= 0:
            d["ai_entry"] = "市值待确认，先不设具体入场点位。"
            d["ai_exit"] = "市值待确认，等待稳定快照后再设防守退场。"
            return d

        verdict = str(d.get("verdict", "WATCH")).upper()
        strategy_id = str(token_data.get("strategy_id") or "DEFAULT")
        profile = self._plan_profile(strategy_id)
        tp_targets = profile.get("tp_targets") or [1.2, 1.5, 2.0]
        sl_pct = max(0.05, min(0.25, _to_float(profile.get("sl_pct")) or 0.10))

        entry_ref = current_mcap
        if verdict == "BUY":
            entry_ref = current_mcap * 0.95
            entry_text = f"回踩至 {self._fmt_mcap_label(entry_ref)} 附近再考虑接。"
        elif verdict == "WATCH":
            entry_ref = current_mcap * 1.02
            entry_text = f"重新站上 {self._fmt_mcap_label(entry_ref)} 并放量后再看。"
        else:
            entry_text = f"未重回 {self._fmt_mcap_label(current_mcap)} 前不考虑进场。"

        sl_mcap = entry_ref * (1.0 - sl_pct)
        tp_mcaps = [entry_ref * float(x) for x in tp_targets[:3]]

        if len(tp_mcaps) >= 3:
            exit_text = (
                f"跌破 {self._fmt_mcap_label(sl_mcap)} 离场；分批止盈看 "
                f"{self._fmt_mcap_label(tp_mcaps[0])} / {self._fmt_mcap_label(tp_mcaps[1])} / {self._fmt_mcap_label(tp_mcaps[2])}。"
            )
        else:
            exit_text = f"跌破 {self._fmt_mcap_label(sl_mcap)} 离场。"

        d["ai_entry"] = self._safe_str(entry_text, 220)
        d["ai_exit"] = self._safe_str(exit_text, 220)
        return d

    # ---------------------------
    # model routing
    # ---------------------------
    async def _call_reasoning_model(self, system_prompt: str, user_prompt: str) -> str:
        """
        静态深度研究优先走 reasoning 模型；
        若无 DeepSeek，则回退 OpenAI 快速 JSON。
        """
        combined_prompt = system_prompt + "\n\n" + user_prompt

        if self.client:
            model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner")
            resp = await self.client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": combined_prompt}],
            )
            try:
                return resp.choices[0].message.content or ""
            except Exception:
                return ""

        if self.oai_client:
            try:
                resp = await self.oai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content or ""
            except Exception:
                return ""

        raise RuntimeError("No reasoning AI client available")

    async def _call_fast_json_model(self, system_prompt: str, user_prompt: str) -> str:
        """
        动态策略必须优先走快模型，确保低延迟 JSON 输出
        """
        if self.oai_client:
            try:
                resp = await self.oai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                logger.warning(f"⚠️ OpenAI 快模型调用失败，尝试回退 DeepSeek: {e}")

        if self.client:
            try:
                resp = await self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                logger.error(f"❌ DeepSeek V3 快模型调用失败: {e}")
                return ""

        raise RuntimeError("No fast AI client available")

    # =======================================================
    # 第一脑：静态叙事 / 头像视觉
    # =======================================================
    async def analyze_static_narrative(self, token_data: dict, analytics: dict = None) -> Dict[str, str]:
        token_data = token_data or {}
        symbol = self._safe_str(token_data.get("symbol", "UNK"), 24)
        name = self._safe_str(token_data.get("name", ""), 48)
        avatar_path = token_data.get("token_image_path", "")
        avatar_url = token_data.get("token_image_url", "")
        av_res, so_res = await asyncio.gather(
            self._analyze_avatar(avatar_path, symbol, avatar_url),
            self._analyze_social(symbol),
        )
        system_prompt = (
            "你是一个无情但敏锐的 Crypto Web3 Meme 文化研究员。你的唯一目标是穿透表象，评估代币的纯叙事价值和视觉传播力。\n"
            "【严格约束】：\n"
            "1. 拒绝任何废话和免责声明。\n"
            "2. 必须输出合法的纯 JSON 对象，绝对不要使用 Markdown 包裹。\n"
        )
        user_prompt = (
            f"Token: {symbol} ({name})\n"
            f"视觉情报(头像): {av_res}\n"
            f"社交情报(推特): {so_res}\n\n"
            "请基于以上碎片情报做定性分析。若某项情报缺失，请直接指出“数据不足，属于盲盒阶段”，禁止编造。\n\n"
            "输出 JSON 字段必须严格遵循以下定义：\n"
            "- ai_narrative：中文，<=60字。点出其 IP 原创度、文化辨识度、是否有 Cult 潜力，以及叙事生命周期判断。\n"
            "- ai_image_read：中文，<=40字。评价视觉质量，是廉价 AI 图、普通仿盘图，还是具备二创传播潜力的素材。\n\n"
            "正确输出示例：\n"
            '{"ai_narrative": "典型的 Meme 仿盘叙事，视觉记忆点一般，短线可能有热度但缺乏长线 Cult 潜力。", "ai_image_read": "头像完成度一般，偏模板化，二创传播力有限。"}'
        )
        try:
            raw = await self._call_reasoning_model(system_prompt, user_prompt)
            js = self._extract_outer_json_object(raw)
            js = self._fix_common_json_issues(js) if js else "{}"
            obj = json.loads(js)
            return {
                "ai_narrative": self._safe_str(obj.get("ai_narrative", "叙事未知"), 100),
                "ai_image_read": self._safe_str(obj.get("ai_image_read", "视觉未知"), 100),
            }
        except Exception as e:
            logger.error(f"静态叙事分析失败: {e}")
            return {"ai_narrative": "获取叙事失败", "ai_image_read": "获取视觉失败"}

    async def _legacy_analyze_dynamic_strategy_buy_watch_pass(
        self,
        token_data: dict,
        terminal_states: dict = None,
        analytics: dict = None,
    ) -> Dict[str, Any]:
        token_data = token_data or {}
        terminal_states = terminal_states or {}
        analytics = analytics or {}

        algo = calc_algo_score(token_data)
        algo_score = int(algo["score"])
        algo_risks = list(algo.get("risk_flags") or ["NONE"])
        algo_verdict = "BUY" if algo_score >= 80 else "WATCH" if algo_score >= 60 else "PASS"

        symbol = self._safe_str(token_data.get("symbol", "UNK"), 24)
        price = _to_float(token_data.get("price_usd") or token_data.get("priceUsd"))
        mcap = _to_float(token_data.get("cap_usd") or token_data.get("mcap") or token_data.get("fdv"))
        liq = _to_float(get_decision_liquidity_usd(token_data))

        ai_narrative = terminal_states.get("ai_narrative", "无")
        ai_image_read = terminal_states.get("ai_image_read", "无")
        entry_price = _to_float(terminal_states.get("entry_price", 0))

        delta_str = ""
        if entry_price > 0 and price > 0:
            mult = price / entry_price
            delta_str = f"当前价格倍数: {mult:.2f}X (相较于系统初始发现价格)"

        smart = _to_int(token_data.get("gmgn_smart"))
        sniper = _to_int(token_data.get("gmgn_sniper"))
        rat = _to_int(token_data.get("gmgn_rat"))
        is_burned = token_data.get("is_burned")
        top10 = _get_trusted_top10_text(token_data)
        top10_pending = _top10_pending_gmgn_review(token_data)

        screenshot_path = analytics.get("screenshot") or token_data.get("chart_screenshot") or ""
        chart_read = await self._analyze_chart(screenshot_path) if screenshot_path else "暂无最新K线图"

        if not self.client and not self.oai_client:
            res = self._fallback_decision(
                algo_score, algo_verdict, algo_risks + ["NO_AI"], "AI未配置，回退算法"
            )
            res.update(
                {
                    "ai_narrative": ai_narrative,
                    "ai_image_read": ai_image_read,
                    "ai_chart_read": chart_read,
                }
            )
            return self._inject_mcap_trade_plan(token_data, res)
        liq_language_guard = (
            "4. 只有当结构化低流动性条件成立时，才允许使用“流动性不足”“流动性较低”“池子太薄”等表述；"
            "否则必须使用中性措辞，如“继续观察”或“等待放量确认”。\n"
        )
        top10_review_guard = (
            "5. 若 top10_pending_gmgn_review=true，则不得把 Bitquery-only Top10 当成最终红线，"
            "只能表述为“Top10待校正，当前不以 Bitquery-only 结果直接定性”。\n"
        )
        system_prompt = (
            "你是华尔街级别的顶级加密货币短线高频交易员(Degen Sniper)。你冷血、客观，只看盈亏比、筹码结构和价格动量。\n"
            "【操盘纪律】：\n"
            "1. 你的建议必须具体、带有明确触发条件(If...Then...)。\n"
            "2. 禁止说“建议观望”这种废话，要指出观望到什么指标出现才动手。\n"
            "3. 必须输出合法的纯JSON对象，绝对不要使用 Markdown 语法包裹。\n"
        )
        system_prompt += liq_language_guard
        system_prompt += top10_review_guard

        user_prompt = (
            f"【目标标的】: {symbol}\n"
            f"【历史静态底牌】: 叙事内核: {ai_narrative} | 视觉基因: {ai_image_read}\n"
            f"【最新盘面异动】: 当前市值: {mcap} USD | 流动性: {liq} USD | {delta_str}\n"
            f"【筹码结构扫描】: 狙击手剩 {sniper} | 老鼠仓 {rat} | 聪明钱 {smart} | 前十总持仓 {top10} | Top10待复核={top10_pending} | 池子是否烧毁: {is_burned}\n"
            f"【交易部即时扫描(K线/图形)】: {chart_read}\n\n"
            "请结合其【底牌】与当下的【筹码/盘面/K线图形】，给出最冷酷的交易决策。\n\n"
            "输出JSON字段严格遵循以下定义：\n"
            "- score: 0-100 的整数。\n"
            "- verdict: 只能从 [BUY, WATCH, PASS] 中选一。\n"
            "- risk_flags: 数组，包含1-3个英文简写风险标签。\n"
            "- reason: 中文<=25字。给出做出该 Verdict 的核心原因。\n"
            "- ai_entry: 中文<=60字。极简入场条件。\n"
            "- ai_exit: 中文<=60字。明确的止损条件和分批止盈策略。\n"
            "- ai_chart_read: 中文<=60字。用一句话总结当前K线与量能的核心结论。\n"
        )

        try:
            raw = await self._call_fast_json_model(system_prompt, user_prompt)
            res = self._parse_decision(raw, algo_score, algo_verdict, algo_risks, algo.get("details", ""))
            res["ai_narrative"] = ai_narrative
            res["ai_image_read"] = ai_image_read
            if not res.get("ai_chart_read"):
                res["ai_chart_read"] = self._safe_str(chart_read, 120)
            return self._inject_mcap_trade_plan(token_data, res)
        except Exception as e:
            logger.error(f"❌ 动态策略分析失败: {e}")
            res = self._fallback_decision(
                algo_score, algo_verdict, algo_risks + ["AI_NET_ERR"], "AI网络异常"
            )
            res.update(
                {
                    "ai_narrative": ai_narrative,
                    "ai_image_read": ai_image_read,
                    "ai_chart_read": self._safe_str(chart_read, 120),
                }
            )
            return self._inject_mcap_trade_plan(token_data, res)

    # =======================================================
    # 兼容旧版统一入口
    # =======================================================
    def _inject_mcap_trade_plan(self, token_data: dict, decision: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(decision or {})
        current_mcap = _to_float(token_data.get("cap_usd") or token_data.get("mcap") or token_data.get("fdv"))
        if current_mcap <= 0:
            d["ai_entry"] = "市值待确认，先不要给出正式进场动作。"
            d["ai_exit"] = "市值待确认，先以观察为主，再决定退出位。"
            return d

        verdict = _normalize_verdict(d.get("verdict", "WATCH"), "WATCH")
        strategy_id = str(token_data.get("strategy_id") or "DEFAULT")
        profile = self._plan_profile(strategy_id)
        tp_targets = profile.get("tp_targets") or [1.2, 1.5, 2.0]
        sl_pct = max(0.05, min(0.25, _to_float(profile.get("sl_pct")) or 0.10))

        entry_ref = current_mcap
        if verdict == "ENTER":
            entry_ref = current_mcap * 0.98
            entry_text = f"确认 {self._fmt_mcap_label(entry_ref)} 一线承接后，可正式 ENTER。"
        elif verdict == "PROBE":
            entry_ref = current_mcap * 0.99
            entry_text = f"只做探针仓，先看 {self._fmt_mcap_label(entry_ref)} 附近承接。"
        elif verdict == "WATCH":
            entry_ref = current_mcap * 1.02
            entry_text = f"重新站上 {self._fmt_mcap_label(entry_ref)} 并放量后再观察。"
        elif verdict == "EXIT":
            entry_text = f"已有仓位优先退出，不建议在 {self._fmt_mcap_label(current_mcap)} 再加仓。"
        else:
            entry_text = f"未重回 {self._fmt_mcap_label(current_mcap)} 前，不考虑开仓。"

        sl_mcap = entry_ref * (1.0 - sl_pct)
        tp_mcaps = [entry_ref * float(x) for x in tp_targets[:3]]

        if verdict == "EXIT":
            exit_text = f"若已有仓位，优先在 {self._fmt_mcap_label(current_mcap)} 一带执行 EXIT。"
        elif len(tp_mcaps) >= 3:
            exit_text = (
                f"跌破 {self._fmt_mcap_label(sl_mcap)} 退出；分批止盈看 "
                f"{self._fmt_mcap_label(tp_mcaps[0])} / {self._fmt_mcap_label(tp_mcaps[1])} / {self._fmt_mcap_label(tp_mcaps[2])}。"
            )
        else:
            exit_text = f"跌破 {self._fmt_mcap_label(sl_mcap)} 退出。"

        d["ai_entry"] = self._safe_str(entry_text, 220)
        d["ai_exit"] = self._safe_str(exit_text, 220)
        return d

    async def analyze_dynamic_strategy(
        self,
        token_data: dict,
        terminal_states: dict = None,
        analytics: dict = None,
    ) -> Dict[str, Any]:
        token_data = token_data or {}
        terminal_states = terminal_states or {}
        analytics = analytics or {}

        algo = calc_algo_score(token_data)
        algo_score = int(algo["score"])
        algo_risks = list(algo.get("risk_flags") or ["NONE"])

        pipeline_settings = canonical_pipeline_settings()
        thresholds = canonical_thresholds()
        current_state = str(
            terminal_states.get("signal_state") or token_data.get("signal_state") or "OBSERVING"
        ).upper()
        liq_context = get_decision_liquidity_context(token_data)
        canonical_stage = get_canonical_stage(token_data) or "unresolved"
        canonical_meta = token_data.get("canonical_metadata") if isinstance(token_data.get("canonical_metadata"), dict) else {}
        top10_semantics = str(
            canonical_meta.get("top10_adjustment_semantics") or token_data.get("top10_adjustment_semantics") or "unknown"
        )
        top10_entity_adjusted = bool(
            canonical_meta.get("top10_entity_adjusted", token_data.get("top10_entity_adjusted", False))
        )

        enter_min = _to_float(pipeline_settings.get("action_enter_score_min"), 80.0)
        probe_min = _to_float(pipeline_settings.get("action_probe_score_min"), 65.0)
        watch_min = _to_float(pipeline_settings.get("action_watch_score_min"), 50.0)
        exit_max = _to_float(pipeline_settings.get("action_exit_score_max_when_entered"), 35.0)
        strict_block_verdict = _normalize_verdict(
            pipeline_settings.get("strict_enter_block_verdict", "PROBE"),
            "PROBE",
        )
        if strict_block_verdict not in {"WATCH", "PROBE"}:
            strict_block_verdict = "PROBE"

        if current_state == "ENTERED" and algo_score <= exit_max:
            algo_verdict = "EXIT"
        elif algo_score >= enter_min:
            algo_verdict = "ENTER"
        elif algo_score >= probe_min:
            algo_verdict = "PROBE"
        elif algo_score >= watch_min:
            algo_verdict = "WATCH"
        else:
            algo_verdict = "PASS"

        if algo_verdict == "ENTER" and not liq_context["formal_enter_ready"]:
            algo_verdict = strict_block_verdict

        symbol = self._safe_str(token_data.get("symbol", "UNK"), 24)
        price = _to_float(token_data.get("price_usd") or token_data.get("priceUsd"))
        mcap = _to_float(token_data.get("cap_usd") or token_data.get("mcap") or token_data.get("fdv"))
        liq = _to_float(get_decision_liquidity_usd(token_data))
        liq_ratio = (liq / mcap) if mcap > 0 and liq > 0 else 0.0
        liq_low_flag = liq > 0 and liq < _to_float(thresholds.get("liquidity_danger_usd", 2000.0), 2000.0)
        liq_ratio_fatal_flag = (
            mcap > 0
            and liq > 0
            and liq_ratio < _to_float(thresholds.get("liquidity_ratio_fatal", 0.01), 0.01)
        )

        ai_narrative = terminal_states.get("ai_narrative", "")
        ai_image_read = terminal_states.get("ai_image_read", "")
        entry_price = _to_float(terminal_states.get("entry_price", 0))

        delta_str = ""
        if entry_price > 0 and price > 0:
            mult = price / entry_price
            delta_str = f"当前价格倍数: {mult:.2f}X (相较于系统初始发现价格)"

        smart = _to_int(token_data.get("gmgn_smart"))
        sniper = _to_int(token_data.get("gmgn_sniper"))
        rat = _to_int(token_data.get("gmgn_rat"))
        is_burned = token_data.get("is_burned")
        top10 = _get_trusted_top10_text(token_data)
        top10_pending = _top10_pending_gmgn_review(token_data)

        screenshot_path = analytics.get("screenshot") or token_data.get("chart_screenshot") or ""
        chart_read = await self._analyze_chart(screenshot_path) if screenshot_path else "暂无最新K线图"

        if not self.client and not self.oai_client:
            res = self._fallback_decision(
                algo_score, algo_verdict, algo_risks + ["NO_AI"], "AI未配置，回退算法"
            )
            res.update(
                {
                    "ai_narrative": ai_narrative,
                    "ai_image_read": ai_image_read,
                    "ai_chart_read": chart_read,
                }
            )
            return self._inject_mcap_trade_plan(token_data, res)
        liq_language_guard = (
            "6. 只有当 liq_low_flag=true 或 liq_ratio_fatal_flag=true 时，才允许使用“流动性不足”“流动性较低”“池子太薄”等表述；"
            "否则必须使用中性措辞，如“继续观察”或“等待放量确认”。\n"
        )
        top10_review_guard = (
            "7. 若 top10_pending_gmgn_review=true，则不得把 Bitquery-only Top10 当成最终红线，"
            "只能表述为“Top10待校正，当前不以 Bitquery-only 结果直接定性”。\n"
        )
        system_prompt = (
            "你是顶级加密短线交易员，只输出冷静、可执行的交易动作。\n"
            "规则:\n"
            "1. 只允许输出合法 JSON。\n"
            "2. verdict 只能从 PASS / WATCH / PROBE / ENTER / EXIT 中选择。\n"
            "3. PASS=放弃，WATCH=继续观察，PROBE=仅允许试探仓，ENTER=正式进场，EXIT=已有仓位退出。\n"
            "4. 若 strict liquidity 未就绪，不允许输出 ENTER，只能在 WATCH 或 PROBE 中选择。\n"
            "5. 若当前状态不是 ENTERED，不要轻易给 EXIT。\n"
        )

        system_prompt += liq_language_guard
        system_prompt += top10_review_guard

        user_prompt = (
            f"结构化流动性: decision_liquidity_usd={liq} | liquidity_ratio={liq_ratio:.4f} | liq_low_flag={liq_low_flag} | liq_ratio_fatal_flag={liq_ratio_fatal_flag}\n"
            f"目标: {symbol}\n"
            f"静态底牌: 叙事={ai_narrative} | 视觉={ai_image_read}\n"
            f"最新盘面: 市值={mcap} USD | 流动性={liq} USD | {delta_str}\n"
            f"筹码结构: Sniper={sniper} | Rat={rat} | Smart={smart} | Top10={top10} | top10_pending_gmgn_review={top10_pending} | Burned={is_burned}\n"
            f"执行上下文: state={current_state} | canonical_stage={canonical_stage} | "
            f"top10_semantics={top10_semantics} | entity_adjusted={top10_entity_adjusted} | "
            f"strict_liquidity={liq_context['strict_mode']} | formal_enter_ready={liq_context['formal_enter_ready']} | "
            f"liquidity_source={liq_context['display_source'] or 'NONE'}\n"
            f"K线扫描: {chart_read}\n\n"
            "请输出 JSON:\n"
            "- score: 0-100 整数\n"
            "- verdict: PASS/WATCH/PROBE/ENTER/EXIT\n"
            "- risk_flags: 1-3 个英文标签\n"
            "- reason: 中文，<=25字\n"
            "- ai_entry: 中文，<=60字\n"
            "- ai_exit: 中文，<=60字\n"
            "- ai_chart_read: 中文，<=60字\n"
        )

        try:
            raw = await self._call_fast_json_model(system_prompt, user_prompt)
            res = self._parse_decision(raw, algo_score, algo_verdict, algo_risks, algo.get("details", ""))
            res["verdict"] = _normalize_verdict(res.get("verdict", algo_verdict), algo_verdict)
            res["ai_narrative"] = ai_narrative
            res["ai_image_read"] = ai_image_read
            if not res.get("ai_chart_read"):
                res["ai_chart_read"] = self._safe_str(chart_read, 120)
            return self._inject_mcap_trade_plan(token_data, res)
        except Exception as e:
            logger.error(f"动态策略分析失败: {e}")
            res = self._fallback_decision(
                algo_score, algo_verdict, algo_risks + ["AI_NET_ERR"], "AI网络异常"
            )
            res.update(
                {
                    "ai_narrative": ai_narrative,
                    "ai_image_read": ai_image_read,
                    "ai_chart_read": self._safe_str(chart_read, 120),
                }
            )
            return self._inject_mcap_trade_plan(token_data, res)

    async def analyze_token(self, *args, **kwargs) -> Dict[str, Any]:
        ca = ""
        token_data: dict = {}
        analytics: Optional[dict] = None

        if args:
            if isinstance(args[0], dict):
                token_data = args[0]
            else:
                ca = str(args[0] or "")
                if len(args) >= 2 and isinstance(args[1], dict):
                    token_data = args[1]
                if len(args) >= 3 and isinstance(args[2], dict):
                    analytics = args[2]

        token_data = token_data or {}
        analytics = analytics or kwargs.get("analytics") or {}

        static_res = await self.analyze_static_narrative(token_data, analytics)

        terminal_states = {
            "ai_narrative": static_res.get("ai_narrative"),
            "ai_image_read": static_res.get("ai_image_read"),
            "entry_price": token_data.get("price_usd", 0),
        }

        final_decision = await self.analyze_dynamic_strategy(token_data, terminal_states, analytics)
        return final_decision


brain = Brain()
