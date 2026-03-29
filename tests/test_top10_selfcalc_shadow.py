import pytest

import main
from modules.data_fetcher import DataFetcher


SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"


def _make_fetcher():
    fetcher = DataFetcher.__new__(DataFetcher)
    fetcher.helius_rpc_url = "https://rpc.example.invalid"
    return fetcher


def _token_account(owner: str, ui_amount: float) -> dict:
    return {
        "data": {
            "parsed": {
                "info": {
                    "owner": owner,
                    "tokenAmount": {
                        "uiAmount": ui_amount,
                        "amount": str(int(ui_amount * 1_000_000)),
                    },
                }
            }
        }
    }


def _owner_account(owner_program: str = SYSTEM_PROGRAM_ID, executable: bool = False) -> dict:
    return {
        "owner": owner_program,
        "executable": executable,
    }


@pytest.mark.asyncio
async def test_top10_selfcalc_distinguishes_raw_and_owner_aggregation():
    fetcher = _make_fetcher()

    largest_accounts = [
        {"address": "acct_a1", "uiAmount": 60.0},
        {"address": "acct_a2", "uiAmount": 55.0},
        {"address": "acct_a3", "uiAmount": 50.0},
        {"address": "acct_b", "uiAmount": 49.0},
        {"address": "acct_c", "uiAmount": 48.0},
        {"address": "acct_d", "uiAmount": 47.0},
        {"address": "acct_e", "uiAmount": 46.0},
        {"address": "acct_f", "uiAmount": 45.0},
        {"address": "acct_g", "uiAmount": 44.0},
        {"address": "acct_h", "uiAmount": 43.0},
        {"address": "acct_i", "uiAmount": 42.0},
        {"address": "acct_j", "uiAmount": 41.0},
        {"address": "acct_k", "uiAmount": 40.0},
    ]
    account_owner_map = {
        "acct_a1": "owner_a",
        "acct_a2": "owner_a",
        "acct_a3": "owner_a",
        "acct_b": "owner_b",
        "acct_c": "owner_c",
        "acct_d": "owner_d",
        "acct_e": "owner_e",
        "acct_f": "owner_f",
        "acct_g": "owner_g",
        "acct_h": "owner_h",
        "acct_i": "owner_i",
        "acct_j": "owner_j",
        "acct_k": "owner_k",
    }

    async def fake_helius_rpc(method, params):
        if method == "getTokenSupply":
            return {
                "value": {
                    "amount": "1000000000",
                    "decimals": 6,
                    "uiAmount": 1000.0,
                }
            }
        if method == "getTokenLargestAccounts":
            return {"value": largest_accounts}
        if method == "getMultipleAccounts":
            addresses = params[0]
            if addresses and str(addresses[0]).startswith("acct_"):
                return {"value": [_token_account(account_owner_map[address], next(item["uiAmount"] for item in largest_accounts if item["address"] == address)) for address in addresses]}
            return {"value": [_owner_account() for _ in addresses]}
        raise AssertionError(f"unexpected method {method}")

    fetcher._helius_rpc = fake_helius_rpc

    result = await DataFetcher._fetch_rpc_holder_top10_finalize_shadow(
        fetcher,
        "So11111111111111111111111111111111111111112",
        known_exclude_owners=set(),
    )

    assert result["top10_raw_pct_self"] == pytest.approx(48.7)
    assert result["top10_owner_pct_self"] == pytest.approx(57.0)
    assert result["top10_effective_pct_self"] == pytest.approx(57.0)
    assert result["top10_holder_count_raw_self"] == 13
    assert result["top10_holder_count_owner_self"] == 11
    assert result["top10_holder_count_effective_self"] == 11


