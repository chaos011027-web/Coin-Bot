import asyncio
import os
import asyncpg
from dotenv import load_dotenv

async def upgrade_database():
    print("🛠️ 开始对数据库进行 [时序化与特征扩展] 改造...")
    load_dotenv()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    
    conn = await asyncpg.connect(db_url)
    
    try:
        # 1. 解除原来的单一主键约束 (假设原来的主键名叫 golden_dog_morphology_pkey)
        print("1. 正在解除单一 CA 唯一约束...")
        await conn.execute("""
            ALTER TABLE golden_dog_morphology DROP CONSTRAINT IF EXISTS golden_dog_morphology_pkey CASCADE;
            ALTER TABLE golden_dog_morphology DROP CONSTRAINT IF EXISTS golden_dog_morphology_ca_key CASCADE;
        """)

        # 2. 增加时间序列复合主键 (同一个币在不同时间可以有多条记录)
        print("2. 正在建立 (CA, snapshot_time) 时序复合主键...")
        await conn.execute("""
            ALTER TABLE golden_dog_morphology 
            ADD PRIMARY KEY (ca, snapshot_time);
        """)

        # 3. 增加高阶特征字段 (LightGBM 训练用的 Features)
        print("3. 正在扩充高阶特征字段库...")
        new_columns = [
            ("time_stage", "VARCHAR(20) DEFAULT 'T_0'"),          # 标记这是开盘、T+15m还是T+1h的数据
            ("price_usd", "FLOAT DEFAULT 0"),                     # 当时的价格
            ("smart_money_delta", "INT DEFAULT 0"),               # 聪明钱相比上一次的净变化
            ("maker_vol_ratio", "FLOAT DEFAULT 0"),               # 独立买家/交易量 (防刷量)
            ("overhang_ratio", "FLOAT DEFAULT 0"),                # 悬空筹码比 (防软跑路)
            ("breakout_vol_ratio", "FLOAT DEFAULT 0"),            # 突破量能比 (防假突破)
            ("label", "INT DEFAULT -1")                           # 机器学习标签 (1=大赚, 0=亏损, -1=未打标)
        ]
        
        for col_name, col_type in new_columns:
            try:
                await conn.execute(f"ALTER TABLE golden_dog_morphology ADD COLUMN {col_name} {col_type};")
                print(f"  [+] 新增字段: {col_name}")
            except asyncpg.exceptions.DuplicateColumnError:
                pass # 字段已存在则跳过

        print("✅ 数据库架构升级完成！现在它支持存储时间序列快照了。")
    except Exception as e:
        print(f"💥 升级失败: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(upgrade_database())