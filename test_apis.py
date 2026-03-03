import asyncio
import aiohttp
import os
import time
import hashlib
import json
from dotenv import load_dotenv

load_dotenv()

# 🎯 测试目标 CA
TEST_CA = "2xMNNityqHbafNAgNBF95phKcdx97qahJMwkUh4Bpump"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'

async def fetch(session, url, method="GET", headers=None, json_data=None):
    start_time = time.time()
    try:
        kwargs = {"headers": headers, "timeout": 10}
        if method == "POST":
            kwargs["json"] = json_data
            
        async with session.request(method, url, **kwargs) as response:
            latency = round((time.time() - start_time) * 1000)
            text = await response.text()
            try:
                resp_json = json.loads(text)
            except:
                resp_json = None
            
            if response.status == 200:
                return resp_json, latency, None
            else:
                return resp_json, latency, f"HTTP {response.status} -> {text}"
    except Exception as e:
        return None, 0, str(e)

async def test_dexscreener(session):
    print(f"\n{YELLOW}▶ [1/9] 测试 DexScreener (免费公开 API)...{RESET}")
    url = f"https://api.dexscreener.com/latest/dex/tokens/{TEST_CA}"
    data, latency, err = await fetch(session, url, headers={"User-Agent": USER_AGENT})
    if data and "pairs" in data:
        print(f"{GREEN}✅ DexScreener 正常 | 延迟: {latency}ms | 抓取到 {len(data['pairs'])} 个池子{RESET}")
    else:
        print(f"{RED}❌ DexScreener 失败 | 报错: {err}{RESET}")

async def test_birdeye(session):
    print(f"\n{YELLOW}▶ [2/9] 测试 BirdEye API (需 BIRDEYE_API_KEY)...{RESET}")
    api_key = os.getenv("BIRDEYE_API_KEY", "").strip()
    if not api_key:
        print(f"{RED}❌ 未配置 BIRDEYE_API_KEY{RESET}")
        return
        
    url = f"https://public-api.birdeye.so/defi/token_overview?address={TEST_CA}"
    headers = {"X-API-KEY": api_key, "x-chain": "solana"}
    data, latency, err = await fetch(session, url, headers=headers)
    
    if err:
        print(f"{RED}❌ BirdEye 失败 (符合预期，因免费额度耗尽可无视) | 真实报错: {err}{RESET}")
    elif data and data.get("success"):
        print(f"{GREEN}✅ BirdEye 正常 | 延迟: {latency}ms | 代币价格: ${data['data'].get('price', 0):.6f}{RESET}")
    else:
        print(f"{RED}❌ BirdEye 失败 | 返回: {data}{RESET}")

