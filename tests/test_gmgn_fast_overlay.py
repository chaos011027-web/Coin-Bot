import time

import pytest

from modules import data_fetcher as data_fetcher_module
from modules.data_fetcher import DataFetcher


class _FakeWait:
    def __init__(self):
        self.calls = []

    def ele(self, selector, timeout=0):
        self.calls.append({"selector": selector, "timeout": timeout})
        return object()


class _FakeTab:
    def __init__(self):
        self.url = "https://gmgn.ai/sol/token/So11111111111111111111111111111111111111112"
        self.title = "GMGN Token"
        self.wait = _FakeWait()
        self.run_js_calls = []
        self.get_calls = []

    def run_js(self, script):
        self.run_js_calls.append(script)
        return ""

    def get(self, url):
        self.get_calls.append(url)


def _make_fetcher():
    fetcher = DataFetcher.__new__(DataFetcher)
    fetcher._browser = object()
    fetcher._gmgn_tab = None
    fetcher._fetcher_role = "interactive"
    return fetcher


@pytest.mark.parametrize(
    ("blocked_reason", "expected_wait_calls"),
    [
        ("overlay_mask", 0),
        ("popup_blocked", 0),
        ("target_not_ready", 1),
    ],
)
def test_gmgn_fast_overlay_returns_weak_within_budget(monkeypatch, blocked_reason, expected_wait_calls):
    fetcher = _make_fetcher()
    tab = _FakeTab()
    walkthrough_deadlines = []
    target_wait_calls = []
    parse_calls = {
        "money": 0,
        "label": 0,
        "top10": 0,
        "avatar": 0,
    }

    fetcher._load_gmgn_saved_state = lambda: {}
    fetcher._build_gmgn_token_url = lambda ca, state=None: f"https://gmgn.ai/sol/token/{ca}"
    fetcher._get_or_create_gmgn_tab = lambda: tab
    fetcher._persist_gmgn_runtime_state = lambda tab_obj, ca: None
    fetcher._gmgn_popup_block_reason = lambda tab_obj: blocked_reason if blocked_reason in {"overlay_mask", "popup_blocked"} else ""

    def fake_finish_walkthrough(tab_obj, max_clicks=12, interval=0.35, deadline_at=None):
        walkthrough_deadlines.append(deadline_at)
        return 0

    def fake_wait_target_page(tab_obj, ca, timeout=10.0, interval=0.4, trace=None, deadline_at=None):
        target_wait_calls.append(
            {
                "ca": ca,
                "timeout": timeout,
                "interval": interval,
                "deadline_at": deadline_at,
            }
        )
        return False

    def fake_page_gate_state(tab_obj, ca="", target_ready=None):
        return {
            "valid": False,
            "blocked_reason": blocked_reason,
            "target_ready": bool(target_ready),
            "layout_ready": blocked_reason not in {"layout_not_ready", "target_not_ready"},
            "header_ready": blocked_reason not in {"header_not_ready", "target_not_ready"},
            "popup_reason": blocked_reason if blocked_reason in {"overlay_mask", "popup_blocked"} else "",
            "overlay_visible": blocked_reason == "overlay_mask",
            "error_reason": "error_page" if blocked_reason == "error_page" else "",
            "shell_page": blocked_reason == "shell_page",
        }

    def fake_money_value(*args, **kwargs):
        parse_calls["money"] += 1
        return 1.0

    def fake_label_snippet(*args, **kwargs):
        parse_calls["label"] += 1
        return "Dex Paid"

    def fake_top10_context(*args, **kwargs):
        parse_calls["top10"] += 1
        return "Top 10 12.34%"

    def fake_pick_avatar(*args, **kwargs):
        parse_calls["avatar"] += 1
        return "https://cdn.example.com/avatar.png"

    fetcher._finish_gmgn_walkthrough = fake_finish_walkthrough
    fetcher._wait_gmgn_target_page = fake_wait_target_page
    fetcher._gmgn_page_gate_state = fake_page_gate_state
    fetcher._extract_gmgn_money_value = fake_money_value
    fetcher._extract_gmgn_label_snippet = fake_label_snippet
    fetcher._extract_gmgn_top10_context = fake_top10_context
    fetcher._pick_gmgn_avatar = fake_pick_avatar

    result = DataFetcher._sync_scrape_gmgn(fetcher, "So11111111111111111111111111111111111111112", full_scan=False)

    assert result["gmgn_result_strength"] == "invalid"
    assert result["gmgn_fast_weak_reason"] == blocked_reason
    assert result["gmgn_page_blocked_reason"] == blocked_reason
    assert result["top10_ratio"] is None
    assert result["header_liq_usd"] == 0
    assert result["raw_data"] == {}
    assert result["gmgn_fast_needs_followup"] is True
    assert result["gmgn_followup_required"] is True
    assert len(target_wait_calls) == expected_wait_calls
    assert len(tab.run_js_calls) == 1
    assert len(tab.get_calls) == 0
    assert walkthrough_deadlines and walkthrough_deadlines[0] is not None
    if target_wait_calls:
        assert target_wait_calls[0]["deadline_at"] is not None
    assert all(count == 0 for count in parse_calls.values())


def test_gmgn_helpers_respect_deadline(monkeypatch):
    fetcher = _make_fetcher()
    sleep_calls = []
    expired_deadline = time.perf_counter() - 1.0

    class _DeadlineTab:
        url = "https://gmgn.ai/sol/token/So11111111111111111111111111111111111111112"
        title = "GMGN Token"

        def run_js(self, script):
            raise AssertionError("walkthrough should not execute after the deadline")

    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(data_fetcher_module.time, "sleep", fake_sleep)

    fetcher._extract_visible_text = lambda tab: (_ for _ in ()).throw(AssertionError("page polling should stop at deadline"))
    fetcher._finish_gmgn_walkthrough = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("walkthrough should not be entered after deadline")
    )
    wait_result = DataFetcher._wait_gmgn_target_page(
        fetcher,
        _DeadlineTab(),
        "So11111111111111111111111111111111111111112",
        timeout=5.0,
        interval=0.4,
        deadline_at=expired_deadline,
    )

    fetcher._gmgn_popup_block_reason = lambda tab: (_ for _ in ()).throw(
        AssertionError("popup probing should stop at deadline")
    )
    walkthrough_result = DataFetcher._finish_gmgn_walkthrough(
        fetcher,
        _DeadlineTab(),
        max_clicks=3,
        interval=0.2,
        deadline_at=expired_deadline,
    )

    assert wait_result is False
    assert walkthrough_result == 0
    assert sleep_calls == []
