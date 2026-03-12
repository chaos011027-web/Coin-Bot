import asyncio
import os
import csv
import sys
import aiohttp
import asyncpg
from dotenv import load_dotenv

# Windows / 管道输出统一转 UTF-8，避免 emoji 导致 gbk 崩溃
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


async def fetch_token_current_price(ca: str) -> float:
    """调用 DexScreener API 极速查现价，用于判定最终胜负"""
    url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        return float(pairs[0].get("priceUsd", 0))
    except Exception as e:
        print(f"[WARN] 查价失败 {ca}: {e}")
    return 0.0


async def run_midnight_hunter():
    print("[Midnight Hunter] 已启动。")
    load_dotenv()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")

    if not db_url:
        print("[ERROR] 找不到数据库连接配置，请检查 .env")
        return

    conn = await asyncpg.connect(db_url)

    try:
        # ==========================================
        # 第一阶段：自动阅卷 (Labeling)
        # ==========================================
        unlabeled_records = await conn.fetch(
            "SELECT ca, price_usd, snapshot_time FROM golden_dog_morphology WHERE label = -1"
        )
        print(f"[INFO] 发现 {len(unlabeled_records)} 条未打标的特征快照，准备进行胜负判定。")

        labeled_count = 0
        for row in unlabeled_records:
            ca = row["ca"]
            entry_price = float(row["price_usd"] or 0)

            if entry_price <= 0:
                print(f"  [-] 历史遗留无价格数据，直接标为失效样本 (CA: {ca[:6]})")
                await conn.execute(
                    "UPDATE golden_dog_morphology SET label = 0 WHERE ca = $1 AND snapshot_time = $2",
                    ca,
                    row["snapshot_time"],
                )
                labeled_count += 1
                continue

            curr_price = await fetch_token_current_price(ca)
            if curr_price <= 0:
                print(f"  [-] DexScreener 未收录或无价格，跳过 (CA: {ca[:6]})")
                continue

            if curr_price >= entry_price * 1.3:
                label = 1
                profit_pct = ((curr_price / entry_price) - 1) * 100
                print(f"  [+] 金狗确立! CA: {ca[:6]}... | 涨幅: +{profit_pct:.1f}%")
            else:
                label = 0
                print(f"  [-] 淘汰/死盘! CA: {ca[:6]}")

            await conn.execute(
                "UPDATE golden_dog_morphology SET label = $1 WHERE ca = $2 AND snapshot_time = $3",
                label,
                ca,
                row["snapshot_time"],
            )
            labeled_count += 1

            await asyncio.sleep(0.5)

        if labeled_count > 0:
            print(f"[OK] 成功为 {labeled_count} 条记录打上胜负标签。")

        # ==========================================
        # 第二阶段：数据榨汁 (Export CSV)
        # ==========================================
        print("[INFO] 正在提取全量结构化数据，生成 LightGBM 训练集。")

        all_data = await conn.fetch(
            "SELECT * FROM golden_dog_morphology WHERE label != -1 ORDER BY snapshot_time DESC"
        )

        if all_data:
            keys = list(all_data[0].keys())
            csv_filename = "ml_training_dataset.csv"

            with open(csv_filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                for d in all_data:
                    row_dict = {}
                    for k in keys:
                        val = d.get(k)
                        if isinstance(val, (dict, list)):
                            row_dict[k] = str(val)
                        else:
                            row_dict[k] = val
                    writer.writerow(row_dict)

            print(f"[OK] 训练集 [{csv_filename}] 已在根目录生成。")
        else:
            print("[WARN] 数据库中目前还没有有效打标的数据，无法生成 CSV。")

    except Exception as e:
        print(f"[ERROR] 运行失败: {e}")
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_midnight_hunter())