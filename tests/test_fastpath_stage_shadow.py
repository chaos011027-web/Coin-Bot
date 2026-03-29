import asyncio
import time

import pytest

import main
from modules.data_fetcher import DataFetcher


def _make_fetcher():
    fetcher = DataFetcher.__new__(DataFetcher)
    fetcher._existing_avatar_path = lambda ca: ""
    fetcher._normalize_image_url = lambda url: str(url or "").strip()
    fetcher._normalize_avatar_source = lambda source, url="": str(source or "").strip().lower()
    fetcher._should_probe_pump = lambda ca, token_data=None: False
    fetcher.helius_rpc_url = "https://rpc.example.invalid"
    return fetcher


@pytest.mark.asyncio
async def test_stage1_shadow_uses_ultra_fast_sources_only():
    fetcher = _make_fetcher()
    created_at_ms = int((time.time() - 900) * 1000)

    async def fake_fetch_dexscreener(ca):
        return {
            "pairs": [
                {
                    "liquidity": {"usd": 1500},
                    "baseToken": {"symbol": "AAA", "name": "Alpha", "logoURI": "https://dex.example/logo.png"},
                    "priceUsd": "0.001",
                    "marketCap": 123456,
                    "volume": {"h24": 9876},
                    "txns": {"h24": {"buys": 10, "sells": 5}},
                    "pairCreatedAt": created_at_ms,
                    "pairAddress": "PAIR123",
                    "dexId": "raydium",
                    "info": {},
                }
            ]
        }

    async def fake_metadata_bundle(ca):
        return {
            "symbol": "ALPHA",
            "name": "Alpha Token",
            "token_image_url": "https://meta.example/logo.png",
            "token_image_source": "metadata",
        }

    async def fake_basic_rpc(ca):
        return {
            "supply_raw": 1000000000,
            "supply_ui": 1000.0,
            "largest_accounts_present": True,
            "largest_accounts_sample_count": 20,
            "top10_ratio": None,
            "top10_ratio_source": "",
            "top10_ratio_pending_exclusion_filter": True,
        }

    fetcher._fetch_dexscreener = fake_fetch_dexscreener
    fetcher._fetch_helius_metadata_bundle = fake_metadata_bundle
    fetcher._fetch_basic_rpc_supply_snapshot = fake_basic_rpc
    fetcher.fetch_rugcheck_data = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("stage1 must not call RugCheck")
    )
    fetcher.fetch_goplus_security = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("stage1 must not call GoPlus")
    )
    fetcher._fetch_rpc_holder_top10_finalize_shadow = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("stage1 must not finalize top10")
    )

    result = await DataFetcher.get_token_info_stage1_shadow(fetcher, "So11111111111111111111111111111111111111112")

    assert result["fastpath_shadow_stage"] == "stage1_ultra_fast"
    assert result["slow_followup_required"] is True
    assert result["market_data_ready"] is True
    assert result["liquidity_data_ready"] is True
    assert result["top10_ratio"] is None
    assert result["top10_ratio_source"] == ""
    assert result["top10_ratio_pending_exclusion_filter"] is True
    assert result["lp_status_phase"] == "amm_pool_phase"
    assert result["stage1_source_status"] == {"dex": "ok", "metadata": "ok", "basic_rpc": "ok"}
    assert result["stage1_partial_degraded"] is False


@pytest.mark.asyncio
async def test_stage1_shadow_isolates_metadata_timeout_without_losing_dex_and_basic_rpc():
    fetcher = _make_fetcher()
    created_at_ms = int((time.time() - 900) * 1000)

    async def fake_fetch_dexscreener(ca):
        return {
            "pairs": [
                {
                    "liquidity": {"usd": 2400},
                    "baseToken": {"symbol": "AAA", "name": "Alpha", "logoURI": "https://dex.example/logo.png"},
                    "priceUsd": "0.002",
                    "marketCap": 220000,
                    "volume": {"h24": 12345},
                    "txns": {"h24": {"buys": 12, "sells": 6}},
                    "pairCreatedAt": created_at_ms,
                    "pairAddress": "PAIRXYZ",
                    "dexId": "raydium",
                    "info": {},
                }
            ]
        }

    async def fake_metadata_bundle(ca):
        raise asyncio.TimeoutError()

    async def fake_basic_rpc(ca):
        return {
            "supply_raw": 1000000000,
            "supply_ui": 1000.0,
            "largest_accounts_present": True,
            "largest_accounts_sample_count": 20,
            "top10_ratio": None,
            "top10_ratio_source": "",
            "top10_ratio_pending_exclusion_filter": True,
        }

    fetcher._fetch_dexscreener = fake_fetch_dexscreener
    fetcher._fetch_helius_metadata_bundle = fake_metadata_bundle
    fetcher._fetch_basic_rpc_supply_snapshot = fake_basic_rpc

    result = await DataFetcher.get_token_info_stage1_shadow(fetcher, "So11111111111111111111111111111111111111112")

    assert result["symbol"] == "AAA"
    assert result["name"] == "Alpha"
    assert result["token_image_url"] == "https://dex.example/logo.png"
    assert result["largest_accounts_present"] is True
    assert result["top10_ratio_pending_exclusion_filter"] is True
    assert result["stage1_source_status"]["dex"] == "ok"
    assert result["stage1_source_status"]["metadata"] == "timeout"
    assert result["stage1_source_status"]["basic_rpc"] == "ok"
    assert result["stage1_partial_degraded"] is True
    assert any(item.startswith("metadata:") for item in result["stage1_source_errors"])


