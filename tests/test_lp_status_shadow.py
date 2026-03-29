import pytest

import main
from modules.data_fetcher import DataFetcher


def _make_fetcher():
    fetcher = DataFetcher.__new__(DataFetcher)
    fetcher._should_probe_pump = lambda ca, token_data=None: False
    return fetcher


def test_lp_status_shadow_marks_bonding_curve_phase_as_not_applicable():
    fetcher = _make_fetcher()
    fetcher._should_probe_pump = lambda ca, token_data=None: True

    result = DataFetcher._build_lp_status_shadow(
        fetcher,
        "So111111111111111111111111111111111111pump",
        market_data={
            "dex_id": "pump",
            "token_age_min": 12,
            "symbol": "PUMPY",
            "name": "Pumpy Token",
        },
        rugcheck_data=None,
        metadata_bundle={},
        goplus_data=None,
    )

    assert result["lp_status_phase"] == "bonding_curve_phase"
    assert result["lp_status_source"] == "pump_heuristic"
    assert result["lp_burned_pct"] is None
    assert result["lp_locked_pct"] is None
    assert "not applicable" in result["lp_status_reason"].lower()
    assert result["lp_status_phase_conflict"] is False
    assert result["lp_status_source_conflict"] is False


def test_lp_status_shadow_keeps_unknown_as_unknown_not_false():
    fetcher = _make_fetcher()

    result = DataFetcher._build_lp_status_shadow(
        fetcher,
        "So11111111111111111111111111111111111111112",
        market_data={},
        rugcheck_data=None,
        metadata_bundle={},
        goplus_data=None,
    )

    assert result["lp_status_phase"] == "unknown"
    assert result["lp_burned_pct"] is None
    assert result["lp_locked_pct"] is None
    assert result["lp_status_confidence"] == pytest.approx(0.25)
    assert result["lp_status_phase_conflict"] is False
    assert result["lp_status_source_conflict"] is False


def test_lp_status_shadow_records_conflict_when_stage1_bonding_curve_and_rugcheck_reports_lp_pcts():
    fetcher = _make_fetcher()

    result = DataFetcher._build_lp_status_shadow(
        fetcher,
        "So111111111111111111111111111111111111pump",
        market_data={"dex_id": "pump"},
        rugcheck_data={"lp_burned_pct": 100, "lp_locked_pct": 0},
        metadata_bundle={},
        goplus_data={},
        prior_shadow={
            "lp_status_phase": "bonding_curve_phase",
            "lp_status_source": "pump_heuristic",
            "lp_status_confidence": 0.92,
            "lp_status_reason": "bonding curve / pump.fun phase detected; LP burn/lock not applicable yet",
        },
    )

    assert result["lp_status_phase"] == "bonding_curve_phase"
    assert result["lp_status_source"] == "pump_heuristic"
    assert result["lp_burned_pct"] == pytest.approx(100.0)
    assert result["lp_locked_pct"] == pytest.approx(0.0)
    assert result["lp_status_phase_conflict"] is True
    assert result["lp_status_source_conflict"] is True
    assert "bonding_curve_phase" in result["lp_status_conflict_reason"]
    assert "review" in result["lp_status_reason"].lower()


@pytest.mark.asyncio
async def test_main_stage2_shadow_propagates_lp_conflict_without_restoring_bool_fields(monkeypatch):
    async def fake_stage2(ca, stage1_payload=None, known_exclude_owners=None):
        return {
            "lp_burned_pct": 100.0,
            "lp_locked_pct": 0.0,
            "lp_status_source": "pump_heuristic",
            "lp_status_confidence": 0.92,
            "lp_status_reason": "bonding curve / pump.fun phase inferred in stage1, but follow-up RugCheck reported LP percentage fields; review required before render/canonical merge",
            "lp_status_phase": "bonding_curve_phase",
            "lp_status_phase_conflict": True,
            "lp_status_source_conflict": True,
            "lp_status_conflict_reason": "stage1 inferred bonding_curve_phase, but RugCheck reported LP percentage fields",
            "is_burned": True,
            "is_locked": False,
            "fastpath_shadow_stage": "stage2_followup_enrich",
            "slow_followup_required": False,
            "stage2_source_status": {"rugcheck": "ok", "goplus": "ok", "top10_finalize": "ok"},
            "stage2_source_errors": [],
            "stage2_partial_degraded": False,
        }

    monkeypatch.setattr(main.fetcher, "get_token_info_stage2_shadow", fake_stage2)

    result = await main.enrich_token_info_fastpath_stage2_shadow(
        "So11111111111111111111111111111111111111112",
        "SYSTEM",
        321,
        654,
        stage1_token_data={
            "ca": "So11111111111111111111111111111111111111112",
            "symbol": "AAA",
            "name": "Alpha",
            "is_burned": True,
            "is_locked": False,
            "lp_status_phase": "bonding_curve_phase",
            "lp_status_source": "pump_heuristic",
            "lp_status_confidence": 0.92,
            "lp_status_reason": "bonding curve / pump.fun phase detected; LP burn/lock not applicable yet",
            "canonical_metadata": {"fastpath_mode": "api_rpc_ultra_fast_stage1"},
        },
    )

    assert "is_burned" not in result
    assert "is_locked" not in result
    assert "liquidity_locked" not in result
    assert result["lp_burned_pct"] == pytest.approx(100.0)
    assert result["lp_locked_pct"] == pytest.approx(0.0)
    assert result["lp_status_phase"] == "bonding_curve_phase"
    assert result["lp_status_source"] == "pump_heuristic"
    assert result["lp_status_phase_conflict"] is True
    assert result["lp_status_source_conflict"] is True
    assert "RugCheck reported LP percentage fields" in result["lp_status_conflict_reason"]
    assert result["canonical_metadata"]["fastpath_mode"] == "api_rpc_stage2_followup"
