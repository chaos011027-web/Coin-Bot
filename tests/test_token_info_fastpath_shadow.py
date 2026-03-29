import time

import pytest

import main
from modules.data_fetcher import DataFetcher


def _make_fetcher():
    fetcher = DataFetcher.__new__(DataFetcher)
    fetcher._log_avatar_trace = lambda *args, **kwargs: None
    fetcher._existing_avatar_path = lambda ca: ""
    fetcher._normalize_image_url = lambda url: str(url or "").strip()
    fetcher._normalize_avatar_source = lambda source, url="": str(source or "").strip().lower()
    return fetcher


@pytest.mark.asyncio
async def test_get_token_info_fastpath_keeps_weak_liquidity_out_of_first_card():
    fetcher = _make_fetcher()
    created_at_ms = int((time.time() - 3600) * 1000)

    async def fake_fetch_dexscreener(ca):
        return {
            "pairs": [
                {
                    "liquidity": {"usd": 5.16},
                    "baseToken": {"symbol": "AAA", "name": "Alpha", "logoURI": "https://dex.example/logo.png"},
                    "priceUsd": "0.001",
                    "marketCap": 123456,
                    "volume": {"h24": 9876},
                    "txns": {"h24": {"buys": 10, "sells": 5}},
                    "pairCreatedAt": created_at_ms,
                    "info": {},
                }
            ]
        }

    async def fake_rpc_holder_snapshot(ca):
        return {
            "top10_ratio": None,
            "top10_ratio_source": "",
            "top10_ratio_pending_exclusion_filter": True,
            "holder_count_estimate": 10,
        }

    async def fake_metadata_bundle(ca):
        return {
            "symbol": "ALPHA",
            "name": "Alpha Token",
            "token_image_url": "https://meta.example/logo.png",
            "token_image_source": "metadata",
        }

    async def fake_helius_security(ca):
        return {
            "mint_authority_present": False,
            "freeze_authority_present": False,
            "top10_ratio": None,
        }

    async def fake_rugcheck(ca):
        return {
            "lp_locked_pct": 80,
            "lp_burned_pct": 100,
            "rugcheck_score": 85,
        }

    async def fake_goplus(ca):
        return {
            "is_honeypot": False,
            "is_blacklisted": False,
            "is_mintable": False,
            "transfer_pausable": False,
        }

    fetcher._fetch_dexscreener = fake_fetch_dexscreener
    fetcher._fetch_rpc_holder_snapshot = fake_rpc_holder_snapshot
    fetcher._fetch_helius_metadata_bundle = fake_metadata_bundle
    fetcher.get_helius_security = fake_helius_security
    fetcher.fetch_rugcheck_data = fake_rugcheck
    fetcher.fetch_goplus_security = fake_goplus

    result = await DataFetcher.get_token_info_fastpath(fetcher, "So11111111111111111111111111111111111111112")

    assert result["market_data_ready"] is True
    assert result["pair_liquidity_usd"] is None
    assert result["liquidity_usd"] is None
    assert result["estimated_pair_liquidity_usd"] == pytest.approx(5.16)
    assert "DEX_LIQUIDITY_WEAK" in result["liquidity_source_error"]
    assert result["top10_ratio"] is None
    assert result["top10_ratio_source"] == ""
    assert result["top10_ratio_pending_exclusion_filter"] is True
    assert result["is_locked"] is True
    assert result["is_burned"] is True
    assert result["mint_authority_present"] is False
    assert result["freeze_authority_present"] is False


@pytest.mark.asyncio
async def test_main_fetch_token_info_fastpath_ignores_non_authoritative_top10_and_page_fields(monkeypatch):
    async def fake_get_token_info_fastpath(ca):
        return {
            "symbol": "AAA",
            "name": "Alpha",
            "price_usd": 0.01,
            "cap_usd": 120000,
            "pair_liquidity_usd": 5000,
            "liquidity_usd": 5000,
            "market_data_ready": True,
            "liquidity_data_ready": True,
            "token_image_url": "https://meta.example/logo.png",
            "token_image_source": "metadata",
            "helius_security": {
                "mint_authority_present": True,
                "freeze_authority_present": False,
                "top10_ratio": None,
            },
            "top10_ratio": "77.00%",
            "top10_ratio_source": "GMGN",
            "gmgn_smart": True,
        }

    monkeypatch.setattr(main.fetcher, "get_token_info_fastpath", fake_get_token_info_fastpath)

    result = await main.fetch_token_info_fastpath(
        "So11111111111111111111111111111111111111112",
        "SYSTEM",
        321,
        654,
    )

    assert not result.get("top10_ratio")
    assert not result.get("top10_ratio_source")
    assert result["mint_authority_present"] is True
    assert result["freeze_authority_present"] is False
    assert result["token_image_source"] == "metadata"
    assert result.get("gmgn_smart") is None
    assert result["canonical_metadata"]["fastpath_mode"] == "api_rpc_only"
    assert result["canonical_metadata"]["page_fields_pending"] is True


@pytest.mark.asyncio
async def test_build_first_card_fastpath_shadow_applies_avatar_fastpath(monkeypatch):
    async def fake_fetch_token_info_fastpath(ca, source, chat_id, msg_id):
        return {
            "ca": ca,
            "symbol": "AAA",
            "name": "Alpha",
            "token_image_url": "",
            "token_image_source": "",
        }

    async def fake_prime_first_card_avatar_fastpath(ca, token_data):
        patched = dict(token_data)
        patched["token_image_url"] = "https://dex.example/logo.png"
        patched["token_image_source"] = "dexscreener"
        patched["token_image_path"] = r"data\token_avatars\alpha.png"
        return patched

    monkeypatch.setattr(main, "fetch_token_info_fastpath", fake_fetch_token_info_fastpath)
    monkeypatch.setattr(main.fetcher, "_prime_first_card_avatar_fastpath", fake_prime_first_card_avatar_fastpath)

    result = await main.build_first_card_fastpath_shadow(
        "So11111111111111111111111111111111111111112",
        "SYSTEM",
        321,
        654,
    )

    assert result["token_image_url"] == "https://dex.example/logo.png"
    assert result["token_image_source"] == "dexscreener"
    assert result["token_image_path"].endswith("alpha.png")