@pytest.mark.asyncio
async def test_top10_selfcalc_effective_excludes_pool_candidates():
    fetcher = _make_fetcher()

    largest_accounts = [
        {"address": "acct_pool", "uiAmount": 300.0, "label": "lp pool reserve"},
        {"address": "acct_b", "uiAmount": 120.0},
        {"address": "acct_c", "uiAmount": 100.0},
        {"address": "acct_d", "uiAmount": 90.0},
    ]
    account_owner_map = {
        "acct_pool": "owner_pool",
        "acct_b": "owner_b",
        "acct_c": "owner_c",
        "acct_d": "owner_d",
    }

    async def fake_helius_rpc(method, params):
        if method == "getTokenSupply":
            return {
                "value": {
                    "amount": "1000000000",
                    "decimals": 6,
                    "uiAmount": 1000.0,
                }
            }
        if method == "getTokenLargestAccounts":
            return {"value": largest_accounts}
        if method == "getMultipleAccounts":
            addresses = params[0]
            if addresses and str(addresses[0]).startswith("acct_"):
                return {"value": [_token_account(account_owner_map[address], next(item["uiAmount"] for item in largest_accounts if item["address"] == address)) for address in addresses]}
            return {"value": [_owner_account() for _ in addresses]}
        raise AssertionError(f"unexpected method {method}")

    fetcher._helius_rpc = fake_helius_rpc

    result = await DataFetcher._fetch_rpc_holder_top10_finalize_shadow(
        fetcher,
        "So11111111111111111111111111111111111111112",
        known_exclude_owners=set(),
        unit_price_usd=0.02,
    )

    assert result["top10_owner_pct_self"] == pytest.approx(61.0)
    assert result["top10_effective_pct_self"] == pytest.approx(31.0)
    assert result["top1_effective_pct_self"] == pytest.approx(12.0)
    assert result["top10_effective_value_usd_self"] == pytest.approx(6.2)
    assert result["top1_effective_value_usd_self"] == pytest.approx(2.4)
    assert result["top10_exclusion_summary_self"]["pool_candidate_count"] == 1
    assert result["top10_exclusion_summary_self"]["effective_excluded_owner_count"] == 1


@pytest.mark.asyncio
async def test_top10_selfcalc_is_conservative_when_owner_lookup_is_missing():
    fetcher = _make_fetcher()

    async def fake_helius_rpc(method, params):
        if method == "getTokenSupply":
            return {
                "value": {
                    "amount": "1000000000",
                    "decimals": 6,
                    "uiAmount": 1000.0,
                }
            }
        if method == "getTokenLargestAccounts":
            return {
                "value": [
                    {"address": "acct_1", "uiAmount": 200.0},
                    {"address": "acct_2", "uiAmount": 150.0},
                ]
            }
        if method == "getMultipleAccounts":
            return {"value": [None, None]}
        raise AssertionError(f"unexpected method {method}")

    fetcher._helius_rpc = fake_helius_rpc

    result = await DataFetcher._fetch_rpc_holder_snapshot(
        fetcher,
        "So11111111111111111111111111111111111111112",
    )

    assert result["top10_raw_pct_self"] == pytest.approx(35.0)
    assert result["top10_owner_pct_self"] is None
    assert result["top10_effective_pct_self"] is None
    assert result["top10_calc_method_self"]["insufficiency_reason"] == "owner_lookup_missing"
    assert result["top10_exclusion_summary_self"]["owner_lookup_missing_count"] == 2


@pytest.mark.asyncio
async def test_main_fastpath_keeps_selfcalc_fields_without_promoting_formal_top10(monkeypatch):
    async def fake_get_token_info_fastpath(ca):
        return {
            "symbol": "AAA",
            "name": "Alpha",
            "top10_ratio": "97.00%",
            "top10_ratio_source": "GMGN",
            "top10_raw_pct_self": 97.0,
            "top10_owner_pct_self": 42.0,
            "top10_effective_pct_self": 24.0,
            "top10_effective_value_usd_self": 120000.0,
            "top1_effective_pct_self": 8.5,
            "top1_effective_value_usd_self": 42000.0,
            "top10_holder_count_raw_self": 20,
            "top10_holder_count_owner_self": 14,
            "top10_holder_count_effective_self": 11,
            "top10_calc_method_self": {"source": "solana_rpc_largest_accounts"},
            "top10_exclusion_summary_self": {"effective_excluded_owner_count": 3},
            "gmgn_observed_top10_ratio": "24.00%",
        }

    monkeypatch.setattr(main.fetcher, "get_token_info_fastpath", fake_get_token_info_fastpath)

    result = await main.fetch_token_info_fastpath(
        "So11111111111111111111111111111111111111112",
        "SYSTEM",
        321,
        654,
    )

    assert "top10_ratio" not in result
    assert "top10_ratio_source" not in result
    assert result["top10_raw_pct_self"] == pytest.approx(97.0)
    assert result["top10_owner_pct_self"] == pytest.approx(42.0)
    assert result["top10_effective_pct_self"] == pytest.approx(24.0)
    assert result["top10_exclusion_summary_self"]["effective_excluded_owner_count"] == 3
    assert "gmgn_observed_top10_ratio" not in result
