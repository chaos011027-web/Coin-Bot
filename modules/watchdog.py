import asyncio
import logging
import json
from modules.database import db
from modules.data_fetcher import get_market_data, get_gmgn_analytics
from modules.feature_engine import calculate_ml_features

logger = logging.getLogger("WatchDog")


def _extract_prev_smart_from_snapshot(prev_snap: dict) -> int:
    if not prev_snap:
        return 0

    social_str = prev_snap.get("social_signal")
    if not social_str:
        return 0

    try:
        social_dict = json.loads(social_str) if isinstance(social_str, str) else social_str
        ix_data = social_dict.get("ix_data", {}) or {}

        # 兼容两种可能的存法
        if "smart_money_count" in ix_data:
            return int(ix_data.get("smart_money_count") or 0)
        if "smart_money" in ix_data:
            return int(ix_data.get("smart_money") or 0)
    except Exception:
        pass

    return 0


async def time_series_patrol_loop():
    """
    时序巡逻犬：每隔 5 分钟巡视一次特征库，
    记录代币的 T_WIP 状态。一旦发现聪明钱异动，直接触发预警。
    """
    logger.info("🐕‍🦺 蛰伏巡逻兵 (Watchdog) 已启动，开始监控多重时间线...")

    while True:
        try:
            records = await db.fetch("""
                SELECT DISTINCT ca
                FROM golden_dog_morphology
                WHERE snapshot_time > NOW() - INTERVAL '4 hours'
            """)

            for row in records:
                ca = row["ca"]

                raw_market = await get_market_data(ca)
                analytics = await get_gmgn_analytics(ca)
                if not raw_market or not analytics:
                    continue

                # 取最新一条快照，而不是最早一条
                prev_snap = await db.fetchrow("""
                    SELECT *
                    FROM golden_dog_morphology
                    WHERE ca = $1
                    ORDER BY snapshot_time DESC
                    LIMIT 1
                """, ca)
                if not prev_snap:
                    continue

                prev_smart = _extract_prev_smart_from_snapshot(prev_snap)
                prev_data = {"smart_money": prev_smart}

                features = calculate_ml_features(raw_market, analytics, prev_data)

                curr_price = float(raw_market.get("priceUsd") or raw_market.get("price_usd") or 0)
                curr_mcap = float(
                    raw_market.get("fdv")
                    or raw_market.get("marketCap")
                    or raw_market.get("cap_usd")
                    or raw_market.get("mcap")
                    or 0
                )

                curr_liq = raw_market.get("liquidity_usd")
                if not curr_liq and isinstance(raw_market.get("liquidity"), dict):
                    curr_liq = raw_market.get("liquidity", {}).get("usd")
                curr_liq = float(curr_liq or 0)

                holders = analytics.get("top10_ratio", "N/A")
                current_smart_abs = prev_smart + int(features.get("smart_money_delta", 0))

                if curr_price <= 0:
                    continue

                await db.execute("""
                    INSERT INTO golden_dog_morphology
                    (
                        ca,
                        snapshot_time,
                        time_stage,
                        market_cap_at_snap,
                        liquidity_at_snap,
                        holder_distribution,
                        social_signal,
                        price_usd,
                        smart_money_delta,
                        maker_vol_ratio,
                        overhang_ratio,
                        breakout_vol_ratio
                    )
                    VALUES
                    (
                        $1,
                        NOW(),
                        'T_WIP',
                        $2,
                        $3,
                        $4,
                        $5,
                        $6,
                        $7,
                        $8,
                        $9,
                        $10
                    )
                    ON CONFLICT (ca, snapshot_time) DO NOTHING
                """,
                    ca,
                    curr_mcap,
                    curr_liq,
                    json.dumps({"top10": holders}, ensure_ascii=False),
                    json.dumps({"ix_data": {"smart_money_count": current_smart_abs}}, ensure_ascii=False),
                    curr_price,
                    int(features.get("smart_money_delta", 0)),
                    float(features.get("maker_vol_ratio", 0)),
                    float(features.get("overhang_ratio", 0)),
                    float(features.get("breakout_vol_ratio", 0)),
                )

                prev_price = float(prev_snap.get("price_usd") or 0)
                if prev_price > 0 and curr_price < prev_price and int(features.get("smart_money_delta", 0)) >= 5:
                    logger.warning(
                        f"🎯 [二浪预警] {ca} 价格洗盘但聪明钱悄悄增仓 (+{features['smart_money_delta']})，极速追踪！"
                    )

        except Exception as e:
            logger.error(f"Watchdog 巡逻异常: {e}", exc_info=True)

        await asyncio.sleep(300)