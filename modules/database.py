import asyncpg
import logging
import os
import json
from typing import List, Dict, Any, Optional

logger = logging.getLogger("Database")

class Database:
    _pool = None

    @classmethod
    async def init_pool(cls):
        """初始化连接池"""
        if cls._pool:
            return
        
        # ✅ 核心修改：设定默认的 PostgreSQL 连接字符串 (包含您的密码 011027 和库名 solana_hunter)
        dsn = os.getenv("DB_DSN", "postgresql://postgres:011027@localhost:5432/solana_hunter")

        try:
            # 创建连接池
            cls._pool = await asyncpg.create_pool(dsn, min_size=5, max_size=20)
            logger.info("✅ 数据库连接池已启动 (PostgreSQL: solana_hunter)")
            
            # 初始化与升级表结构
            await cls._setup_tables()
            
        except Exception as e:
            logger.critical(f"❌ 数据库连接失败: {e}")
            raise e

    @classmethod
    async def _setup_tables(cls):
        """自动创建或无损更新表结构（打牢状态化缓存的地基）"""
        try:
            # 1. 确保基础表存在
            create_table_query = """
            CREATE TABLE IF NOT EXISTS signals_snapshot (
                ca VARCHAR(255) PRIMARY KEY,
                source VARCHAR(255),
                status VARCHAR(50),
                rank_score FLOAT,
                ai_narrative TEXT
            );
            """
            await cls.execute(create_table_query)
            
            # 2. 动态追加盖楼与缓存所需的新字段 (IF NOT EXISTS 保证数据无损)
            alter_queries = [
                "ALTER TABLE signals_snapshot ADD COLUMN IF NOT EXISTS entry_price FLOAT;",
                "ALTER TABLE signals_snapshot ADD COLUMN IF NOT EXISTS last_notified_price FLOAT;",
                "ALTER TABLE signals_snapshot ADD COLUMN IF NOT EXISTS initial_msg_id BIGINT;",
                "ALTER TABLE signals_snapshot ADD COLUMN IF NOT EXISTS terminal_states JSONB;"
            ]
            for query in alter_queries:
                await cls.execute(query)
                
            logger.info("✅ 数据库表结构校验完毕：增量缓存字段已就绪")
        except Exception as e:
            logger.error(f"⚠️ 校验表结构时发生异常 (不影响主流程): {e}")

    @classmethod
    async def close_pool(cls):
        """关闭连接池"""
        if cls._pool:
            await cls._pool.close()
            logger.info("🛑 数据库连接池已关闭")

    @classmethod
    async def fetch_one(cls, query: str, *args) -> Optional[Dict[str, Any]]:
        """查询单条记录"""
        if not cls._pool: await cls.init_pool()
        async with cls._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    @classmethod
    async def fetch_all(cls, query: str, *args) -> List[Dict[str, Any]]:
        """查询多条记录"""
        if not cls._pool: await cls.init_pool()
        async with cls._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    @classmethod
    async def execute(cls, query: str, *args) -> str:
        """执行插入/更新/删除"""
        if not cls._pool: await cls.init_pool()
        async with cls._pool.acquire() as conn:
            return await conn.execute(query, *args)

    # ========================================================
    # 🟢 新增：专为“状态化增量缓存”与“防伪战报”设计的核心函数
    # ========================================================

    @classmethod
    async def save_initial_signal(cls, ca: str, source: str, entry_price: float, initial_msg_id: int, terminal_states: dict):
        """保存首次监听到的代币信息及静态缓存"""
        query = """
            INSERT INTO signals_snapshot 
                (ca, source, status, entry_price, last_notified_price, initial_msg_id, terminal_states)
            VALUES 
                ($1, $2, 'analyzed', $3, $3, $4, $5::jsonb)
            ON CONFLICT (ca) DO UPDATE 
            SET entry_price = EXCLUDED.entry_price,
                last_notified_price = EXCLUDED.last_notified_price,
                initial_msg_id = EXCLUDED.initial_msg_id,
                terminal_states = EXCLUDED.terminal_states
        """
        await cls.execute(query, ca, source, entry_price, initial_msg_id, json.dumps(terminal_states))

    @classmethod
    async def get_signal_snapshot(cls, ca: str) -> Optional[Dict[str, Any]]:
        """光速获取代币的快照缓存信息 (用于增量 AI 分析和战报校验)"""
        query = "SELECT * FROM signals_snapshot WHERE ca = $1"
        row = await cls.fetch_one(query, ca)
        if row and row.get('terminal_states'):
            # 自动将 JSON 字符串反序列化为字典
            try:
                if isinstance(row['terminal_states'], str):
                    row['terminal_states'] = json.loads(row['terminal_states'])
            except Exception:
                row['terminal_states'] = {}
        return row

    @classmethod
    async def update_milestone(cls, ca: str, new_price: float):
        """触发涨幅战报后，更新 last_notified_price 锚点"""
        query = "UPDATE signals_snapshot SET last_notified_price = $1 WHERE ca = $2"
        await cls.execute(query, float(new_price), ca)
        
    @classmethod
    async def update_terminal_states(cls, ca: str, terminal_states: dict):
        """更新静态缓存 (例如：起初没烧池子，几分钟后烧了，变成不可逆终态，存入库中)"""
        query = "UPDATE signals_snapshot SET terminal_states = $1::jsonb WHERE ca = $2"
        await cls.execute(query, json.dumps(terminal_states), ca)

# 全局单例
db = Database