import asyncio
import copy

import pytest

import main


def test_avatar_enrichment_patch_does_not_overwrite_existing_name_cap_and_safety(monkeypatch):
    async def _run_case():
        ca = "So11111111111111111111111111111111111111112"
        avatar_url = "https://cdn.example.com/avatar.png"
        avatar_source = "gmgn/warm"
        avatar_path = r"data\token_avatars\patched_avatar.jpg"

        terminal_states = {
            "symbol": "LEGACY",
            "entry_price": 1.23,
            "milestone_anchor_price": 1.23,
            "decision_action": main.ACTION_WATCH,
            "decision_reason": "keep stable fields",
            "reply_chat_id": 321,
            "token_image_url": "",
            "token_image_path": "",
            "token_image_source": "",
            "stable_snapshot": {
                "symbol": "LEGACY",
                "name": "Legacy Token",
                "cap_usd": 987654.0,
                "volume_h24": 43210.0,
                "buy_sell_ratio": 1.8,
                "dex_paid": True,
                "is_burned": True,
                "is_locked": True,
                "top10_ratio": "12.34%",
                "top10_ratio_source": "BITQUERY",
            },
        }
        record = {
            "terminal_states": terminal_states,
            "message_snapshot": {"symbol": "LEGACY"},
            "initial_msg_id": 654,
            "entry_price": 1.23,
            "source": "SYSTEM",
            "status": main.SIGNAL_STATE_OBSERVING,
        }

        saved_terminal_states = []
        refreshed_payloads = []
        refreshed = asyncio.Event()

        async def fake_get_signal_snapshot(requested_ca):
            assert requested_ca == ca
            return record

        async def fake_save_initial_signal(contract, source, entry_price, initial_msg_id, terminal, status=None):
            saved_terminal_states.append(copy.deepcopy(terminal))
            return {
                "ca": contract,
                "source": source,
                "entry_price": entry_price,
                "initial_msg_id": initial_msg_id,
                "status": status,
            }

        async def fake_update_user_message(*, chat_id, message_id, ca, token_data, decision):
            refreshed_payloads.append(
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "ca": ca,
                    "token_data": copy.deepcopy(token_data),
                    "decision": copy.deepcopy(decision),
                }
            )
            refreshed.set()
            return True

        def fake_normalize_token_data(contract, raw_market, source, chat_id, msg_id):
            return {
                "ca": contract,
                "symbol": "UNK",
                "name": "",
                "cap_usd": 0,
                "volume_h24": 0,
                "buy_sell_ratio": 0,
                "dex_paid": None,
                "is_burned": None,
                "is_locked": None,
                "top10_ratio": "?",
                "top10_ratio_source": "?",
                "token_image_url": "",
                "token_image_path": "",
                "token_image_source": "",
            }

        async def fake_ensure_token_avatar(contract, url, source, fast_mode=False):
            if not url:
                return ""
            return avatar_path

        async def fake_prime_avatar_sources(contract, token_data, allow_warm_probe=True):
            return avatar_url, avatar_source

        monkeypatch.setattr(main, "_avatar_enrichment_queue", asyncio.Queue())
        monkeypatch.setattr(main, "_avatar_enrichment_pending", set())
        monkeypatch.setattr(main, "_avatar_enrichment_lock", asyncio.Lock())
        monkeypatch.setattr(main, "normalize_token_data", fake_normalize_token_data)
        monkeypatch.setattr(main.db, "get_signal_snapshot", fake_get_signal_snapshot)
        monkeypatch.setattr(main.db, "save_initial_signal", fake_save_initial_signal)
        monkeypatch.setattr(main, "update_user_message", fake_update_user_message)
        monkeypatch.setattr(main.background_fetcher, "_existing_avatar_path", lambda contract: "")
        monkeypatch.setattr(main.background_fetcher, "ensure_token_avatar", fake_ensure_token_avatar)
        monkeypatch.setattr(main.background_fetcher, "prime_avatar_sources", fake_prime_avatar_sources)

        worker = asyncio.create_task(main._avatar_enrichment_loop())
        await main._enqueue_avatar_enrichment(ca, 321, 654)
        await asyncio.wait_for(refreshed.wait(), timeout=2.0)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

        assert saved_terminal_states, "avatar patch should persist terminal state"
        assert refreshed_payloads, "avatar patch should refresh the first card payload"

        refreshed_token_data = refreshed_payloads[0]["token_data"]
        saved_terminal = saved_terminal_states[0]
        saved_snapshot = saved_terminal["stable_snapshot"]

        assert refreshed_token_data["name"] == "Legacy Token"
        assert refreshed_token_data["cap_usd"] == 987654.0
        assert refreshed_token_data["volume_h24"] == 43210.0
        assert refreshed_token_data["buy_sell_ratio"] == 1.8
        assert refreshed_token_data["dex_paid"] is True
        assert refreshed_token_data["is_burned"] is True
        assert refreshed_token_data["is_locked"] is True
        assert refreshed_token_data["top10_ratio"] == "12.34%"
        assert refreshed_token_data["top10_ratio_source"] == "BITQUERY"
        assert refreshed_token_data["token_image_url"] == avatar_url
        assert refreshed_token_data["token_image_source"] == avatar_source
        assert refreshed_token_data["token_image_path"] == avatar_path

        assert saved_snapshot["name"] == "Legacy Token"
        assert saved_snapshot["cap_usd"] == 987654.0
        assert saved_snapshot["dex_paid"] is True
        assert saved_snapshot["is_burned"] is True
        assert saved_snapshot["is_locked"] is True
        assert saved_snapshot["top10_ratio"] == "12.34%"
        assert saved_snapshot["top10_ratio_source"] == "BITQUERY"
        assert saved_snapshot["token_image_url"] == avatar_url
        assert saved_snapshot["token_image_source"] == avatar_source
        assert saved_snapshot["token_image_path"] == avatar_path

    asyncio.run(_run_case())


def test_merge_existing_terminal_restores_name_from_stable_snapshot():
    token_data = {
        "symbol": "LEGACY",
        "name": "",
        "volume_h24": None,
        "buy_sell_ratio": 0,
    }
    terminal = {
        "stable_snapshot": {
            "name": "Recovered Name",
            "volume_h24": 54321.0,
            "buy_sell_ratio": 1.7,
        }
    }

    merged = main._merge_existing_terminal(copy.deepcopy(token_data), terminal)

    assert merged["name"] == "Recovered Name"
    assert merged["volume_h24"] == 54321.0
    assert merged["buy_sell_ratio"] == 1.7
