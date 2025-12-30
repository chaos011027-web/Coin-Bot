import os
import re
import json
import time
import asyncio
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

logger = logging.getLogger("Brain")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

DEFAULT_DECISION = {
    "score": 0,
    "verdict": "PASS",
    "risk_flags": ["AI_ERROR"],
    "reason": "AI不可用或返回异常"
}

ALLOWED_VERDICTS = {"BUY", "WATCH", "PASS"}

# =========================================
# 🧮 算法评分引擎 (硬指标计算)
# =========================================
def calc_algo_score(token_data: dict) -> dict:
    """
    基于硬指标计算基准分，不依赖 AI。
    返回: {"score": int, "details": str, "risk_flags": list}
    """
    score = 60  # 及格线起步
    breakdown = []
    risk_flags = []

    # 1. 标签解析
    tags_list = token_data.get("gmgn_tags", [])
    tags_str = " ".join(tags_list)

    def get_tag_count(keywords):
        kw_pattern = "|".join([re.escape(k) for k in keywords])
        match = re.search(f"(?:{kw_pattern}).*?(\d+)", tags_str, re.IGNORECASE)
        return int(match.group(1)) if match else 0

    smart_count = get_tag_count(["Smart Money", "聪明钱", "Smart"])
    rat_count = get_tag_count(["Rat", "老鼠仓"])
    sniper_count = get_tag_count(["Sniper", "狙击手"])
    
    # 2. 市场基本面
    mcap = float(token_data.get("mcap") or token_data.get("fdv") or 0)
    liq = float(token_data.get("liquidity_usd", 0) or 0)

    if mcap < 5_000:
        score -= 20
        breakdown.append("市值过低")
        risk_flags.append("LOW_MCAP")
    elif 5_000 <= mcap < 100_000:
        score += 10
        breakdown.append("早期红利")
    
    if liq > 0 and mcap > 0:
        ratio = liq / mcap
        if ratio < 0.05: 
            score -= 15
            breakdown.append("池子太薄")
            risk_flags.append("THIN_LIQ")

    # 3. 筹码分布 (Top 10)
    top10_str = str(token_data.get("top10_ratio", "0")).replace("%", "")
    try: top10 = float(top10_str)
    except: top10 = 0

    if top10 > 50:
        score -= 30
        breakdown.append(f"Top10控盘{top10}%")
        risk_flags.append("HIGH_CONCENTRATION")
    elif 0 < top10 < 15:
        score += 5
        breakdown.append("筹码分散")

    # 4. GMGN 链上行为 (核心加分项)
    if smart_count > 0:
        pts = min(20, smart_count * 2)
        score += pts
        breakdown.append(f"聪明钱x{smart_count}")
    
    if rat_count > 0:
        penalty = rat_count * 10
        score -= penalty
        breakdown.append(f"老鼠仓x{rat_count}")
        risk_flags.append("RAT_FARM")

    # 5. 交易动能
    vol = float(token_data.get("volume_h24", 0) or 0)
    if vol > liq * 5:
        score += 5
        breakdown.append("超高换手")

    score = max(0, min(100, int(score)))
    
    return {
        "score": score,
        "details": ", ".join(breakdown) if breakdown else "无明显特征",
        "risk_flags": risk_flags
    }


