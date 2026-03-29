from modules.data_fetcher import DataFetcher


class _FakeTab:
    def __init__(self):
        self.url = "https://gmgn.ai/sol/token/So11111111111111111111111111111111111111112"
        self.title = "GMGN Token"
        self.get_calls = []

    def get(self, url):
        self.get_calls.append(url)


def _make_fetcher():
    fetcher = DataFetcher.__new__(DataFetcher)
    fetcher._gmgn_tab = None
    return fetcher


def test_passive_attach_reader_uses_passive_helpers_only():
    fetcher = _make_fetcher()
    tab = _FakeTab()
    fetcher._gmgn_tab = tab

    fetcher._wait_gmgn_target_page = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("active wait helper must not be used")
    )
    fetcher._gmgn_page_gate_state = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("active gate helper must not be used")
    )
    fetcher._get_or_create_gmgn_tab = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("keeper tab creation must not be used")
    )
    fetcher._apply_gmgn_saved_state = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("keeper saved-state restore must not be used")
    )
    fetcher._bootstrap_gmgn_tab_layout = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("keeper bootstrap must not be used")
    )
    fetcher._finish_gmgn_walkthrough = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("walkthrough must not be used")
    )

    fetcher._wait_gmgn_target_page_passive = lambda *args, **kwargs: True
    fetcher._gmgn_page_gate_state_passive = lambda *args, **kwargs: {
        "valid": True,
        "blocked_reason": "",
        "target_ready": True,
        "layout_ready": True,
        "header_ready": True,
        "popup_reason": "",
        "overlay_visible": False,
        "error_reason": "",
        "shell_page": False,
        "passive_reader": True,
    }

    def fake_block(tab_obj, markers, max_chars=520):
        joined = " | ".join(markers)
        if "Market Cap" in joined or "市值" in joined:
            return "Market Cap $120K\nLiquidity $45K\n1m +12.3%"
        if "Dex Paid" in joined or "Dex付费" in joined:
            return "Dex Paid Yes\nLP Burned 100%\nLiquidity Locked 100%\nMint Renounced\nFreeze Disabled"
        return "Smart Money\nKOL\nSniper"

    fetcher._extract_gmgn_block_snippet = fake_block
    fetcher._extract_gmgn_top10_context = lambda tab_obj: "Top 10 Holders 12.34%"

    result = DataFetcher.passive_attach_read_gmgn(
        fetcher,
        "So11111111111111111111111111111111111111112",
        tab,
    )

    assert result["gmgn_result_strength"] == "strong"
    assert result["gmgn_observed_non_authoritative"] is True
    assert result["gmgn_observed_header_liq_usd"] == 45000.0
    assert result["gmgn_observed_top10_ratio"] == "12.34%"
    assert result["gmgn_observed_dex_paid"] is True
    assert result["gmgn_observed_burned"] is True
    assert result["gmgn_observed_locked"] is True
    assert result["gmgn_observed_mint_authority_present"] is False
    assert result["gmgn_observed_freeze_authority_present"] is False
    assert result["gmgn_observed_raw_tags"]["smart"] is True
    assert result["gmgn_observed_raw_tags"]["kol"] is True
    assert result["gmgn_observed_raw_tags"]["sniper"] is True
    assert "top10_ratio" not in result
    assert tab.get_calls == []


def test_passive_attach_reader_returns_invalid_observed_result_on_blocked_page():
    fetcher = _make_fetcher()
    tab = _FakeTab()
    fetcher._gmgn_tab = tab

    fetcher._wait_gmgn_target_page = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("active wait helper must not be used")
    )
    fetcher._gmgn_page_gate_state = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("active gate helper must not be used")
    )

    fetcher._gmgn_page_gate_state_passive = lambda *args, **kwargs: {
        "valid": False,
        "blocked_reason": "target_not_ready",
        "target_ready": False,
        "layout_ready": False,
        "header_ready": False,
        "popup_reason": "",
        "overlay_visible": False,
        "error_reason": "",
        "shell_page": False,
        "passive_reader": True,
    }

    result = DataFetcher.passive_attach_read_gmgn(
        fetcher,
        "So11111111111111111111111111111111111111112",
        tab,
    )

    assert result["gmgn_result_strength"] == "invalid"
    assert result["gmgn_page_blocked_reason"] == "target_not_ready"
    assert result["gmgn_observed_non_authoritative"] is True
    assert result["gmgn_observed_top10_ratio"] is None
    assert result["gmgn_observed_header_liq_usd"] == 0
    assert result["gmgn_observed_raw_tags"] == {}
    assert "top10_ratio" not in result


def test_passive_attach_reader_returns_invalid_when_no_attached_tab():
    fetcher = _make_fetcher()

    result = DataFetcher.passive_attach_read_gmgn(
        fetcher,
        "So11111111111111111111111111111111111111112",
        None,
    )

    assert result["gmgn_result_strength"] == "invalid"
    assert result["gmgn_page_blocked_reason"] == "tab_missing"
    assert result["gmgn_observed_non_authoritative"] is True
    assert result["gmgn_observed_top10_ratio"] is None
    assert result["gmgn_observed_header_liq_usd"] == 0