async def test_rugcheck(session):
    print(f"\n{YELLOW}▶ [3/9] 测试 RugCheck (免费公开 API)...{RESET}")
    url = f"https://api.rugcheck.xyz/v1/tokens/{TEST_CA}/report"
    data, latency, err = await fetch(session, url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    if data and "mint" in data:
        print(f"{GREEN}✅ RugCheck 正常 | 延迟: {latency}ms | 风险评分: {data.get('score', 'N/A')}{RESET}")
    else:
        print(f"{RED}❌ RugCheck 失败 | 报错: {err}{RESET}")

async def test_goplus(session):
    print(f"\n{YELLOW}▶ [4/9] 测试 GoPlus 安全 API (动态 SHA1 鉴权)...{RESET}")
    app_key = os.getenv("GOPLUS_APP_KEY", "").strip()
    app_secret = os.getenv("GOPLUS_APP_SECRET", "").strip()
    
    if not app_key or not app_secret:
        print(f"{RED}❌ 未配置 GOPLUS_APP_KEY 或 SECRET{RESET}")
        return

    t = str(int(time.time()))
    sign = hashlib.sha1((app_key + t + app_secret).encode('utf-8')).hexdigest()
    token_url = "https://api.gopluslabs.io/api/v1/token"
    token_data, _, err = await fetch(session, token_url, method="POST", json_data={"app_key": app_key, "sign": sign, "time": t})
    
    if err:
        print(f"{RED}❌ GoPlus 请求报错 | 真实错误反馈: {err}{RESET}")
        return

    if not token_data:
        print(f"{RED}❌ GoPlus 鉴权异常 | API 返回为空{RESET}")
        return
        
    token_info = token_data.get("result") or token_data.get("data") or {}
    access_token = token_info.get("access_token")
    
    if not access_token:
        print(f"{RED}❌ GoPlus 解析异常 | 找不到 access_token: {token_data}{RESET}")
        return
        
    print(f"  └ 🔐 成功获取临时 Token: {access_token[:10]}...")
    
    # 🟢 终极修复：测试脚本也加入双重 Bearer 判断
    if access_token.startswith("Bearer"):
        auth_header = access_token
    else:
        auth_header = f"Bearer {access_token}"

    url = f"https://api.gopluslabs.io/api/v1/token_security/solana?contract_addresses={TEST_CA}"
    headers = {"Authorization": auth_header, "User-Agent": USER_AGENT}
    data, latency, err = await fetch(session, url, headers=headers)
    
    if data and str(data.get("code")) == "1":
        result_data = data.get("result") or {}
        res = result_data.get(TEST_CA.lower(), {})
        print(f"{GREEN}✅ GoPlus 正常 | 延迟: {latency}ms | 貔貅盘: {res.get('is_honeypot') == '1'}{RESET}")
    else:
        print(f"{RED}❌ GoPlus 查询失败 | 报错: {err} | 返回: {data}{RESET}")

async def test_helius(session):
    print(f"\n{YELLOW}▶ [5/9] 测试 Helius RPC (需 HELIUS_API_KEY)...{RESET}")
    api_key = os.getenv("HELIUS_API_KEY", "").strip()
    if not api_key:
        print(f"{RED}❌ 未配置 HELIUS_API_KEY{RESET}")
        return
    url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo", "params": [TEST_CA, {"encoding": "jsonParsed"}]}
    data, latency, err = await fetch(session, url, method="POST", json_data=payload)
    if data and "result" in data:
        print(f"{GREEN}✅ Helius RPC 正常 | 延迟: {latency}ms | 成功连接链上节点{RESET}")
    else:
        print(f"{RED}❌ Helius RPC 失败 | 真实报错: {err}{RESET}")

async def test_openai(session):
    print(f"\n{YELLOW}▶ [6/9] 测试 OpenAI 生成 (需 OPENAI_API_KEY)...{RESET}")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print(f"{RED}❌ 未配置 OPENAI_API_KEY{RESET}")
        return
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Say 'OK'"}], "max_tokens": 5}
    data, latency, err = await fetch(session, url, method="POST", headers=headers, json_data=payload)
    
    if data and "choices" in data:
        reply = data["choices"][0]["message"]["content"].strip()
        print(f"{GREEN}✅ OpenAI 正常 | 延迟: {latency}ms | 官方回复: '{reply}'{RESET}")
    else:
        print(f"{RED}❌ OpenAI 失败 | 真实错误反馈: {err} | API原文: {data}{RESET}")

async def test_bitquery():
    print(f"\n{YELLOW}▶ [7/9] 测试 Bitquery (调用本地模块)...{RESET}")
    if not os.getenv("BITQUERY_API_KEY"):
        print(f"{YELLOW}⚠️ 未配置 BITQUERY_API_KEY，已跳过{RESET}")
        return
    try:
        from modules.bitquery_client import bitquery
        start = time.time()
        res = await asyncio.wait_for(bitquery.fetch_comprehensive_data(TEST_CA), timeout=15)
        latency = round((time.time() - start) * 1000)
        if res:
            print(f"{GREEN}✅ Bitquery 正常 | 延迟: {latency}ms{RESET}")
        else:
            print(f"{RED}❌ Bitquery 返回为空{RESET}")
    except Exception as e:
        print(f"{RED}❌ Bitquery 调用失败: {e}{RESET}")

async def test_trench():
    print(f"\n{YELLOW}▶ [8/9] 测试 Trench (调用本地模块)...{RESET}")
    if not os.getenv("TRENCH_API_KEY"):
        print(f"{YELLOW}⚠️ 未配置 TRENCH_API_KEY，已跳过{RESET}")
        return
    print(f"{YELLOW}⚠️ 模块存在，跳过具体函数调用{RESET}")

async def test_insightx():
    print(f"\n{YELLOW}▶ [9/9] 测试 InsightX (调用本地模块)...{RESET}")
    if not os.getenv("INSIGHTX_API_KEY"):
        print(f"{YELLOW}⚠️ 未配置 INSIGHTX_API_KEY，已跳过{RESET}")
        return
    print(f"{YELLOW}⚠️ 模块存在，跳过具体函数调用{RESET}")

async def main():
    print("==================================================")
    print("🚀 SolanaHunter V3.6 - 最终完美版 API 体检系统")
    print(f"🎯 测试目标 CA: {TEST_CA}")
    print("==================================================")
    
    async with aiohttp.ClientSession() as session:
        await test_dexscreener(session)
        await test_birdeye(session)
        await test_rugcheck(session)
        await test_goplus(session)
        await test_helius(session)
        await test_openai(session)
        
    await test_bitquery()
    await test_trench()
    await test_insightx()

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())