class Brain:
    def __init__(
        self,
        model: str = "deepseek-chat",
        temperature: float = 0.6, # 稍微降低随机性，让它更听话
        max_tokens: int = 256,
        timeout_sec: float = 25.0,
        max_retries: int = 2,
        concurrency: int = 5,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self._sem = asyncio.Semaphore(concurrency)

        if not DEEPSEEK_API_KEY:
            logger.error("❌ 未找到 DEEPSEEK_API_KEY，AI 模块将降级为纯算法模式！")
            self.client = None
        else:
            self.client = AsyncOpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL
            )

    # -------------------------
    # Helpers
    # -------------------------
    def _safe_str(self, s: Any, max_len: int = 60) -> str:
        if s is None: return ""
        s = str(s)
        s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
        s = s.strip()
        if len(s) > max_len: s = s[:max_len] + "…"
        return s

    def _safe_num(self, v: Any) -> float:
        try:
            if v is None: return 0.0
            x = float(v)
            if x != x or x == float("inf") or x == float("-inf"): return 0.0
            return x
        except: return 0.0

    def _strip_code_fences(self, text: str) -> str:
        text = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```", "", text)
        return text.strip()

    def _extract_outer_json_object(self, text: str) -> Optional[str]:
        if not text: return None
        text = self._strip_code_fences(text)
        start = text.find("{")
        if start == -1: return None
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape: escape = False
                elif ch == "\\": escape = True
                elif ch == '"': in_str = False
                continue
            else:
                if ch == '"': in_str = True; continue
                if ch == "{": depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0: return text[start:i + 1]
        return None

    def _fix_common_json_issues(self, s: str) -> str:
        if not s: return s
        s = s.strip()
        s = re.sub(r"\bNaN\b", "0", s)
        s = re.sub(r"\bInfinity\b", "0", s)
        s = re.sub(r"\b-inf\b", "0", s, flags=re.IGNORECASE)
        s = re.sub(r",\s*([}\]])", r"\1", s)
        if s.count('"') < 2 and s.count("'") >= 4: s = s.replace("'", '"')
        return s

    def _parse_decision(self, raw_text: str) -> Dict[str, Any]:
        if not raw_text: return dict(DEFAULT_DECISION)
        json_text = self._extract_outer_json_object(raw_text)
        if not json_text:
            logger.error(f"❌ AI 返回无 JSON：{raw_text}")
            return dict(DEFAULT_DECISION)

        json_text = self._fix_common_json_issues(json_text)

        try:
            obj = json.loads(json_text)
        except Exception:
            logger.error(f"❌ JSON解析失败。raw={raw_text}")
            return dict(DEFAULT_DECISION)

        score = obj.get("score", 0)
        verdict = obj.get("verdict", "PASS")
        risk_flags = obj.get("risk_flags", [])
        reason = obj.get("reason", "")

        try: score = int(float(score))
        except: score = 0
        score = max(0, min(100, score))

        verdict = str(verdict).upper().strip()
        if verdict not in ALLOWED_VERDICTS: verdict = "PASS"

        if not isinstance(risk_flags, list): risk_flags = [str(risk_flags)]
        risk_flags = [self._safe_str(x, 20).upper() for x in risk_flags if str(x).strip()]
        if not risk_flags: risk_flags = ["NONE"]

        reason = self._safe_str(reason, 100)
        if not reason: reason = "信息不足"

        return {
            "score": score,
            "verdict": verdict,
            "risk_flags": risk_flags,
            "reason": reason
        }

    async def _call_deepseek(self, system_prompt: str, user_prompt: str) -> str:
        if not self.client: raise RuntimeError("No Client")
        async with self._sem:
            last_err = None
            for attempt in range(self.max_retries + 1):
                try:
                    coro = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                    resp = await asyncio.wait_for(coro, timeout=self.timeout_sec)
                    return resp.choices[0].message.content or ""
                except asyncio.TimeoutError as e:
                    last_err = e
                    logger.warning(f"⏱️ AI超时 {attempt+1}")
                except Exception as e:
                    last_err = e
                    msg = str(e).lower()
                    retriable = any(x in msg for x in ["429", "rate", "timeout", "502", "503"])
                    if not retriable: break
                    if attempt < self.max_retries: await asyncio.sleep(1 * (2 ** attempt))
            raise last_err or RuntimeError("DeepSeek failed")

    # -------------------------
    # Public: analyze token
    # -------------------------
    async def analyze_token(self, token_data: dict) -> Dict[str, Any]:
        """
        混合分析模式：算法 + AI
        """
        token_data = token_data or {}
        
        # 1. 先跑算法 (硬指标兜底)
        algo_result = calc_algo_score(token_data)
        algo_score = algo_result["score"]
        algo_details = algo_result["details"]
        algo_risks = algo_result["risk_flags"]
        
        # 算法建议
        algo_verdict = "BUY" if algo_score >= 80 else "WATCH" if algo_score >= 60 else "PASS"

        # 如果没有 Client，直接返回算法结果
        if not self.client:
            return {
                "score": algo_score,
                "verdict": algo_verdict,
                "risk_flags": algo_risks + ["NO_AI_KEY"],
                "reason": f"AI未配置，基于算法: {algo_details}"
            }

        # 2. 准备数据给 AI
        symbol = self._safe_str(token_data.get("symbol", "UNK"), 24)
        name = self._safe_str(token_data.get("name", "Unknown"), 48)
        mcap = self._safe_num(token_data.get("mcap", 0))
        liq = self._safe_num(token_data.get("liquidity_usd", 0))
        vol = self._safe_num(token_data.get("volume_h24", 0))
        
        # GMGN 数据
        tags = ", ".join(token_data.get("gmgn_tags", [])) or "None"
        top10 = token_data.get("top10_ratio", "Unknown")
        avg_hold = token_data.get("avg_hold", "Unknown")

        # 外部涨幅
        ext_pnl = token_data.get("external_pnl")
        pnl_context = f"Signal claims +{ext_pnl}%." if ext_pnl else "No signal pnl."

        system_prompt = (
            "You are a Solana Degen Analyst. "
            "I have already calculated a base score using an algorithm. "
            "Review the data, adjust the score if necessary, and output JSON."
        )

        user_prompt = (
            f"Token: {symbol} ({name})\n"
            f"Mcap: ${mcap:.0f} | Liq: ${liq:.0f} | Vol: ${vol:.0f}\n"
            f"GMGN: Tags=[{tags}] Top10={top10} AvgHold={avg_hold}\n"
            f"Context: {pnl_context}\n\n"
            f"🤖 Algo Analysis:\n"
            f"- Base Score: {algo_score}/100\n"
            f"- Logic: {algo_details}\n"
            f"- Risks: {algo_risks}\n\n"
            f"Task:\n"
            f"1. Final Score (0-100). Trust Algo unless you see extra narrative/risk.\n"
            f"2. Verdict: BUY / WATCH / PASS.\n"
            f"3. Reason: Short Chinese summary (max 20 words).\n\n"
            f"JSON Format:\n"
            f'{{"score":85,"verdict":"BUY","risk_flags":["TAG"],"reason":"..."}}'
        )

        try:
            raw = await self._call_deepseek(system_prompt, user_prompt)
            decision = self._parse_decision(raw)
            return decision

        except Exception as e:
            logger.error(f"❌ AI请求最终失败: {e}")
            # 兜底：AI 挂了就用算法结果
            return {
                "score": algo_score,
                "verdict": algo_verdict,
                "risk_flags": algo_risks + ["AI_NET_ERR"],
                "reason": f"AI超时，回退至算法评分: {algo_details}"
            }

brain = Brain()