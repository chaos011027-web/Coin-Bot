import pytest

from modules.data_fetcher import DataFetcher


def _make_fetcher():
    fetcher = DataFetcher.__new__(DataFetcher)
    fetcher._log_avatar_trace = lambda *args, **kwargs: None
    fetcher._existing_avatar_path = lambda ca: ""
    fetcher._normalize_image_url = lambda url: str(url or "").strip()

    def _normalize_avatar_source(source, url=""):
        source = str(source or "").strip().lower()
        if source:
            return source
        low = str(url or "").lower()
        if "dex" in low:
            return "dexscreener"
        if "meta" in low:
            return "metadata"
        return ""

    fetcher._normalize_avatar_source = _normalize_avatar_source
    return fetcher


@pytest.mark.asyncio
async def test_first_card_avatar_fastpath_prefers_dex_without_pump_birdeye_or_gmgn():
    fetcher = _make_fetcher()
    calls = {
        "dex": 0,
        "metadata": 0,
        "ensure": 0,
    }

    async def fake_fetch_dex_avatar_url(ca):
        calls["dex"] += 1
        return "https://dex.example/logo.png", "dexscreener"

    async def fake_fetch_metadata_avatar_url(ca, token_data=None):
        calls["metadata"] += 1
        return "https://meta.example/logo.png", "metadata"

    async def fake_ensure_token_avatar(ca, url, source="", fast_mode=False):
        calls["ensure"] += 1
        assert url == "https://dex.example/logo.png"
        assert source == "dexscreener"
        assert fast_mode is True
        return r"data\token_avatars\dex_logo.png"

    fetcher._fetch_dex_avatar_url = fake_fetch_dex_avatar_url
    fetcher._fetch_metadata_avatar_url = fake_fetch_metadata_avatar_url
    fetcher.ensure_token_avatar = fake_ensure_token_avatar
    fetcher._fetch_pump_avatar_url = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pump must not be used"))
    fetcher._fetch_birdeye_avatar_url = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("birdeye must not be used"))
    fetcher._fetch_warm_gmgn_avatar_url = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("gmgn warm must not be used"))

    result = await DataFetcher._prime_first_card_avatar_fastpath(
        fetcher,
        "So11111111111111111111111111111111111111112",
        {"token_image_url": "", "token_image_source": ""},
    )

    assert result["token_image_url"] == "https://dex.example/logo.png"
    assert result["token_image_source"] == "dexscreener"
    assert result["token_image_path"].endswith("dex_logo.png")
    assert calls["dex"] == 1
    assert calls["metadata"] == 0
    assert calls["ensure"] == 1


@pytest.mark.asyncio
async def test_first_card_avatar_fastpath_uses_metadata_when_dex_misses():
    fetcher = _make_fetcher()
    calls = {
        "dex": 0,
        "metadata": 0,
    }

    async def fake_fetch_dex_avatar_url(ca):
        calls["dex"] += 1
        return "", ""

    async def fake_fetch_metadata_avatar_url(ca, token_data=None):
        calls["metadata"] += 1
        return "https://meta.example/logo.png", "metadata"

    async def fake_ensure_token_avatar(ca, url, source="", fast_mode=False):
        assert url == "https://meta.example/logo.png"
        assert source == "metadata"
        return r"data\token_avatars\meta_logo.png"

    fetcher._fetch_dex_avatar_url = fake_fetch_dex_avatar_url
    fetcher._fetch_metadata_avatar_url = fake_fetch_metadata_avatar_url
    fetcher.ensure_token_avatar = fake_ensure_token_avatar
    fetcher._fetch_pump_avatar_url = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pump must not be used"))
    fetcher._fetch_birdeye_avatar_url = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("birdeye must not be used"))
    fetcher._fetch_warm_gmgn_avatar_url = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("gmgn warm must not be used"))

    result = await DataFetcher._prime_first_card_avatar_fastpath(
        fetcher,
        "So11111111111111111111111111111111111111112",
        {"token_image_url": "", "token_image_source": ""},
    )

    assert result["token_image_url"] == "https://meta.example/logo.png"
    assert result["token_image_source"] == "metadata"
    assert result["token_image_path"].endswith("meta_logo.png")
    assert calls["dex"] == 1
    assert calls["metadata"] == 1


@pytest.mark.asyncio
async def test_first_card_avatar_fastpath_materializes_existing_trusted_url_without_extra_probe():
    fetcher = _make_fetcher()

    async def fake_ensure_token_avatar(ca, url, source="", fast_mode=False):
        assert url == "https://meta.example/logo.png"
        assert source == "metadata"
        return r"data\token_avatars\trusted_logo.png"

    fetcher.ensure_token_avatar = fake_ensure_token_avatar
    fetcher._fetch_dex_avatar_url = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dex probe should not run"))
    fetcher._fetch_metadata_avatar_url = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("metadata probe should not run"))

    result = await DataFetcher._prime_first_card_avatar_fastpath(
        fetcher,
        "So11111111111111111111111111111111111111112",
        {
            "token_image_url": "https://meta.example/logo.png",
            "token_image_source": "metadata",
        },
    )

    assert result["token_image_url"] == "https://meta.example/logo.png"
    assert result["token_image_source"] == "metadata"
    assert result["token_image_path"].endswith("trusted_logo.png")