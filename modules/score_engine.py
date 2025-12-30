import re

def calc_score_breakdown(token_data: dict) -> dict:
    """
    全能评分模型 V2.0
    基于：市场结构 + GMGN标签 + 持仓分布 + 交易动能
    """
    score = 60  # ✅ 优化1：基准分 60，及格线起步
    breakdown = {}

    # =========================================
    # 🛠 辅助：自动从标签列表提取数值
    # =========================================
    # 之前的 data_fetcher 返回的是 ['🧠 聪明钱(5)', '🐀 老鼠仓(10)']
    tags_list = token_data.get("gmgn_tags", [])
    tags_str = " ".join(tags_list)

    def get_tag_count(keywords):
        # 匹配 "关键词(数字)" 或 "关键词 x数字"
        kw_pattern = "|".join([re.escape(k) for k in keywords])
        match = re.search(f"(?:{kw_pattern}).*?(\d+)", tags_str)
        return int(match.group(1)) if match else 0

    smart_count = get_tag_count(["Smart Money", "聪明钱", "Smart"])
    kol_count = get_tag_count(["KOL"])
    rat_count = get_tag_count(["Rat", "老鼠仓"])
    sniper_count = get_tag_count(["Sniper", "狙击手"])
    bundle_count = get_tag_count(["Bundle", "捆绑"])

    # =========================================
    # 1. 市场基本面 (权重 30%)
    # =========================================
    mcap = float(token_data.get("mcap") or token_data.get("fdv") or 0)
    liq = float(token_data.get("liquidity_usd", 0) or 0)

    # 市值结构 (寻找 50K-500K 的金狗区间)
    if mcap < 5_000:
        score -= 20; breakdown["市值"] = -20  # 极度危险，随时Rug
    elif 5_000 <= mcap < 100_000:
        score += 10; breakdown["市值"] = +10  # 早期红利区
    elif 100_000 <= mcap < 1_000_000:
        score += 5;  breakdown["市值"] = +5   # 稳健区
    elif mcap > 10_000_000:
        score -= 5;  breakdown["市值"] = -5   # 也就是吃个鱼尾，爆发力弱

    # 池子厚度与健康度 (Liq / FDV)
    if liq > 0 and mcap > 0:
        ratio = liq / mcap
        if ratio < 0.05: # 池子太薄，大户跑不了，典型的貔貅特征
            score -= 15; breakdown["池子比"] = -15
        elif ratio > 0.15:
            score += 5;  breakdown["池子比"] = +5

    if liq < 10_000:
        score -= 10; breakdown["流动性"] = -10 # 池子太小

    # =========================================
    # 2. 筹码分布 (权重 30%) - ✅ 新增
    # =========================================
    # 需要从 token_data['top10_ratio'] 解析 "15.5%" 这种字符串
    top10_str = str(token_data.get("top10_ratio", "0")).replace("%", "")
    try:
        top10 = float(top10_str)
    except:
        top10 = 0

    if top10 > 50:
        score -= 30; breakdown["Top10控盘"] = -30 # 高度控盘，一波砸死
    elif top10 > 30:
        score -= 10; breakdown["Top10控盘"] = -10
    elif 0 < top10 < 15:
        score += 5;  breakdown["Top10分散"] = +5

    # =========================================
    # 3. GMGN 链上行为 (权重 40%) - 核心 Alpha
    # =========================================
    
    # 聪明钱 (Smart Money)
    if smart_count > 0:
        # 阶梯加分，哪怕只有1个也是好迹象
        pts = min(20, smart_count * 2) # 上限加20分
        score += pts
        breakdown[f"聪明钱({smart_count})"] = +pts
    
    # KOL (营销力度)
    if kol_count > 0:
        score += 5
        breakdown[f"KOL({kol_count})"] = +5

    # 老鼠仓 (Rat Farm) - 一票否决级
    if rat_count > 0:
        # 发现老鼠仓直接扣大分
        penalty = rat_count * 5
        score -= penalty
        breakdown[f"老鼠仓({rat_count})"] = -penalty

    # 捆绑交易 (Bundle)
    if bundle_count > 0:
        if bundle_count > 70:
            score -= 25; breakdown["严重捆绑"] = -25
        elif bundle_count > 30:
            score -= 10; breakdown["存在捆绑"] = -10

    # 狙击手 (Sniper) - 适度容忍
    if sniper_count > 80:
        score -= 10; breakdown["狙击过多"] = -10

    # =========================================
    # 4. 交易动能
    # =========================================
    vol = float(token_data.get("volume_h24", 0) or 0)
    if vol > liq * 3: # 换手极高
        score += 5; breakdown["高换手"] = +5
    
    drop_24h = float(token_data.get("price_change_24h", 0) or 0)
    if drop_24h < -50:
        score -= 10; breakdown["腰斩"] = -10

    # =========================================
    # 结算
    # =========================================
    score = max(0, min(100, int(score)))

    # 生成评语
    if score >= 85:
        summary = "🔥 <b>极品金狗</b>：聪明钱扎堆，结构完美"
    elif score >= 70:
        summary = "✅ <b>优质标的</b>：有些许瑕疵，但值得一冲"
    elif score >= 50:
        summary = "⚖️ <b>中规中矩</b>：观察为主，等待信号"
    elif score >= 30:
        summary = "⚠️ <b>高风险</b>：老鼠仓或控盘严重"
    else:
        summary = "☠️ <b>垃圾盘/Rug</b>：快跑！"

    return {
        "total": score,
        "breakdown": breakdown,
        "summary": summary
    }