import os
import re
import json
import logging
import asyncio
import base64
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

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
}

ALLOWED_VERDICTS = {"BUY", "WATCH", "PASS"}


# ===========================
# Algo Scoring (fallback)
# ===========================
def _to_int(x: Any) -> int:
    try:
        return int(float(x))
    except Exception:
        return 0


def _to_float(x: Any) -> float:
    try:
        if x is None or x == "":
            return 0.0
        if isinstance(x, str):
            x = x.replace(",", "").strip()
        v = float(x)
        if v != v or v in (float("inf"), float("-inf")):
            return 0.0
        return v
    except Exception:
        return 0.0


def calc_algo_score(token_data: dict) -> Dict[str, Any]:
    """
    只作为 AI 不可用时兜底：稳健 > 激进。
    """
    td = token_data or {}

    price = _to_float(td.get("price_usd") or td.get("priceUsd"))
    mcap = _to_float(td.get("cap_usd") or td.get("mcap") or td.get("fdv"))
    liq = _to_float(td.get("liquidity_usd"))
    vol = _to_float(td.get("volume_h24"))

    sniper = _to_int(td.get("gmgn_sniper"))
    rat = _to_int(td.get("gmgn_rat"))
    bundle = _to_int(td.get("gmgn_bundle"))
    smart = _to_int(td.get("gmgn_smart"))
    dev = _to_int(td.get("gmgn_dev"))

    top10_ratio = td.get("top10_ratio")
    mint_present = td.get("mint_authority_present")
    freeze_present = td.get("freeze_authority_present")
    non_honeypot = td.get("non_honeypot")
    liq_locked = td.get("liquidity_locked")
    dex_paid = td.get("dex_paid")

    score = 50
    risks: List[str] = []
    details: List[str] = []

    try:
        t10 = float(str(top10_ratio).replace("%", "")) if top10_ratio is not None else None
    except Exception:
        t10 = None

    if t10 is not None:
        if t10 >= 60:
            score -= 25
            risks.append("TOP10_60")
            details.append(f"Top10 {t10:.1f}%")
        elif t10 >= 50:
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

    if mcap > 0 and mcap < 5_000_000:
        score += 4
        details.append("小市值")
    if liq > 0 and liq < 5_000:
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
        "details": "；".join(details[:8]) if details else "—"
    }


