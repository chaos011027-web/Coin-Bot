import asyncio
import os

from dotenv import load_dotenv

from modules.db_schema import migrate_database


async def upgrade_database():
    load_dotenv()
    await migrate_database()


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(upgrade_database())
