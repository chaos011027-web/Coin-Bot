import asyncio
import os
from dotenv import load_dotenv
from modules.database import db

# 加载环境变量
load_dotenv()

async def init_tables():
    print("🚀 正在初始化数据库表结构...")
    
    try:
        await db.init_pool()
        
        # 1. 代币基础表 (tokens_meta)
        # 用于缓存代币的基础信息，避免重复查 DexScreener/Helius
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tokens_meta (
                ca TEXT PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                decimals INT DEFAULT 9,
                security_flags JSONB,  -- 存 {is_mintable: true, is_locked: false...}
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        print("✅ tokens_meta 表就绪")

        # 2. 信号快照表 (signals_snapshot)
        # 记录每次推送时的原始数据，用于 AI 训练和回测
        await db.execute("""
            CREATE TABLE IF NOT EXISTS signals_snapshot (
                id SERIAL PRIMARY KEY,
                ca TEXT REFERENCES tokens_meta(ca),
                trigger_time TIMESTAMP DEFAULT NOW(),
                source TEXT,         -- 来源: 'DexScreener', 'Pump', 'UserQuery'
                rank_score FLOAT,    -- 当时的评分
                features JSONB,      -- 存当时的 {mcap, liquidity, top10, sniper_cnt...}
                ai_narrative TEXT,   -- 存 AI 给出的理由
                status TEXT DEFAULT 'pending' -- pending/analyzed
            );
        """)
        print("✅ signals_snapshot 表就绪")

        # 3. 表现回溯表 (performance_labels)
        # 记录信号发出后 1h/6h/24h 的真实涨幅，用于判断是否是金狗
        await db.execute("""
            CREATE TABLE IF NOT EXISTS performance_labels (
                signal_id INT REFERENCES signals_snapshot(id),
                max_pnl_1h FLOAT,
                max_pnl_6h FLOAT,
                max_pnl_24h FLOAT,
                is_winner BOOLEAN DEFAULT FALSE, -- 是否达到金狗标准
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(signal_id)
            );
        """)
        print("✅ performance_labels 表就绪")

        print("\n🎉 数据库初始化全部完成！")

    except Exception as e:
        print(f"\n❌ 初始化失败: {e}")
    finally:
        await db.close_pool()

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(init_tables())