# ===========================
# Brain (AI 矩阵架构)
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
            except Exception:
                pass
                
        if XAI_API_KEY:
            try:
                self.xai_client = AsyncOpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
                logger.info("✅ Grok 情报局长已就位")
            except Exception:
                pass

    def _safe_str(self, x: Any, n: int = 160) -> str:
        s = "" if x is None else str(x)
        s = s.replace("\u0000", "").strip()
        return s[:n] if len(s) > n else s

    def _extract_outer_json_object(self, text: str) -> Optional[str]:
        if not text:
            return None
        text = text.strip()
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        m = re.search(r"\{[\s\S]*\}", text)
        return m.group(0) if m else None

    def _fix_common_json_issues(self, s: str) -> str:
        s = s.strip()
        s = re.sub(r",\s*}", "}", s)
        s = re.sub(r",\s*]", "]", s)
        return s

    def _encode_image(self, image_path: str) -> str:
        if not image_path or not os.path.exists(image_path):
            return ""
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception:
            return ""

    # ---------------------------
    # 多模态子代理 (Sub-Agents)
    # ---------------------------
    async def _analyze_avatar(self, path: str, symbol: str) -> str:
        if not self.oai_client or not path: return "未启用视觉或无头像"
        img = self._encode_image(path)
        if not img: return "头像读取失败"
        try:
            res = await self.oai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": f"代币{symbol}的头像，是一眼假的劣质图还是高质量/魔性原创图？用一句简短的话评价。"}, 
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}
                ]}]
            )
            return res.choices[0].message.content
        except Exception: return "头像分析报错"

    async def _analyze_chart(self, path: str) -> str:
        if not self.oai_client or not path: return "未启用视觉或无K线图"
        img = self._encode_image(path)
        if not img: return "K线截图读取失败"
        try:
            res = await self.oai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "作为顶级交易员，一句话分析这张DexK线图：处于拉升初盘、洗盘诱空还是典型的暴跌画门？"}, 
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}
                ]}]
            )
            return res.choices[0].message.content
        except Exception: return "K线分析报错"

    async def _analyze_social(self, symbol: str) -> str:
        if not self.xai_client: return "未启用 Grok"
        try:
            res = await self.xai_client.chat.completions.create(
                model="grok-3-mini",
                messages=[
                    {"role": "system", "content": "你是最懂 Crypto X (推特) 文化的 Degen。"},
                    {"role": "user", "content": f"代币名称: {symbol}。用一句极简的Crypto黑话评判它在推特可能的潜在热度或危险信号。"}
                ]
            )
            return res.choices[0].message.content
        except Exception: return "社交分析报错"

    # ---------------------------
    # JSON 兜底解析引擎
    # ---------------------------
    def _parse_decision(
        self,
        raw_text: str,
        algo_score: int,
        algo_verdict: str,
        algo_risks: List[str],
        algo_details: str
    ) -> Dict[str, Any]:
        if not raw_text:
            return self._fallback_decision(algo_score, algo_verdict, algo_risks + ["AI_EMPTY"], f"AI空响应: {algo_details}")

        js = self._extract_outer_json_object(raw_text)
        if not js:
            return self._fallback_decision(algo_score, algo_verdict, algo_risks + ["AI_NO_JSON"], f"AI无JSON: {algo_details}")

        js = self._fix_common_json_issues(js)
        try:
            obj = json.loads(js)
        except Exception:
            return self._fallback_decision(algo_score, algo_verdict, algo_risks + ["AI_BAD_JSON"], f"JSON解析失败: {algo_details}")

        score = obj.get("score", algo_score)
        verdict = obj.get("verdict", algo_verdict)
        risk_flags = obj.get("risk_flags", algo_risks)
        reason = obj.get("reason", "")

        try:
            score = int(float(score))
        except Exception:
            score = algo_score
        score = max(0, min(100, score))

        verdict = str(verdict).upper().strip()
        if verdict not in ALLOWED_VERDICTS:
            verdict = algo_verdict

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
        }

    def _fallback_decision(self, score: int, verdict: str, risks: List[str], reason: str) -> Dict[str, Any]:
        d = dict(DEFAULT_DECISION)
        d.update({
            "score": score,
            "verdict": verdict,
            "risk_flags": risks,
            "reason": reason,
            "ai_entry": "数据或网络受限：建议观望，等待信号明确再操作。",
            "ai_exit": "严格设置止损，避免剧烈波动带来的滑点亏损。",
        })
        return d

    # =======================================================
    # 🟢 核心重构：大模型路由引擎 (Model Routing)
    # =======================================================
    async def _call_reasoning_model(self, system_prompt: str, user_prompt: str) -> str:
        """【左脑专用】调用带有思考过程的慢模型 (R1/o1)"""
        if not self.client:
            raise RuntimeError("No reasoning AI client available")
            
        combined_prompt = system_prompt + "\n\n" + user_prompt
        # 自动读取 .env 配置，默认使用 deepseek-reasoner
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner")
        
        # 思考模型不支持 response_format="json_object"，必须普通调用
        resp = await self.client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": combined_prompt}]
        )
        try:
            return resp.choices[0].message.content or ""
        except Exception:
            return ""

    async def _call_fast_json_model(self, system_prompt: str, user_prompt: str) -> str:
        """【右脑专用】强制调用极速模型，100% 确保输出干净的 JSON 且不超时"""
        
        # 1. 🥇 首选：如果有 OpenAI 钥匙，调用地表最稳最快的 gpt-4o-mini
        if self.oai_client:
            try:
                resp = await self.oai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"}
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                logger.warning(f"⚠️ OpenAI 快模型调用失败，尝试回退 DeepSeek: {e}")

        # 2. 🥈 备选：如果只有 DeepSeek 钥匙，强行调用非思考版的 V3 (deepseek-chat)
        if self.client:
            try:
                resp = await self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"}
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                logger.error(f"❌ DeepSeek V3 快模型调用失败: {e}")
                return ""
                
        raise RuntimeError("No fast AI client available")

    # =======================================================
    # 第一脑 (静态深度研究员) - 负责看图和解构文化
    # =======================================================
    async def analyze_static_narrative(self, token_data: dict, analytics: dict = None) -> Dict[str, str]:
        token_data = token_data or {}
        symbol = self._safe_str(token_data.get("symbol", "UNK"), 24)
        name = self._safe_str(token_data.get("name", ""), 48)
        avatar_path = token_data.get("token_image_path", "")
        
        av_res, so_res = await asyncio.gather(
            self._analyze_avatar(avatar_path, symbol),
            self._analyze_social(symbol)
        )

        system_prompt = (
            "你是一个无情且敏锐的 Crypto Web3 Meme 文化研究员。你的唯一目标是穿透表象，评估代币的‘纯叙事价值’和‘视觉传播力’。\n"
            "【严格约束】：\n"
            "1. 拒绝任何废话和免责声明。\n"
            "2. 必须输出合法的纯JSON对象，绝对不要使用 ```json 等Markdown语法包裹，直接输出花括号 {} 及内部内容。\n"
        )
        
        user_prompt = (
            f"Token: {symbol} ({name})\n"
            f"视觉部情报(头像): {av_res}\n"
            f"社交部情报(推特): {so_res}\n\n"
            "请基于以上碎片信息进行定性分析。若某项情报缺失，请直接指出“数据不足属于盲盒阶段”，禁止编造。\n\n"
            "输出JSON字段严格遵循以下定义：\n"
            "- ai_narrative：<=60字。必须点出它的IP原创度（是老IP仿盘还是新文化）、是否有Cult潜力、叙事生命周期预判。\n"
            "- ai_image_read：<=40字。评价其视觉质量（是AI粗劣生成还是极具魔性/二创潜力的精美素材）。\n\n"
            "【正确输出示例】：\n"
            '{"ai_narrative": "典型的Pepe换皮仿盘，叙事极度疲软且同质化严重，无长期Cult潜力。","ai_image_read": "AI生成的廉价网图，缺乏视觉记忆点和二创空间。"}'
        )

        try:
            # 🟢 左脑：调用慢速思考模型
            raw = await self._call_reasoning_model(system_prompt, user_prompt)
            js = self._extract_outer_json_object(raw)
            js = self._fix_common_json_issues(js) if js else "{}"
            obj = json.loads(js)
            return {
                "ai_narrative": self._safe_str(obj.get("ai_narrative", "叙事未知"), 100),
                "ai_image_read": self._safe_str(obj.get("ai_image_read", "视觉未知"), 100)
            }
        except Exception as e:
            logger.error(f"❌ 静态叙事分析失败: {e}")
            return {"ai_narrative": "获取叙事失败", "ai_image_read": "获取视觉失败"}

    # =======================================================
    # 第二脑 (动态极速操盘手) - 负责瞬间计算盈亏比下指令
    # =======================================================
    async def analyze_dynamic_strategy(self, token_data: dict, terminal_states: dict = None, analytics: dict = None) -> Dict[str, Any]:
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
        liq = _to_float(token_data.get("liquidity_usd"))
        
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
        top10 = token_data.get("top10_ratio", "未知")

        screenshot_path = analytics.get("screenshot", "")
        ch_res = await self._analyze_chart(screenshot_path) if screenshot_path else "暂无最新K线图"

        # 🟢 如果两个接口都没有，直接启动硬编码兜底
        if not self.client and not self.oai_client:
            res = self._fallback_decision(algo_score, algo_verdict, algo_risks + ["NO_AI"], "AI未配置，回退算法")
            res.update({"ai_narrative": ai_narrative, "ai_image_read": ai_image_read})
            return res

        system_prompt = (
            "你是华尔街级别的顶级加密货币短线高频交易员(Degen Sniper)。你冷血、客观，只看盈亏比、筹码结构和价格动量。\n"
            "【操盘纪律】：\n"
            "1. 你的建议必须具体的、带有明确触发条件的(If...Then...)。\n"
            "2. 禁止说“建议观望”这种废话，要指出观望到什么指标出现才动手。\n"
            "3. 必须输出合法的纯JSON对象，绝对不要使用 ```json 等Markdown语法包裹。\n"
        )

        user_prompt = (
            f"【目标标的】: {symbol}\n"
            f"【历史静态底牌】: 叙事内核: {ai_narrative} | 视觉基因: {ai_image_read}\n"
            f"【最新盘面异动】: 当前市值: {mcap} USD | 流动性: {liq} USD | {delta_str}\n"
            f"【筹码结构扫描】: 狙击手剩 {sniper} | 老鼠仓 {rat} | 聪明钱 {smart} | 前十总持仓 {top10} | 池子是否烧毁: {is_burned}\n"
            f"【交易部即时扫描】: {ch_res}\n\n"
            "请结合其【底牌】与当下的【筹码/盘面】，给出最冷酷的交易决策。\n\n"
            "输出JSON字段严格遵循以下定义：\n"
            "- score: 0-100的整数。\n"
            "- verdict: 只能从 [BUY, WATCH, PASS] 中选一。\n"
            "- risk_flags: 数组，包含1-3个英文简写风险标签。\n"
            "- reason: 中文<=25字。给出做出该Verdict的一针见血的核心原因。\n"
            "- ai_entry: 中文<=60字。极简入场条件。\n"
            "- ai_exit: 中文<=60字。明确的止损条件和分批止盈策略。\n"
        )

        try:
            # 🟢 右脑：强行路由至快模型 (gpt-4o-mini 或 deepseek-chat)
            raw = await self._call_fast_json_model(system_prompt, user_prompt)
            res = self._parse_decision(raw, algo_score, algo_verdict, algo_risks, "")
            res["ai_narrative"] = ai_narrative
            res["ai_image_read"] = ai_image_read
            return res
        except Exception as e:
            logger.error(f"❌ 动态策略分析失败: {e}")
            res = self._fallback_decision(algo_score, algo_verdict, algo_risks + ["AI_NET_ERR"], "AI网络异常")
            res.update({"ai_narrative": ai_narrative, "ai_image_read": ai_image_read})
            return res

    # =======================================================
    # 兼容旧版的统一入口
    # =======================================================
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
            "entry_price": token_data.get("price_usd", 0)
        }
        
        final_decision = await self.analyze_dynamic_strategy(token_data, terminal_states, analytics)
        
        return final_decision

brain = Brain()