@pytest.mark.asyncio
async def test_stage2_shadow_isolates_rugcheck_failure_without_losing_goplus_and_top10():
    fetcher = _make_fetcher()

    async def fake_rugcheck(ca):
        raise RuntimeError("rugcheck temporary failure")

    async def fake_goplus(ca):
        return {
            "is_honeypot": False,
            "is_blacklisted": False,
            "is_mintable": False,
            "transfer_pausable": False,
        }

    async def fake_top10_finalize(ca, known_exclude_owners=None):
        return {
            "top10_ratio": "12.34%",
            "top10_ratio_source": "SOLANA_RPC",
            "top10_ratio_pending_exclusion_filter": False,
            "top10_finalize_reason": "owner_aggregate_after_exclusion",
        }

    fetcher.fetch_rugcheck_data = fake_rugcheck
    fetcher.fetch_goplus_security = fake_goplus
    fetcher._fetch_rpc_holder_top10_finalize_shadow = fake_top10_finalize

    result = await DataFetcher.get_token_info_stage2_shadow(
        fetcher,
        "So11111111111111111111111111111111111111112",
        stage1_payload={
            "lp_status_phase": "amm_pool_phase",
            "lp_status_source": "dex_pair",
            "lp_status_confidence": 0.72,
            "lp_status_reason": "AMM pair detected, but LP burn/lock still pending slow-source validation",
            "top10_ratio_pending_exclusion_filter": True,
        },
        known_exclude_owners={"burn111111111111111111111111111111111111"},
    )

    assert result["stage2_source_status"]["rugcheck"] == "error"
    assert result["stage2_source_status"]["goplus"] == "ok"
    assert result["stage2_source_status"]["top10_finalize"] == "ok"
    assert result["stage2_partial_degraded"] is True
    assert result["is_honeypot"] is False
    assert result["is_blacklisted"] is False
    assert result["top10_ratio"] == "12.34%"
    assert result["top10_ratio_source"] == "SOLANA_RPC"
    assert result["top10_ratio_pending_exclusion_filter"] is False


@pytest.mark.asyncio
async def test_main_stage1_shadow_clears_bool_lp_fields(monkeypatch):
    async def fake_stage1(ca):
        return {
            "symbol": "AAA",
            "name": "Alpha",
            "price_usd": 0.01,
            "cap_usd": 120000,
            "pair_liquidity_usd": 5000,
            "liquidity_usd": 5000,
            "market_data_ready": True,
            "liquidity_data_ready": True,
            "is_burned": True,
            "is_locked": False,
            "lp_burned_pct": None,
            "lp_locked_pct": None,
            "lp_status_source": "stage1_ultra_fast",
            "lp_status_confidence": 0.25,
            "lp_status_reason": "slow LP sources not queried yet",
            "lp_status_phase": "unknown",
            "lp_status_phase_conflict": False,
            "lp_status_source_conflict": False,
            "lp_status_conflict_reason": "",
            "top10_ratio": None,
            "top10_ratio_source": "",
            "top10_ratio_pending_exclusion_filter": True,
            "fastpath_shadow_stage": "stage1_ultra_fast",
            "slow_followup_required": True,
            "stage1_source_status": {"dex": "ok", "metadata": "ok", "basic_rpc": "ok"},
            "stage1_source_errors": [],
            "stage1_partial_degraded": False,
        }

    monkeypatch.setattr(main.fetcher, "get_token_info_stage1_shadow", fake_stage1)

    result = await main.fetch_token_info_fastpath_stage1_shadow(
        "So11111111111111111111111111111111111111112",
        "SYSTEM",
        321,
        654,
    )

    assert "is_burned" not in result
    assert "is_locked" not in result
    assert "liquidity_locked" not in result
    assert result["lp_status_phase"] == "unknown"
    assert result["top10_ratio_pending_exclusion_filter"] is True
    assert result["canonical_metadata"]["fastpath_mode"] == "api_rpc_ultra_fast_stage1"
