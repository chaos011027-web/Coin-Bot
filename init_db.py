import asyncio
import os

from dotenv import load_dotenv

from modules.db_schema import migrate_database


async def init_tables():
    load_dotenv()
    print("Initializing unified database schema...")
    await migrate_database()
    print("Schema ready.")
    print("Authority: modules.db_schema.ensure_schema / migrate_database")
    print("Tables: tokens_meta, signal_cache_current, signal_snapshots, performance_labels, golden_dog_morphology, smart_wallet_intel, wallet_clusters")
    print("Compatibility view: signals_snapshot")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(init_tables())
