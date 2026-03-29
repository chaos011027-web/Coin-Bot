import asyncio
import os

from dotenv import load_dotenv

from modules.db_schema import migrate_database


async def upgrade_database():
    load_dotenv()
    dsn = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    await migrate_database(dsn)


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(upgrade_database())
