import aiohttp
import asyncio
import os
import logging
import time
import re
import json
import random
import hashlib
from io import BytesIO
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from PIL import Image

from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.errors import PageDisconnectedError

from modules.database import db

logger = logging.getLogger("DataFetcher")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

_GLOBAL_GMGN_AVATAR_RUNTIME_CACHE: Dict[str, Tuple[float, str, str]] = {}


def _to_float(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        if isinstance(x, str):
            x = x.replace(",", "").replace("$", "").strip()
            if x.endswith("%"):
                x = x[:-1].strip()
            if "K" in x.upper():
                x = float(x.replace("K", "").replace("k", "")) * 1000
            elif "M" in x.upper():
                x = float(x.replace("M", "").replace("m", "")) * 1000000
            elif "B" in x.upper():
                x = float(x.replace("B", "").replace("b", "")) * 1000000000
        return float(x)
    except Exception:
        return default


def _to_int(x, default=0) -> int:
    try:
        return int(float(x)) if x is not None else default
    except Exception:
        return default


class DataFetcher:
    def __init__(self, profile_dir: Optional[str] = None):
        self.img_dir = "data/charts"
        self.avatar_dir = "data/token_avatars"
        self.profile_dir = os.path.abspath(profile_dir or "data/browser_profile")
        profile_hint = str(self.profile_dir or "").lower()
        self._fetcher_role = "background" if "background" in profile_hint else "interactive"
        self.gmgn_template_token = "So11111111111111111111111111111111111111112"
        self.gmgn_state_path = os.path.join(self.profile_dir, "gmgn_runtime_state.json")
        self.gmgn_marker_path = os.path.join(self.profile_dir, ".gmgn_profile_ready")

        os.makedirs(self.img_dir, exist_ok=True)
        os.makedirs(self.avatar_dir, exist_ok=True)
        os.makedirs(self.profile_dir, exist_ok=True)

        self.dex_api_url = "https://api.dexscreener.com/latest/dex/tokens/{}"
        self.birdeye_api_key = os.getenv("BIRDEYE_API_KEY", "")
        self.goplus_app_key = os.getenv("GOPLUS_APP_KEY", "")
        self.goplus_app_secret = os.getenv("GOPLUS_APP_SECRET", "")

        self.jup_api_key = (os.getenv("JUP_API_KEY") or os.getenv("JUPITER_API_KEY") or "").strip()
        self.jup_price_url = "https://api.jup.ag/price/v3"
        self.jup_lite_price_url = "https://lite-api.jup.ag/price/v3"

        self._goplus_token = ""
        self._goplus_token_expire = 0

        self._session: Optional[aiohttp.ClientSession] = None
        self._browser: Optional[ChromiumPage] = None
        self._gmgn_tab = None
        self._browser_lock = asyncio.Lock()
        self._gmgn_lock = asyncio.Lock()
        self._gmgn_priority_ca = ""
        self._gmgn_priority_until = 0.0
        self._gmgn_pending_high = 0
        self._gmgn_pending_normal = 0
        self._gmgn_pending_lock = asyncio.Lock()
        self._ca_locks: Dict[str, asyncio.Lock] = {}
        self._ca_locks_lock = asyncio.Lock()

        self._market_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._market_cache_ttl = float(os.getenv("DEX_MARKET_CACHE_TTL", "8") or 8.0)
        self._last_gmgn_avatar_pick: Dict[str, str] = {"source": "", "url": ""}
        self._gmgn_weak_state: Dict[str, Dict[str, Any]] = {}
        self._gmgn_skip_state: Dict[str, Dict[str, Any]] = {}
        self._gmgn_avatar_runtime_cache = _GLOBAL_GMGN_AVATAR_RUNTIME_CACHE
        self._gmgn_avatar_runtime_cache_ttl = float(os.getenv("GMGN_AVATAR_RUNTIME_CACHE_TTL", "900") or 900.0)
        self._birdeye_overview_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._birdeye_overview_cache_ttl = float(os.getenv("BIRDEYE_OVERVIEW_CACHE_TTL", "90") or 90.0)
        self._birdeye_avatar_cooldown: Dict[str, float] = {}
        self._birdeye_avatar_cooldown_ttl = float(os.getenv("BIRDEYE_AVATAR_COOLDOWN_TTL", "90") or 90.0)

        self.helius_api_key = (os.getenv("HELIUS_API_KEY") or "").strip()
        self.helius_rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}" if self.helius_api_key else ""



    async def _shadow_source_call(self, name: str, coro, timeout_s: float) -> Dict[str, Any]:
        try:
            data = await asyncio.wait_for(coro, timeout=float(timeout_s))
            return {
                "source": name,
                "ok": True,
                "status": "ok",
                "data": data,
                "error": "",
            }
        except asyncio.TimeoutError:
            logger.warning("ShadowSourceTimeout | source=%s", name)
            return {
                "source": name,
                "ok": False,
                "status": "timeout",
                "data": None,
                "error": "timeout",
            }
        except Exception as e:
            logger.warning("ShadowSourceError | source=%s | err=%s", name, e)
            return {
                "source": name,
                "ok": False,
                "status": "error",
                "data": None,
                "error": f"{type(e).__name__}: {e}",
            }

    def _coerce_shadow_source_result(self, name: str, payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict) and payload.get("source") == name and "status" in payload and "ok" in payload:
            return payload

        if isinstance(payload, Exception):
            status = "timeout" if isinstance(payload, asyncio.TimeoutError) else "error"
            return {
                "source": name,
                "ok": False,
                "status": status,
                "data": None,
                "error": f"{type(payload).__name__}: {payload}",
            }

        return {
            "source": name,
            "ok": True,
            "status": "ok",
            "data": payload,
            "error": "",
        }

    async def _fetch_helius_metadata_bundle(self, mint: str) -> Dict[str, Any]:
        mint = str(mint or "").strip()
        if not mint or not self.helius_rpc_url:
            return {}

        try:
            asset = await self._helius_rpc("getAsset", {"id": mint})
        except Exception:
            asset = None

        if not isinstance(asset, dict):
            return {}

        content = asset.get("content") or {}
        metadata = content.get("metadata") or {}
        links = content.get("links") or {}
        files = content.get("files") or []

        symbol = str(metadata.get("symbol") or asset.get("symbol") or "").strip()
        name = str(metadata.get("name") or asset.get("name") or "").strip()

        image_candidates: List[str] = []
        for candidate in (
            metadata.get("image"),
            links.get("image"),
            links.get("logo"),
            asset.get("image"),
        ):
            norm = self._normalize_image_url(candidate or "")
            if norm:
                image_candidates.append(norm)

        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                for key in ("uri", "cdn_uri", "url"):
                    norm = self._normalize_image_url(item.get(key) or "")
                    if norm:
                        image_candidates.append(norm)

        token_image_url = ""
        for candidate in image_candidates:
            if candidate.startswith("http://") or candidate.startswith("https://"):
                token_image_url = candidate
                break

        out: Dict[str, Any] = {}
        if symbol:
            out["symbol"] = symbol
        if name:
            out["name"] = name
        if token_image_url:
            out["token_image_url"] = token_image_url
            out["token_image_source"] = "metadata"

        metadata_json_uri = str(
            content.get("json_uri")
            or links.get("json_uri")
            or asset.get("json_uri")
            or ""
        ).strip()
        if metadata_json_uri:
            out["metadata_json_uri"] = metadata_json_uri

        return out
    
    async def _fetch_metadata_avatar_url(self, ca: str, token_data: Optional[dict] = None) -> Tuple[str, str]:
        td = token_data if isinstance(token_data, dict) else {}

        current_url = self._normalize_image_url(td.get("token_image_url") or "")
        current_source = self._normalize_avatar_source(td.get("token_image_source") or "", current_url)
        if current_url and current_source in {"metadata", "helius", "das", "api"}:
            return current_url, current_source or "metadata"

        bundle = await self._fetch_helius_metadata_bundle(ca)
        if not isinstance(bundle, dict):
            return "", ""

        url = self._normalize_image_url(bundle.get("token_image_url") or "")
        source = self._normalize_avatar_source(bundle.get("token_image_source") or "metadata", url)
        return (url, source) if url else ("", "")

    async def _fetch_basic_rpc_supply_snapshot(self, mint: str) -> Dict[str, Any]:
        mint = str(mint or "").strip()
        if not mint or not self.helius_rpc_url:
            return {}

        supply_res, largest_res = await asyncio.gather(
            self._helius_rpc("getTokenSupply", [mint]),
            self._helius_rpc("getTokenLargestAccounts", [mint]),
            return_exceptions=True,
        )

        supply_err = isinstance(supply_res, Exception)
        largest_err = isinstance(largest_res, Exception)

        supply_val = (supply_res or {}).get("value", {}) if isinstance(supply_res, dict) else {}
        largest_accounts = (largest_res or {}).get("value", []) if isinstance(largest_res, dict) else []

        decimals = _to_int(supply_val.get("decimals"), 0)
        supply_raw_text = str(supply_val.get("amount") or "").strip()
        supply_raw = int(supply_raw_text) if supply_raw_text.isdigit() else 0

        supply_ui = _to_float(supply_val.get("uiAmount"), 0.0)
        if supply_ui <= 0:
            supply_ui = _to_float(supply_val.get("uiAmountString"), 0.0)
        if supply_ui <= 0 and supply_raw > 0:
            supply_ui = supply_raw / (10 ** max(0, decimals))

        holders = largest_accounts if isinstance(largest_accounts, list) else []
        reasons: List[str] = []
        if supply_err:
            reasons.append("supply_failed")
        if largest_err:
            reasons.append("largest_accounts_failed")

        return {
            "supply_raw": supply_raw if supply_raw > 0 else None,
            "supply_ui": supply_ui if supply_ui > 0 else None,
            "largest_accounts_present": bool(holders),
            "largest_accounts_sample_count": len(holders),
            "top10_ratio": None,
            "top10_ratio_source": "",
            "top10_ratio_pending_exclusion_filter": bool(holders),
            "basic_rpc_partial": bool(supply_err or largest_err),
            "basic_rpc_reason": ",".join(reasons),
        }

    def _empty_top10_selfcalc_shadow(self) -> Dict[str, Any]:
        return {
            "top10_raw_pct_self": None,
            "top10_owner_pct_self": None,
            "top10_effective_pct_self": None,
            "top10_effective_value_usd_self": None,
            "top1_effective_pct_self": None,
            "top1_effective_value_usd_self": None,
            "top10_calc_method_self": {
                "source": "solana_rpc_largest_accounts",
                "supply_basis": "total_supply",
                "raw": "token_account",
                "owner": "owner_aggregated",
                "effective": "owner_aggregated_minus_excluded",
                "owner_lookup": "not_attempted",
                "special_address_detection": [
                    "known_exclude_owners",
                    "owner_program_lookup",
                    "row_keyword_curve_pool",
                ],
                "insufficiency_reason": "",
            },
            "top10_exclusion_summary_self": {
                "manual_excluded_owner_count": 0,
                "curve_candidate_count": 0,
                "pool_candidate_count": 0,
                "program_owned_candidate_count": 0,
                "effective_excluded_owner_count": 0,
                "owner_lookup_missing_count": 0,
                "excluded_owner_samples": [],
                "insufficiency_reason": "",
            },
            "top10_holder_count_raw_self": 0,
            "top10_holder_count_owner_self": 0,
            "top10_holder_count_effective_self": 0,
        }

    async def _build_top10_selfcalc_shadow(
        self,
        mint: str,
        *,
        supply_res: Optional[dict] = None,
        largest_res: Optional[dict] = None,
        known_exclude_owners: Optional[set[str]] = None,
        unit_price_usd: Any = None,
    ) -> Dict[str, Any]:
        mint = str(mint or "").strip()
        out = self._empty_top10_selfcalc_shadow()
        method = out["top10_calc_method_self"]
        summary = out["top10_exclusion_summary_self"]

        if not mint or not self.helius_rpc_url:
            method["insufficiency_reason"] = "rpc_unavailable"
            summary["insufficiency_reason"] = "rpc_unavailable"
            return out

        if supply_res is None or largest_res is None:
            supply_res, largest_res = await asyncio.gather(
                self._helius_rpc("getTokenSupply", [mint]),
                self._helius_rpc("getTokenLargestAccounts", [mint]),
                return_exceptions=True,
            )

        if isinstance(supply_res, Exception) or isinstance(largest_res, Exception):
            method["insufficiency_reason"] = "supply_or_largest_accounts_failed"
            summary["insufficiency_reason"] = "supply_or_largest_accounts_failed"
            return out

        supply_val = (supply_res or {}).get("value", {}) if isinstance(supply_res, dict) else {}
        largest_accounts = (largest_res or {}).get("value", []) if isinstance(largest_res, dict) else []
        decimals = _to_int(supply_val.get("decimals"), 0)
        supply_raw_text = str(supply_val.get("amount") or "").strip()
        supply_raw = int(supply_raw_text) if supply_raw_text.isdigit() else 0

        supply_ui = _to_float(supply_val.get("uiAmount"), 0.0)
        if supply_ui <= 0:
            supply_ui = _to_float(supply_val.get("uiAmountString"), 0.0)
        if supply_ui <= 0 and supply_raw > 0:
            supply_ui = supply_raw / (10 ** max(0, decimals))

        raw_rows: List[Dict[str, Any]] = []
        for row in largest_accounts if isinstance(largest_accounts, list) else []:
            if not isinstance(row, dict):
                continue
            ui_amount = _to_float(row.get("uiAmount"), 0.0)
            if ui_amount <= 0:
                raw_amount_text = str(row.get("amount") or "").strip()
                if raw_amount_text.isdigit() and decimals >= 0:
                    ui_amount = int(raw_amount_text) / (10 ** max(0, decimals))
            if ui_amount <= 0:
                continue
            raw_rows.append(
                {
                    "account": str(row.get("address") or row.get("account") or "").strip(),
                    "ui_amount": float(ui_amount),
                    "label": str(row.get("label") or row.get("name") or "").strip(),
                    "tags": row.get("tags") if isinstance(row.get("tags"), list) else [],
                }
            )

        raw_rows.sort(key=lambda item: float(item.get("ui_amount") or 0.0), reverse=True)
        out["top10_holder_count_raw_self"] = len(raw_rows)

        if supply_ui <= 0:
            method["insufficiency_reason"] = "supply_missing"
            summary["insufficiency_reason"] = "supply_missing"
            return out

        if not raw_rows:
            method["insufficiency_reason"] = "largest_accounts_missing"
            summary["insufficiency_reason"] = "largest_accounts_missing"
            return out

        raw_top10_ui = sum(float(item.get("ui_amount") or 0.0) for item in raw_rows[:10])
        out["top10_raw_pct_self"] = round(min(100.0, max(0.0, (raw_top10_ui / supply_ui) * 100.0)), 4)

        addresses = [item["account"] for item in raw_rows if item.get("account")]
        if not addresses:
            method["owner_lookup"] = "unavailable"
            method["insufficiency_reason"] = "holder_accounts_missing"
            summary["insufficiency_reason"] = "holder_accounts_missing"
            return out

        try:
            token_accounts_res = await self._helius_rpc(
                "getMultipleAccounts",
                [addresses, {"encoding": "jsonParsed"}],
            )
        except Exception:
            token_accounts_res = None

        account_values = (token_accounts_res or {}).get("value", []) if isinstance(token_accounts_res, dict) else []
        if not isinstance(account_values, list) or not account_values:
            method["owner_lookup"] = "failed"
            method["insufficiency_reason"] = "owner_lookup_missing"
            summary["insufficiency_reason"] = "owner_lookup_missing"
            summary["owner_lookup_missing_count"] = len(addresses)
            return out

        owner_rows: List[Dict[str, Any]] = []
        unresolved_accounts = max(0, len(addresses) - len(account_values))
        for row, acct in zip(raw_rows, account_values):
            info = (((acct or {}).get("data") or {}).get("parsed") or {}).get("info", {}) if isinstance(acct, dict) else {}
            owner = str(info.get("owner") or "").strip()
            if not owner:
                unresolved_accounts += 1
                continue
            owner_rows.append(
                {
                    "account": row.get("account"),
                    "owner": owner,
                    "ui_amount": float(row.get("ui_amount") or 0.0),
                    "label": row.get("label") or "",
                    "tags": row.get("tags") or [],
                }
            )

        if not owner_rows:
            method["owner_lookup"] = "failed"
            method["insufficiency_reason"] = "owner_lookup_missing"
            summary["insufficiency_reason"] = "owner_lookup_missing"
            summary["owner_lookup_missing_count"] = len(addresses)
            return out

        if unresolved_accounts > 0:
            method["owner_lookup"] = "partial"
            method["insufficiency_reason"] = "owner_lookup_incomplete"
            summary["insufficiency_reason"] = "owner_lookup_incomplete"
            summary["owner_lookup_missing_count"] = unresolved_accounts
            return out

        method["owner_lookup"] = "complete"

        owner_totals: Dict[str, float] = {}
        owner_meta: Dict[str, Dict[str, Any]] = {}
        for item in owner_rows:
            owner_low = str(item["owner"]).lower()
            owner_totals[owner_low] = owner_totals.get(owner_low, 0.0) + float(item["ui_amount"])
            meta = owner_meta.setdefault(
                owner_low,
                {
                    "owner": item["owner"],
                    "labels": [],
                    "tags": [],
                },
            )
            label = str(item.get("label") or "").strip()
            if label:
                meta["labels"].append(label)
            tags = item.get("tags") if isinstance(item.get("tags"), list) else []
            if tags:
                meta["tags"].extend(str(tag) for tag in tags if tag)

        out["top10_holder_count_owner_self"] = len(owner_totals)
        owner_top10_ui = sum(sorted(owner_totals.values(), reverse=True)[:10])
        out["top10_owner_pct_self"] = round(min(100.0, max(0.0, (owner_top10_ui / supply_ui) * 100.0)), 4)

        unique_owners = [meta["owner"] for meta in owner_meta.values() if meta.get("owner")]
        owner_account_meta: Dict[str, Dict[str, Any]] = {}
        if unique_owners:
            try:
                owner_accounts_res = await self._helius_rpc(
                    "getMultipleAccounts",
                    [unique_owners, {"encoding": "base64"}],
                )
            except Exception:
                owner_accounts_res = None

            owner_account_values = (owner_accounts_res or {}).get("value", []) if isinstance(owner_accounts_res, dict) else []
            if isinstance(owner_account_values, list):
                for owner_addr, owner_acct in zip(unique_owners, owner_account_values):
                    owner_account_meta[str(owner_addr).lower()] = {
                        "exists": owner_acct is not None,
                        "executable": bool((owner_acct or {}).get("executable")) if isinstance(owner_acct, dict) else False,
                        "owner_program": str((owner_acct or {}).get("owner") or "").strip() if isinstance(owner_acct, dict) else "",
                    }

        excluded_manual = {str(owner or "").strip().lower() for owner in (known_exclude_owners or set()) if owner}
        effective_totals: Dict[str, float] = {}
        excluded_owner_samples: List[str] = []
        manual_excluded_count = 0
        curve_candidate_count = 0
        pool_candidate_count = 0
        program_owned_candidate_count = 0
        effective_excluded_owner_count = 0
        system_program_id = "11111111111111111111111111111111"

        for owner_low, total_ui in owner_totals.items():
            meta = owner_meta.get(owner_low) or {}
            owner_text_parts = [owner_low]
            owner_text_parts.extend(str(item or "") for item in meta.get("labels") or [])
            owner_text_parts.extend(str(item or "") for item in meta.get("tags") or [])
            owner_text = " ".join(owner_text_parts).lower()

            owner_account = owner_account_meta.get(owner_low) or {}
            owner_program = str(owner_account.get("owner_program") or "").strip()
            is_curve_candidate = any(keyword in owner_text for keyword in ("curve", "bonding"))
            is_pool_candidate = any(keyword in owner_text for keyword in ("pool", "lp", "liquidity", "amm", "vault"))
            is_program_owned_candidate = bool(
                owner_account.get("executable")
                or (owner_program and owner_program != system_program_id)
            )
            is_manual_excluded = owner_low in excluded_manual
            is_excluded = bool(
                is_manual_excluded
                or is_curve_candidate
                or is_pool_candidate
                or is_program_owned_candidate
            )

            if is_manual_excluded:
                manual_excluded_count += 1
            if is_curve_candidate:
                curve_candidate_count += 1
            if is_pool_candidate:
                pool_candidate_count += 1
            if is_program_owned_candidate:
                program_owned_candidate_count += 1

            if is_excluded:
                effective_excluded_owner_count += 1
                if len(excluded_owner_samples) < 5:
                    excluded_owner_samples.append(str(meta.get("owner") or owner_low))
                continue

            effective_totals[owner_low] = float(total_ui)

        summary["manual_excluded_owner_count"] = manual_excluded_count
        summary["curve_candidate_count"] = curve_candidate_count
        summary["pool_candidate_count"] = pool_candidate_count
        summary["program_owned_candidate_count"] = program_owned_candidate_count
        summary["effective_excluded_owner_count"] = effective_excluded_owner_count
        summary["excluded_owner_samples"] = excluded_owner_samples

        out["top10_holder_count_effective_self"] = len(effective_totals)
        if effective_totals:
            sorted_effective = sorted(effective_totals.values(), reverse=True)
            top10_effective_ui = sum(sorted_effective[:10])
            top1_effective_ui = float(sorted_effective[0])
            out["top10_effective_pct_self"] = round(
                min(100.0, max(0.0, (top10_effective_ui / supply_ui) * 100.0)),
                4,
            )
            out["top1_effective_pct_self"] = round(
                min(100.0, max(0.0, (top1_effective_ui / supply_ui) * 100.0)),
                4,
            )

            price_usd = _to_float(unit_price_usd, None)
            if price_usd is not None and price_usd > 0:
                out["top10_effective_value_usd_self"] = round(top10_effective_ui * price_usd, 4)
                out["top1_effective_value_usd_self"] = round(top1_effective_ui * price_usd, 4)
        elif effective_excluded_owner_count > 0:
            summary["insufficiency_reason"] = ""

        logger.info(
            "Top10SelfCalcTrace | mint=%s | raw=%s | owner=%s | effective=%s | raw_n=%s | owner_n=%s | effective_n=%s | excluded=%s | insuff=%s",
            mint[:8],
            out.get("top10_raw_pct_self"),
            out.get("top10_owner_pct_self"),
            out.get("top10_effective_pct_self"),
            out.get("top10_holder_count_raw_self"),
            out.get("top10_holder_count_owner_self"),
            out.get("top10_holder_count_effective_self"),
            summary.get("effective_excluded_owner_count"),
            method.get("insufficiency_reason") or summary.get("insufficiency_reason") or "",
        )
        return out

    async def _fetch_rpc_holder_snapshot(self, mint: str) -> Dict[str, Any]:
        mint = str(mint or "").strip()
        snap = await self._fetch_basic_rpc_supply_snapshot(mint)
        out = dict(snap or {})
        if not mint or not self.helius_rpc_url:
            return out

        try:
            supply_res, largest_res = await asyncio.gather(
                self._helius_rpc("getTokenSupply", [mint]),
                self._helius_rpc("getTokenLargestAccounts", [mint]),
            )
        except Exception:
            return out

        research = await self._build_top10_selfcalc_shadow(
            mint,
            supply_res=supply_res,
            largest_res=largest_res,
        )
        out.update(research)
        return out 

    def _detect_lp_status_phase_shadow(
        self,
        ca: str,
        market_data: Optional[dict] = None,
        metadata_bundle: Optional[dict] = None,
    ) -> Dict[str, Any]:
        market = dict(market_data or {})
        meta = dict(metadata_bundle or {})
        merged = dict(market)
        for key, value in meta.items():
            if value not in (None, "", {}, []):
                merged.setdefault(key, value)

        dex_id = str(merged.get("dex_id") or "").strip().lower()
        pair_address = str(merged.get("pair_address") or "").strip()
        pair_liquidity = _to_float(
            merged.get("pair_liquidity_usd"),
            _to_float(merged.get("liquidity_usd"), 0.0),
        )

        if self._should_probe_pump(ca, merged) or dex_id in {"pump", "pumpfun", "pump.fun"}:
            return {
                "lp_status_phase": "bonding_curve_phase",
                "lp_status_source": "pump_heuristic",
                "lp_status_confidence": 0.92,
                "lp_status_reason": "bonding curve / pump.fun phase detected; LP burn/lock not applicable yet",
                "lp_status_phase_conflict": False,
                "lp_status_source_conflict": False,
                "lp_status_conflict_reason": "",
            }

        if pair_liquidity > 100 or pair_address:
            return {
                "lp_status_phase": "amm_pool_phase",
                "lp_status_source": "dex_pair",
                "lp_status_confidence": 0.72,
                "lp_status_reason": "AMM pair detected, but LP burn/lock still pending slow-source validation",
                "lp_status_phase_conflict": False,
                "lp_status_source_conflict": False,
                "lp_status_conflict_reason": "",
            }

        return {
            "lp_status_phase": "unknown",
            "lp_status_source": "stage1_ultra_fast",
            "lp_status_confidence": 0.25,
            "lp_status_reason": "slow LP sources not queried yet",
            "lp_status_phase_conflict": False,
            "lp_status_source_conflict": False,
            "lp_status_conflict_reason": "",
        }

    def _build_lp_status_shadow(
        self,
        ca: str,
        market_data: Optional[dict] = None,
        rugcheck_data: Optional[dict] = None,
        metadata_bundle: Optional[dict] = None,
        goplus_data: Optional[dict] = None,
        prior_shadow: Optional[dict] = None,
    ) -> Dict[str, Any]:
        def _pct_or_none(value: Any) -> Optional[float]:
            if value in (None, ""):
                return None
            try:
                return float(value)
            except Exception:
                return None

        prior = dict(prior_shadow or {})
        if str(prior.get("lp_status_phase") or "").strip():
            phase_info = {
                "lp_status_phase": str(prior.get("lp_status_phase") or "unknown"),
                "lp_status_source": str(prior.get("lp_status_source") or "unknown"),
                "lp_status_confidence": float(prior.get("lp_status_confidence") or 0.0),
                "lp_status_reason": str(prior.get("lp_status_reason") or ""),
                "lp_status_phase_conflict": bool(prior.get("lp_status_phase_conflict")),
                "lp_status_source_conflict": bool(prior.get("lp_status_source_conflict")),
                "lp_status_conflict_reason": str(prior.get("lp_status_conflict_reason") or ""),
            }
        else:
            phase_info = self._detect_lp_status_phase_shadow(ca, market_data=market_data, metadata_bundle=metadata_bundle)

        out = {
            "lp_burned_pct": None,
            "lp_locked_pct": None,
            "lp_status_source": str(phase_info.get("lp_status_source") or "unknown"),
            "lp_status_confidence": float(phase_info.get("lp_status_confidence") or 0.0),
            "lp_status_reason": str(phase_info.get("lp_status_reason") or ""),
            "lp_status_phase": str(phase_info.get("lp_status_phase") or "unknown"),
            "lp_status_phase_conflict": bool(phase_info.get("lp_status_phase_conflict")),
            "lp_status_source_conflict": bool(phase_info.get("lp_status_source_conflict")),
            "lp_status_conflict_reason": str(phase_info.get("lp_status_conflict_reason") or ""),
        }

        rug = rugcheck_data if isinstance(rugcheck_data, dict) else {}
        gp = goplus_data if isinstance(goplus_data, dict) else {}

        lp_burned_pct = _pct_or_none(rug.get("lp_burned_pct"))
        lp_locked_pct = _pct_or_none(rug.get("lp_locked_pct"))

        if lp_burned_pct is not None or lp_locked_pct is not None:
            out["lp_burned_pct"] = lp_burned_pct
            out["lp_locked_pct"] = lp_locked_pct

            if out["lp_status_phase"] == "bonding_curve_phase":
                out["lp_status_phase_conflict"] = True
                out["lp_status_source_conflict"] = True
                out["lp_status_conflict_reason"] = (
                    "stage1 inferred bonding_curve_phase, but RugCheck reported LP percentage fields"
                )
                out["lp_status_reason"] = (
                    "bonding curve / pump.fun phase inferred in stage1, but follow-up RugCheck reported LP "
                    "percentage fields; review required before render/canonical merge"
                )
                out["lp_status_confidence"] = max(float(out.get("lp_status_confidence") or 0.0), 0.92)
                return out

            out["lp_status_source"] = "rugcheck_report"
            out["lp_status_phase"] = "amm_pool_phase"
            out["lp_status_confidence"] = 0.92 if lp_burned_pct is not None and lp_locked_pct is not None else 0.78
            out["lp_status_reason"] = "RugCheck market report returned LP percentage fields"
            return out

        if out["lp_status_phase"] == "bonding_curve_phase":
            return out

        if gp:
            out["lp_status_source"] = "stage2_followup_unconfirmed"
            out["lp_status_confidence"] = max(float(out.get("lp_status_confidence") or 0.0), 0.35)
            out["lp_status_reason"] = (
                "follow-up security sources queried, but LP burn/lock percentages are still unavailable"
            )
            return out

        return out

    async def _fetch_rpc_holder_top10_finalize_shadow(
        self,
        mint: str,
        known_exclude_owners: Optional[set[str]] = None,
        unit_price_usd: Any = None,
    ) -> Dict[str, Any]:
        mint = str(mint or "").strip()
        if not mint or not self.helius_rpc_url:
            return {}

        out: Dict[str, Any] = {
            "top10_ratio": None,
            "top10_ratio_source": "",
            "top10_ratio_pending_exclusion_filter": True,
            "top10_finalize_reason": "",
        }

        supply_res, largest_res = await asyncio.gather(
            self._helius_rpc("getTokenSupply", [mint]),
            self._helius_rpc("getTokenLargestAccounts", [mint]),
            return_exceptions=True,
        )

        if not isinstance(supply_res, Exception) and not isinstance(largest_res, Exception):
            out.update(
                await self._build_top10_selfcalc_shadow(
                    mint,
                    supply_res=supply_res if isinstance(supply_res, dict) else None,
                    largest_res=largest_res if isinstance(largest_res, dict) else None,
                    known_exclude_owners=known_exclude_owners,
                    unit_price_usd=unit_price_usd,
                )
            )

        if isinstance(supply_res, Exception) or isinstance(largest_res, Exception):
            out["top10_finalize_reason"] = "supply_or_largest_accounts_failed"
            return out

        supply_val = (supply_res or {}).get("value", {}) if isinstance(supply_res, dict) else {}
        largest_accounts = (largest_res or {}).get("value", []) if isinstance(largest_res, dict) else []

        decimals = _to_int(supply_val.get("decimals"), 0)
        supply_raw_text = str(supply_val.get("amount") or "").strip()
        supply_raw = int(supply_raw_text) if supply_raw_text.isdigit() else 0

        supply_ui = _to_float(supply_val.get("uiAmount"), 0.0)
        if supply_ui <= 0:
            supply_ui = _to_float(supply_val.get("uiAmountString"), 0.0)
        if supply_ui <= 0 and supply_raw > 0:
            supply_ui = supply_raw / (10 ** max(0, decimals))

        rows = largest_accounts if isinstance(largest_accounts, list) else []
        if not rows or supply_ui <= 0:
            out["top10_ratio_pending_exclusion_filter"] = bool(rows)
            out["top10_finalize_reason"] = "largest_accounts_missing" if not rows else "supply_missing"
            return out

        addresses = [str(row.get("address") or "").strip() for row in rows[:20] if isinstance(row, dict)]
        addresses = [addr for addr in addresses if addr]
        if not addresses:
            out["top10_finalize_reason"] = "holder_accounts_missing"
            return out

        if known_exclude_owners is None:
            out["top10_finalize_reason"] = "owner_data_available_but_exclusion_filter_unset"
            return out

        try:
            accounts_res = await self._helius_rpc("getMultipleAccounts", [addresses, {"encoding": "jsonParsed"}])
        except Exception:
            accounts_res = None

        account_values = (accounts_res or {}).get("value", []) if isinstance(accounts_res, dict) else []
        if not isinstance(account_values, list) or not account_values:
            out["top10_finalize_reason"] = "owner_lookup_missing"
            return out

        owner_rows = []
        for row, acct in zip(rows[:20], account_values):
            info = (((acct or {}).get("data") or {}).get("parsed") or {}).get("info", {}) if isinstance(acct, dict) else {}
            owner = str(info.get("owner") or "").strip()
            if not owner:
                continue

            ui_amount = _to_float((info.get("tokenAmount") or {}).get("uiAmount"), 0.0)
            if ui_amount <= 0:
                raw_amount_text = str((info.get("tokenAmount") or {}).get("amount") or row.get("amount") or "").strip()
                if raw_amount_text.isdigit() and decimals >= 0:
                    ui_amount = int(raw_amount_text) / (10 ** max(0, decimals))
            if ui_amount <= 0:
                continue

            owner_rows.append({"owner": owner, "ui_amount": ui_amount})

        if not owner_rows:
            out["top10_finalize_reason"] = "owner_lookup_missing"
            return out

        excluded = {str(owner or "").strip().lower() for owner in known_exclude_owners if owner}
        owner_totals: Dict[str, float] = {}
        for item in owner_rows:
            owner_low = item["owner"].lower()
            if owner_low in excluded:
                continue
            owner_totals[owner_low] = owner_totals.get(owner_low, 0.0) + float(item["ui_amount"])

        if not owner_totals:
            out["top10_finalize_reason"] = "all_large_holders_excluded"
            return out

        top10_ui = sum(sorted(owner_totals.values(), reverse=True)[:10])
        if top10_ui <= 0:
            out["top10_finalize_reason"] = "eligible_holder_amount_missing"
            return out

        pct = min(100.0, max(0.0, (top10_ui / supply_ui) * 100.0))
        out["top10_ratio"] = f"{pct:.2f}%"
        out["top10_ratio_source"] = "SOLANA_RPC"
        out["top10_ratio_pending_exclusion_filter"] = False
        out["top10_finalize_reason"] = "owner_aggregate_after_exclusion"
        return out

    async def get_token_info_stage1_shadow(self, ca: str) -> Dict[str, Any]:
        ca = str(ca or "").strip()
        if not ca:
            return {}

        dex_res, metadata_res, rpc_res = await asyncio.gather(
            self._shadow_source_call("dex", self._fetch_dexscreener(ca), 4.5),
            self._shadow_source_call("metadata", self._fetch_helius_metadata_bundle(ca), 4.0),
            self._shadow_source_call("basic_rpc", self._fetch_basic_rpc_supply_snapshot(ca), 4.5),
            return_exceptions=True,
        )

        dex_payload = self._coerce_shadow_source_result("dex", dex_res)
        metadata_payload = self._coerce_shadow_source_result("metadata", metadata_res)
        rpc_payload = self._coerce_shadow_source_result("basic_rpc", rpc_res)

        ds_data = dex_payload.get("data") if dex_payload.get("ok") and isinstance(dex_payload.get("data"), dict) else {}
        metadata_bundle = metadata_payload.get("data") if metadata_payload.get("ok") and isinstance(metadata_payload.get("data"), dict) else {}
        rpc_basic = rpc_payload.get("data") if rpc_payload.get("ok") and isinstance(rpc_payload.get("data"), dict) else {}

        source_status = {
            "dex": dex_payload.get("status"),
            "metadata": metadata_payload.get("status"),
            "basic_rpc": rpc_payload.get("status"),
        }
        source_errors = [
            f"{item['source']}:{item['error']}"
            for item in (dex_payload, metadata_payload, rpc_payload)
            if not item.get("ok")
        ]

        result: Dict[str, Any] = {
            "symbol": "UNK",
            "name": "",
            "price_usd": 0,
            "cap_usd": 0,
            "pair_liquidity_usd": None,
            "liquidity_usd": None,
            "estimated_pair_liquidity_usd": None,
            "market_data_ready": False,
            "liquidity_data_ready": False,
            "liquidity_source_error": "",
            "volume_h24": 0,
            "buys_24h": 0,
            "sells_24h": 0,
            "buy_sell_ratio": 0.0,
            "token_age_min": 0,
            "token_image_url": "",
            "token_image_source": "",
            "top10_ratio": None,
            "top10_ratio_source": "",
            "top10_ratio_pending_exclusion_filter": False,
            "largest_accounts_present": False,
            "largest_accounts_sample_count": 0,
            "fastpath_shadow_stage": "stage1_ultra_fast",
            "slow_followup_required": True,
            "authority_fields_pending": True,
            "stage1_source_status": source_status,
            "stage1_source_errors": source_errors,
            "stage1_partial_degraded": bool(source_errors),
        }
        liquidity_errors: List[str] = []

        pairs = ds_data.get("pairs", []) if isinstance(ds_data, dict) else []
        if not dex_payload.get("ok"):
            liquidity_errors.append(f"DEX_{str(dex_payload.get('status') or 'error').upper()}")
        elif not pairs:
            liquidity_errors.append("DEXSCREENER_NO_PAIRS")

        if pairs:
            valid_pairs = [p for p in pairs if isinstance(p, dict)]
            best = max(
                valid_pairs,
                key=lambda p: _to_float((p.get("liquidity") or {}).get("usd"), 0.0),
            )

            info = best.get("info", {}) or {}
            base = best.get("baseToken", {}) or {}
            pair_liq_raw = _to_float((best.get("liquidity") or {}).get("usd"), 0.0)

            result["market_data_ready"] = True
            result["symbol"] = str(base.get("symbol") or "UNK").strip() or "UNK"
            result["name"] = str(base.get("name") or "").strip()
            result["price_usd"] = best.get("priceUsd") or 0
            result["cap_usd"] = _to_float(best.get("marketCap") or best.get("fdv"), 0.0)
            result["volume_h24"] = _to_float((best.get("volume") or {}).get("h24"), 0.0)

            h24 = (best.get("txns") or {}).get("h24", {}) if isinstance(best.get("txns"), dict) else {}
            result["buys_24h"] = _to_int(h24.get("buys", 0))
            result["sells_24h"] = _to_int(h24.get("sells", 0))
            sells = result["sells_24h"]
            result["buy_sell_ratio"] = (result["buys_24h"] / sells) if sells > 0 else 999.0

            created = best.get("pairCreatedAt")
            if _to_float(created, 0.0) > 0:
                result["token_age_min"] = max(0, int((time.time() * 1000 - float(created)) / 60000))

            dex_image = self._normalize_image_url(
                info.get("imageUrl")
                or base.get("logoURI")
                or base.get("imageUrl")
                or ""
            )
            if dex_image:
                result["token_image_url"] = dex_image
                result["token_image_source"] = "dexscreener"

            if pair_liq_raw >= 100.0:
                result["pair_liquidity_usd"] = pair_liq_raw
                result["liquidity_usd"] = pair_liq_raw
                result["liquidity_data_ready"] = True
            elif pair_liq_raw > 0:
                result["estimated_pair_liquidity_usd"] = pair_liq_raw
                liquidity_errors.append("DEX_LIQUIDITY_WEAK")
            else:
                liquidity_errors.append("DEX_LIQUIDITY_MISSING")

            result["dex_id"] = str(best.get("dexId") or "").lower()
            result["pair_address"] = best.get("pairAddress")

        if isinstance(metadata_bundle, dict):
            if result.get("symbol") == "UNK" and metadata_bundle.get("symbol"):
                result["symbol"] = str(metadata_bundle.get("symbol") or "").strip() or "UNK"
            if not result.get("name") and metadata_bundle.get("name"):
                result["name"] = str(metadata_bundle.get("name") or "").strip()
            if not result.get("token_image_url") and metadata_bundle.get("token_image_url"):
                result["token_image_url"] = metadata_bundle.get("token_image_url")
                result["token_image_source"] = metadata_bundle.get("token_image_source") or "metadata"
            if metadata_bundle.get("metadata_json_uri"):
                result["metadata_json_uri"] = metadata_bundle.get("metadata_json_uri")

        if isinstance(rpc_basic, dict):
            for key in (
                "supply_raw",
                "supply_ui",
                "largest_accounts_present",
                "largest_accounts_sample_count",
                "top10_ratio_pending_exclusion_filter",
                "basic_rpc_partial",
                "basic_rpc_reason",
            ):
                if key in rpc_basic:
                    result[key] = rpc_basic.get(key)

        lp_status = self._build_lp_status_shadow(ca, market_data=result, metadata_bundle=metadata_bundle)
        result.update(lp_status)

        if not result.get("liquidity_data_ready") and not liquidity_errors:
            liquidity_errors.append("LIQUIDITY_UNAVAILABLE")
        result["liquidity_source_error"] = ",".join(dict.fromkeys(err for err in liquidity_errors if err))
        return result

    async def get_token_info_stage2_shadow(
        self,
        ca: str,
        stage1_payload: Optional[dict] = None,
        known_exclude_owners: Optional[set[str]] = None,
    ) -> Dict[str, Any]:
        ca = str(ca or "").strip()
        if not ca:
            return {}

        base = dict(stage1_payload or {})

        async def _top10_finalize_call() -> Dict[str, Any]:
            try:
                return await self._fetch_rpc_holder_top10_finalize_shadow(
                    ca,
                    known_exclude_owners=known_exclude_owners,
                    unit_price_usd=base.get("price_usd"),
                )
            except TypeError:
                return await self._fetch_rpc_holder_top10_finalize_shadow(
                    ca,
                    known_exclude_owners=known_exclude_owners,
                )

        rug_res, goplus_res, top10_res = await asyncio.gather(
            self._shadow_source_call("rugcheck", self.fetch_rugcheck_data(ca), 6.0),
            self._shadow_source_call("goplus", self.fetch_goplus_security(ca), 6.5),
            self._shadow_source_call(
                "top10_finalize",
                _top10_finalize_call(),
                10.0,
            ),
            return_exceptions=True,
        )

        rug_payload = self._coerce_shadow_source_result("rugcheck", rug_res)
        goplus_payload = self._coerce_shadow_source_result("goplus", goplus_res)
        top10_payload = self._coerce_shadow_source_result("top10_finalize", top10_res)

        rugcheck_data = rug_payload.get("data") if rug_payload.get("ok") and isinstance(rug_payload.get("data"), dict) else {}
        goplus_data = goplus_payload.get("data") if goplus_payload.get("ok") and isinstance(goplus_payload.get("data"), dict) else {}
        top10_final = top10_payload.get("data") if top10_payload.get("ok") and isinstance(top10_payload.get("data"), dict) else {}

        source_status = {
            "rugcheck": rug_payload.get("status"),
            "goplus": goplus_payload.get("status"),
            "top10_finalize": top10_payload.get("status"),
        }
        source_errors = [
            f"{item['source']}:{item['error']}"
            for item in (rug_payload, goplus_payload, top10_payload)
            if not item.get("ok")
        ]

        out: Dict[str, Any] = {
            "fastpath_shadow_stage": "stage2_followup_enrich",
            "slow_followup_required": False,
            "stage2_source_status": source_status,
            "stage2_source_errors": source_errors,
            "stage2_partial_degraded": bool(source_errors),
        }

        lp_status = self._build_lp_status_shadow(
            ca,
            market_data=base,
            rugcheck_data=rugcheck_data,
            metadata_bundle=base,
            goplus_data=goplus_data,
            prior_shadow=base,
        )
        out.update(lp_status)

        if isinstance(rugcheck_data, dict):
            if rugcheck_data.get("rugcheck_score") is not None:
                out["rugcheck_score"] = _to_float(rugcheck_data.get("rugcheck_score"), 0.0)

        if isinstance(goplus_data, dict):
            for key in ("is_honeypot", "is_blacklisted", "is_mintable", "transfer_pausable"):
                if goplus_data.get(key) is not None:
                    out[key] = goplus_data.get(key)

        if isinstance(top10_final, dict) and top10_final:
            for key in (
                "top10_ratio",
                "top10_ratio_source",
                "top10_ratio_pending_exclusion_filter",
                "top10_finalize_reason",
                "top10_raw_pct_self",
                "top10_owner_pct_self",
                "top10_effective_pct_self",
                "top10_effective_value_usd_self",
                "top1_effective_pct_self",
                "top1_effective_value_usd_self",
                "top10_calc_method_self",
                "top10_exclusion_summary_self",
                "top10_holder_count_raw_self",
                "top10_holder_count_owner_self",
                "top10_holder_count_effective_self",
            ):
                if key in top10_final:
                    out[key] = top10_final.get(key)
        elif not top10_payload.get("ok"):
            out["top10_ratio_pending_exclusion_filter"] = True
            out["top10_finalize_reason"] = f"top10_finalize_{top10_payload.get('status') or 'error'}"

        return out
    
    async def _prime_first_card_avatar_fastpath(self, ca: str, token_data: dict) -> dict:
        td = dict(token_data or {})
        if td.get("token_image_path"):
            return td

        try:
            stable_avatar_path = self._existing_avatar_path(ca)
        except Exception:
            stable_avatar_path = ""

        if stable_avatar_path:
            td["token_image_path"] = stable_avatar_path
            if not td.get("token_image_source"):
                td["token_image_source"] = "stable_cache"
            return td

        trusted_sources = {"stable_cache", "dexscreener", "metadata", "helius", "das", "api"}
        deadline_at = time.perf_counter() + 0.90

        async def _materialize(url: str, source: str) -> bool:
            norm_url = self._normalize_image_url(url or "")
            norm_source = self._normalize_avatar_source(source or "", norm_url)
            if not norm_url or norm_source not in trusted_sources:
                return False

            td["token_image_url"] = norm_url
            td["token_image_source"] = norm_source

            timeout_left = max(0.05, deadline_at - time.perf_counter())
            if timeout_left <= 0:
                return False

            try:
                avatar_path = await asyncio.wait_for(
                    self.ensure_token_avatar(ca, norm_url, source=norm_source, fast_mode=True),
                    timeout=timeout_left,
                )
            except Exception:
                avatar_path = None

            if avatar_path:
                td["token_image_path"] = avatar_path
                return True
            return False

        current_url = self._normalize_image_url(td.get("token_image_url") or "")
        current_source = self._normalize_avatar_source(td.get("token_image_source") or "", current_url)
        if current_url and current_source in trusted_sources:
            if await _materialize(current_url, current_source):
                return td

        dex_fn = getattr(self, "_fetch_dex_avatar_url", None)
        if callable(dex_fn) and time.perf_counter() < deadline_at:
            try:
                dex_url, dex_source = await asyncio.wait_for(
                    dex_fn(ca),
                    timeout=max(0.05, deadline_at - time.perf_counter()),
                )
            except Exception:
                dex_url, dex_source = "", ""
            if dex_url and await _materialize(dex_url, dex_source):
                return td

        metadata_fn = getattr(self, "_fetch_metadata_avatar_url", None)
        if callable(metadata_fn) and time.perf_counter() < deadline_at:
            try:
                meta_url, meta_source = await asyncio.wait_for(
                    metadata_fn(ca, td),
                    timeout=max(0.05, deadline_at - time.perf_counter()),
                )
            except TypeError:
                try:
                    meta_url, meta_source = await asyncio.wait_for(
                        metadata_fn(ca),
                        timeout=max(0.05, deadline_at - time.perf_counter()),
                    )
                except Exception:
                    meta_url, meta_source = "", ""
            except Exception:
                meta_url, meta_source = "", ""
            if meta_url and await _materialize(meta_url, meta_source):
                return td

        return td

    async def get_token_info_fastpath(self, ca: str) -> Dict[str, Any]:
        ca = str(ca or "").strip()
        if not ca:
            return {}

        async def _timed(coro, timeout_s: float, default):
            try:
                return await asyncio.wait_for(coro, timeout=float(timeout_s))
            except Exception:
                return default

        def _strip_page_fields(payload: dict) -> dict:
            out = dict(payload or {})
            explicit_page_keys = {
                "raw_data",
                "screenshot",
                "chart_screenshot",
                "page_text",
                "visible_text",
                "combined_text",
                "header_block",
                "safety_block",
                "holder_tags_block",
                "top10_context",
            }
            for key in list(out.keys()):
                low = str(key or "").lower()
                if key in explicit_page_keys:
                    out.pop(key, None)
                    continue
                if low.startswith("gmgn_"):
                    out.pop(key, None)
                    continue
                if low.startswith("observed_"):
                    out.pop(key, None)
                    continue
                if low.startswith("page_"):
                    out.pop(key, None)
                    continue
            return out

        stage1_fn = getattr(self, "get_token_info_stage1_shadow", None)
        stage2_fn = getattr(self, "get_token_info_stage2_shadow", None)
        helius_fn = getattr(self, "get_helius_security", None)
        compat_rpc_fn = getattr(self, "_fetch_rpc_holder_snapshot", None)

        async def _empty():
            return {}

        stage1_task = _timed(stage1_fn(ca), 10.0, {}) if callable(stage1_fn) else _timed(_empty(), 0.01, {})
        helius_task = _timed(helius_fn(ca), 6.0, {}) if callable(helius_fn) else _timed(_empty(), 0.01, {})
        compat_rpc_task = _timed(compat_rpc_fn(ca), 6.0, {}) if callable(compat_rpc_fn) else _timed(_empty(), 0.01, {})

        stage1_payload, helius_sec, compat_rpc = await asyncio.gather(
            stage1_task,
            helius_task,
            compat_rpc_task,
            return_exceptions=False,
        )

        stage1_payload = dict(stage1_payload or {})
        helius_sec = dict(helius_sec or {})
        compat_rpc = dict(compat_rpc or {})

        stage2_payload: Dict[str, Any] = {}
        if callable(stage2_fn):
            stage2_payload = await _timed(stage2_fn(ca, stage1_payload=stage1_payload), 18.0, {})
            stage2_payload = dict(stage2_payload or {})

        result = dict(stage1_payload)

        for key in (
            "fastpath_shadow_stage",
            "slow_followup_required",
            "stage1_source_status",
            "stage1_source_errors",
            "stage1_partial_degraded",
            "stage2_source_status",
            "stage2_source_errors",
            "stage2_partial_degraded",
            "rugcheck_score",
            "is_honeypot",
            "is_blacklisted",
            "is_mintable",
            "transfer_pausable",
            "lp_burned_pct",
            "lp_locked_pct",
            "lp_status_source",
            "lp_status_confidence",
            "lp_status_reason",
            "lp_status_phase",
            "lp_status_phase_conflict",
            "lp_status_source_conflict",
            "lp_status_conflict_reason",
            "top10_finalize_reason",
            "top10_raw_pct_self",
            "top10_owner_pct_self",
            "top10_effective_pct_self",
            "top10_effective_value_usd_self",
            "top1_effective_pct_self",
            "top1_effective_value_usd_self",
            "top10_calc_method_self",
            "top10_exclusion_summary_self",
            "top10_holder_count_raw_self",
            "top10_holder_count_owner_self",
            "top10_holder_count_effective_self",
        ):
            if key in stage2_payload:
                result[key] = stage2_payload.get(key)

        if helius_sec:
            result["helius_security"] = dict(helius_sec)
            for key in ("mint_authority_present", "freeze_authority_present"):
                if helius_sec.get(key) is not None:
                    result[key] = helius_sec.get(key)

        if compat_rpc:
            for key in (
                "holder_count_estimate",
                "top10_holder_count",
                "supply_raw",
                "supply_ui",
                "top10_ratio_pending_exclusion_filter",
                "top10_raw_pct_self",
                "top10_owner_pct_self",
                "top10_effective_pct_self",
                "top10_effective_value_usd_self",
                "top1_effective_pct_self",
                "top1_effective_value_usd_self",
                "top10_calc_method_self",
                "top10_exclusion_summary_self",
                "top10_holder_count_raw_self",
                "top10_holder_count_owner_self",
                "top10_holder_count_effective_self",
            ):
                if compat_rpc.get(key) is not None:
                    result[key] = compat_rpc.get(key)

        pending_filter = stage2_payload.get("top10_ratio_pending_exclusion_filter")
        if pending_filter is None:
            pending_filter = compat_rpc.get("top10_ratio_pending_exclusion_filter")
        if pending_filter is None:
            pending_filter = stage1_payload.get("top10_ratio_pending_exclusion_filter")
        result["top10_ratio_pending_exclusion_filter"] = bool(pending_filter)

        candidate_top10 = None
        candidate_source = ""

        if (
            "top10_ratio" in stage2_payload
            and stage2_payload.get("top10_ratio") not in (None, "", "?", "❓", "UNK")
        ):
            candidate_top10 = stage2_payload.get("top10_ratio")
            candidate_source = str(stage2_payload.get("top10_ratio_source") or "").strip().upper()
        elif (
            "top10_ratio" in compat_rpc
            and compat_rpc.get("top10_ratio") not in (None, "", "?", "❓", "UNK")
        ):
            candidate_top10 = compat_rpc.get("top10_ratio")
            candidate_source = str(compat_rpc.get("top10_ratio_source") or "").strip().upper()
        elif (
            "top10_ratio" in stage1_payload
            and stage1_payload.get("top10_ratio") not in (None, "", "?", "❓", "UNK")
        ):
            candidate_top10 = stage1_payload.get("top10_ratio")
            candidate_source = str(stage1_payload.get("top10_ratio_source") or "").strip().upper()

        if (
            candidate_source in {"SOLANA_RPC", "BITQUERY", "HELIUS"}
            and candidate_top10 not in (None, "", "?", "❓", "UNK")
            and not result.get("top10_ratio_pending_exclusion_filter")
        ):
            result["top10_ratio"] = candidate_top10
            result["top10_ratio_source"] = candidate_source
        else:
            result["top10_ratio"] = None
            result["top10_ratio_source"] = ""

        lp_burned_pct = result.get("lp_burned_pct")
        lp_locked_pct = result.get("lp_locked_pct")
        if lp_burned_pct is not None:
            result["is_burned"] = _to_float(lp_burned_pct, 0.0) > 0
        if lp_locked_pct is not None:
            result["is_locked"] = _to_float(lp_locked_pct, 0.0) > 0

        result = _strip_page_fields(result)
        return result

    def passive_attach_read_gmgn(self, ca: str, tab=None) -> Dict[str, Any]:
        def _invalid(reason: str, snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            snap = snapshot if isinstance(snapshot, dict) else {}
            return {
                "gmgn_result_strength": "invalid",
                "gmgn_followup_required": True,
                "gmgn_fast_needs_followup": True,
                "gmgn_followup_priority": "high",
                "gmgn_fast_weak_reason": str(reason or "page_invalid"),
                "gmgn_observed_non_authoritative": True,
                "gmgn_observed_top10_ratio": None,
                "gmgn_observed_header_liq_usd": 0,
                "gmgn_observed_dex_paid": None,
                "gmgn_observed_burned": None,
                "gmgn_observed_locked": None,
                "gmgn_observed_mint_authority_present": None,
                "gmgn_observed_freeze_authority_present": None,
                "gmgn_observed_raw_tags": {},
                "gmgn_observed_tag_non_null_count": 0,
                "gmgn_observed_tags_present": False,
                "gmgn_page_blocked_reason": str(snap.get("blocked_reason") or reason or ""),
                "gmgn_popup_reason": str(snap.get("popup_reason") or ""),
                "gmgn_overlay_visible": bool(snap.get("overlay_visible")),
                "gmgn_error_reason": str(snap.get("error_reason") or ""),
                "screenshot": "",
            }

        live_tab = tab or self._gmgn_tab
        if not live_tab:
            return _invalid("tab_missing", {"blocked_reason": "tab_missing"})

        gate_fn = getattr(self, "_gmgn_page_gate_state_passive", None)
        if not callable(gate_fn):
            return _invalid("passive_gate_missing", {"blocked_reason": "passive_gate_missing"})

        snapshot = gate_fn(live_tab, str(ca or "").strip())
        if not isinstance(snapshot, dict) or not snapshot.get("valid"):
            return _invalid(str((snapshot or {}).get("blocked_reason") or "page_invalid"), snapshot)

        block_reader = getattr(self, "_extract_gmgn_block_snippet", None)
        if not callable(block_reader):
            return _invalid("block_reader_missing", {"blocked_reason": "block_reader_missing"})

        header_block = block_reader(
            live_tab,
            ["Market Cap", "市值", "Liquidity", "池子", "24h Volume", "1m", "5m"],
        )
        safety_block = block_reader(
            live_tab,
            ["Dex Paid", "Dex付费", "LP Burned", "烧池子", "Liquidity Locked", "Mint", "Freeze"],
        )
        tags_block = block_reader(
            live_tab,
            ["Smart Money", "KOL", "Blue Chip", "Sniper", "Rat", "Dev", "Bundle", "Phishing"],
        )
        top10_context = self._extract_gmgn_top10_context(live_tab)

        result: Dict[str, Any] = {
            "gmgn_result_strength": "weak",
            "gmgn_followup_required": False,
            "gmgn_fast_needs_followup": False,
            "gmgn_followup_priority": "normal",
            "gmgn_fast_weak_reason": "",
            "gmgn_observed_non_authoritative": True,
            "gmgn_observed_top10_ratio": None,
            "gmgn_observed_header_liq_usd": 0,
            "gmgn_observed_dex_paid": None,
            "gmgn_observed_burned": None,
            "gmgn_observed_locked": None,
            "gmgn_observed_mint_authority_present": None,
            "gmgn_observed_freeze_authority_present": None,
            "gmgn_observed_raw_tags": {},
            "gmgn_observed_tag_non_null_count": 0,
            "gmgn_observed_tags_present": False,
            "gmgn_page_blocked_reason": "",
            "gmgn_popup_reason": str(snapshot.get("popup_reason") or ""),
            "gmgn_overlay_visible": bool(snapshot.get("overlay_visible")),
            "gmgn_error_reason": str(snapshot.get("error_reason") or ""),
            "screenshot": "",
        }

        mcap_val = self._extract_gmgn_money_value(header_block, ["市值", "market cap", "mcap", "mc"], max_gap=16)
        liq_raw = self._extract_gmgn_money_raw(header_block, ["池子", "liquidity", "lp"], max_gap=16)
        liq_val = self._extract_gmgn_money_value(header_block, ["池子", "liquidity", "lp"], max_gap=16)
        liq_ok, _ = self._assess_gmgn_header_liquidity(liq_raw, liq_val, mcap_val)
        if liq_ok and _to_float(liq_val, 0.0) > 0:
            result["gmgn_observed_header_liq_usd"] = _to_float(liq_val, 0.0)

        dex_paid = self._extract_gmgn_dex_paid_state(safety_block)
        burned = self._extract_gmgn_burn_state(safety_block)
        locked = self._extract_gmgn_lock_state(safety_block)
        mintable = self._extract_gmgn_mint_state(safety_block)
        freezeable = self._extract_gmgn_freeze_state(safety_block)

        if dex_paid is not None:
            result["gmgn_observed_dex_paid"] = dex_paid
        if burned is not None:
            result["gmgn_observed_burned"] = burned
        if locked is not None:
            result["gmgn_observed_locked"] = locked
        if mintable is not None:
            result["gmgn_observed_mint_authority_present"] = mintable
        if freezeable is not None:
            result["gmgn_observed_freeze_authority_present"] = freezeable

        top10_ratio = self._extract_gmgn_top10_ratio(top10_context)
        if top10_ratio:
            result["gmgn_observed_top10_ratio"] = top10_ratio

        tag_map = {
            "smart": ["Smart Money", "聪明钱", "Smart"],
            "kol": ["KOL"],
            "blue_chip": ["Blue Chip", "蓝筹"],
            "sniper": ["Sniper", "狙击手"],
            "rat": ["Rat", "Rat Farm", "老鼠仓"],
            "dev": ["Dev", "Developer"],
            "bundle": ["Bundle", "Bundled", "捆绑"],
            "phishing_wallets": ["Phishing", "Fish", "钓鱼钱包"],
        }
        tags_low = str(tags_block or "").lower()
        observed_tags: Dict[str, Any] = {}
        for key, labels in tag_map.items():
            hit = any(str(label or "").lower() in tags_low for label in labels)
            observed_tags[key] = True if hit else None

        result["gmgn_observed_raw_tags"] = observed_tags
        result["gmgn_observed_tag_non_null_count"] = sum(1 for value in observed_tags.values() if value is not None)
        result["gmgn_observed_tags_present"] = bool(result["gmgn_observed_tag_non_null_count"] > 0)

        observed_signal_count = 0
        if result.get("gmgn_observed_top10_ratio"):
            observed_signal_count += 1
        if _to_float(result.get("gmgn_observed_header_liq_usd"), 0.0) > 0:
            observed_signal_count += 1
        safety_count = sum(
            1
            for key in (
                "gmgn_observed_dex_paid",
                "gmgn_observed_burned",
                "gmgn_observed_locked",
                "gmgn_observed_mint_authority_present",
                "gmgn_observed_freeze_authority_present",
            )
            if result.get(key) is not None
        )
        if safety_count >= 2:
            observed_signal_count += 1
        if result.get("gmgn_observed_tag_non_null_count", 0) > 0:
            observed_signal_count += 1

        if observed_signal_count >= 2:
            result["gmgn_result_strength"] = "strong"
        else:
            result["gmgn_result_strength"] = "weak"
            result["gmgn_followup_required"] = True
            result["gmgn_fast_needs_followup"] = True
            result["gmgn_fast_weak_reason"] = "passive_attach_thin"

        return result

    def _gmgn_high_priority_waiting(self, ca: str, priority: str = "normal") -> bool:
        try:
            if str(priority or "").lower() == "high":
                return False
            return bool(
                int(self._gmgn_pending_high or 0) > 0
                or (
                self._gmgn_priority_ca
                and self._gmgn_priority_ca != ca
                and time.time() < float(self._gmgn_priority_until or 0.0)
                )
            )
        except Exception:
            return False

    async def _gmgn_mark_pending(self, priority: str, delta: int) -> int:
        async with self._gmgn_pending_lock:
            if str(priority or "").lower() == "high":
                self._gmgn_pending_high = max(0, int(self._gmgn_pending_high or 0) + int(delta))
            else:
                self._gmgn_pending_normal = max(0, int(self._gmgn_pending_normal or 0) + int(delta))
            return int(self._gmgn_pending_high or 0) + int(self._gmgn_pending_normal or 0)

    def _gmgn_queue_len(self) -> int:
        try:
            return int(self._gmgn_pending_high or 0) + int(self._gmgn_pending_normal or 0)
        except Exception:
            return 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                trust_env=True
            )
        return self._session

    def _has_saved_gmgn_profile(self) -> bool:
        try:
            if not os.path.isdir(self.profile_dir):
                return False
            if not os.path.exists(self.gmgn_marker_path):
                return False
            return bool(self._load_gmgn_saved_state())
        except Exception:
            return False

    async def prepare_browser_profile(self):
        os.makedirs(self.profile_dir, exist_ok=True)
        status: Dict[str, Any] = {
            "role": self._fetcher_role,
            "ready": False,
            "active_state": "",
            "blocked_reason": "",
            "persisted": False,
        }
        if not await self._ensure_browser():
            logger.warning("⚠️ 浏览器持久化引擎预热失败: browser_unavailable")
            status["blocked_reason"] = "browser_unavailable"
            return status

        saved_state = self._load_gmgn_saved_state()
        warm_state = "saved_state" if saved_state else "fresh_state"

        async with self._gmgn_lock:
            try:
                tab = await asyncio.to_thread(self._get_or_create_gmgn_tab)
                if not tab:
                    raise RuntimeError("gmgn_tab_unavailable")

                if saved_state:
                    warmed = await asyncio.to_thread(self._bootstrap_gmgn_tab_layout, tab, saved_state)
                    if not warmed:
                        target_url = self._build_gmgn_token_url(
                            (saved_state or {}).get("template_token") or self.gmgn_template_token,
                            state=saved_state,
                        )
                        await asyncio.to_thread(tab.get, target_url)
                        try:
                            await asyncio.to_thread(lambda: tab.wait.ele("tag:body", timeout=8))
                        except Exception:
                            pass
                        try:
                            await asyncio.to_thread(self._apply_gmgn_saved_state, tab, saved_state, False)
                        except Exception:
                            pass
                        try:
                            await asyncio.to_thread(self._finish_gmgn_walkthrough, tab, 8, 0.20)
                        except Exception:
                            pass
                else:
                    await asyncio.to_thread(tab.get, self._default_gmgn_layout_url())
                    try:
                        await asyncio.to_thread(lambda: tab.wait.ele("tag:body", timeout=8))
                    except Exception:
                        pass
                    try:
                        await asyncio.to_thread(self._inject_gmgn_local_flags, tab)
                    except Exception:
                        pass
                    try:
                        await asyncio.to_thread(self._finish_gmgn_walkthrough, tab, 8, 0.20)
                    except Exception:
                        pass

                persisted = False
                try:
                    persisted = bool(await asyncio.to_thread(self._persist_gmgn_runtime_state, tab))
                except Exception:
                    persisted = False
            except Exception as e:
                logger.warning(f"⚠️ 浏览器持久化引擎预热失败: {e}")
                status["blocked_reason"] = str(e)
                return status

        logger.info("✅ 浏览器持久化引擎已就绪 (GMGN warm state=%s)", warm_state)
        status.update(
            {
                "ready": True,
                "active_state": warm_state,
                "persisted": persisted,
            }
        )
        return status

    def _init_browser_sync(self) -> bool:
        try:
            if self._browser and getattr(self._browser, "process_id", None):
                return True
            co = ChromiumOptions().set_user_data_path(self.profile_dir).auto_port()
            co.headless(False)
            co.set_argument("--window-position=-32000,-32000")
            co.set_argument("--window-size=1920,1080")
            co.set_argument("--disable-popup-blocking")
            co.set_argument("--disable-notifications")
            co.mute(True)
            self._browser = ChromiumPage(co)
            return True
        except Exception as e:
            logger.error(f"❌ 浏览器初始化失败: {e}")
            return False

    async def _ensure_browser(self):
        async with self._browser_lock:
            if self._browser and getattr(self._browser, "process_id", None):
                return True
            return await asyncio.to_thread(self._init_browser_sync)

    async def _reset_browser(self):
        async with self._browser_lock:
            if self._browser:
                try:
                    await asyncio.to_thread(self._browser.quit)
                except Exception:
                    pass
            self._gmgn_tab = None
            self._browser = None

    def _default_gmgn_layout_url(self) -> str:
        return f"https://gmgn.ai/sol/token/{self.gmgn_template_token}?chain=sol"

    def _read_gmgn_state_file(self) -> Dict[str, Any]:
        return self._read_gmgn_state_file_from_path(self.gmgn_state_path)

    def _sanitize_gmgn_layout_url(self, url: str) -> str:
        text = str(url or "").strip()
        if not text.startswith("http") or "gmgn.ai" not in text:
            return ""
        return text

    def _is_usable_gmgn_work_url(self, url: str, title_text: str = "") -> bool:
        text = self._sanitize_gmgn_layout_url(url)
        if not text:
            return False
        low = text.lower()
        if "gmgn.ai" not in low:
            return False
        parsed = urlparse(text)
        path = str(parsed.path or "").strip().lower()
        if path in {"", "/", "/sol", "/sol/", "/discover", "/home"}:
            return False
        if "/sol/token/" not in path:
            return False
        token = self._extract_token_from_gmgn_url(text)
        if not token:
            return False
        if token.lower() in {"undefined", "null", "token", "address", "ca"}:
            return False
        title_low = str(title_text or "").strip().lower()
        bad_markers = [
            "welcome",
            "tutorial",
            "guide",
            "getting started",
            "loading",
            "initialize",
            "初始化",
            "欢迎",
            "引导",
            "unexpected application error",
            "not found",
            "404",
        ]
        return not any(marker in title_low for marker in bad_markers)

    def _gmgn_state_paths_for_role(self, role: str) -> Dict[str, str]:
        normalized_role = "background" if str(role or "").strip().lower() == "background" else "interactive"
        data_dir = os.path.dirname(self.profile_dir)
        profile_name = "browser_profile_background" if normalized_role == "background" else "browser_profile_interactive"
        profile_dir = os.path.join(data_dir, profile_name)
        return {
            "profile_dir": profile_dir,
            "gmgn_state_path": os.path.join(profile_dir, "gmgn_runtime_state.json"),
            "gmgn_marker_path": os.path.join(profile_dir, ".gmgn_profile_ready"),
        }

    def _read_gmgn_state_file_from_path(self, path: str) -> Dict[str, Any]:
        try:
            if not path or not os.path.exists(path):
                return {}
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"⚠️ GMGN 页面状态读取失败: {e}")
            return {}

    def _write_gmgn_state_file_to_path(self, state: dict, state_path: str, marker_path: str) -> bool:
        try:
            if not isinstance(state, dict):
                return False
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            tmp_path = f"{state_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, state_path)

            marker_tmp = f"{marker_path}.tmp"
            with open(marker_tmp, "w", encoding="utf-8") as f:
                f.write(str(state.get("saved_at") or int(time.time())))
                f.flush()
                os.fsync(f.fileno())
            os.replace(marker_tmp, marker_path)
            return True
        except Exception as e:
            logger.warning(f"⚠️ GMGN 页面状态保存失败: {e}")
            return False

    def _is_valid_gmgn_runtime_state(self, state: dict) -> bool:
        if not isinstance(state, dict):
            return False
        if not str(state.get("template_token") or "").strip():
            return False
        if not isinstance(state.get("local_storage") or {}, dict):
            return False
        if not isinstance(state.get("session_storage") or {}, dict):
            return False
        url = self._sanitize_gmgn_layout_url(state.get("url") or "")
        last_known_good = self._sanitize_gmgn_layout_url(state.get("last_known_good_layout_url") or "")
        title_text = str(state.get("title") or "")
        return bool(
            self._is_usable_gmgn_work_url(url, title_text)
            or self._is_usable_gmgn_work_url(last_known_good, title_text)
        )

    def _sync_gmgn_state_to_peer(self, target_role: str, state: dict) -> bool:
        success = False
        if self._fetcher_role == "interactive" and str(target_role or "").strip().lower() == "background" and self._is_valid_gmgn_runtime_state(state):
            target_paths = self._gmgn_state_paths_for_role("background")
            mirrored_state = {
                "url": self._sanitize_gmgn_layout_url(state.get("url") or ""),
                "title": str(state.get("title") or ""),
                "template_token": str(state.get("template_token") or "").strip() or self.gmgn_template_token,
                "last_known_good_layout_url": self._sanitize_gmgn_layout_url(
                    state.get("last_known_good_layout_url") or state.get("url") or ""
                ),
                "local_storage": dict(state.get("local_storage") or {}) if isinstance(state.get("local_storage") or {}, dict) else {},
                "session_storage": dict(state.get("session_storage") or {}) if isinstance(state.get("session_storage") or {}, dict) else {},
                "saved_at": int(state.get("saved_at") or int(time.time())),
            }
            if self._is_valid_gmgn_runtime_state(mirrored_state):
                success = self._write_gmgn_state_file_to_path(
                    mirrored_state,
                    target_paths["gmgn_state_path"],
                    target_paths["gmgn_marker_path"],
                )
            logger.info(
                "GMGNStateSync | from=%s | to=%s | success=%s | url=%s",
                self._fetcher_role,
                "background",
                success,
                mirrored_state.get("url") if 'mirrored_state' in locals() else "",
            )
        return success

    def _load_peer_gmgn_saved_state(self, role: str) -> Dict[str, Any]:
        peer_paths = self._gmgn_state_paths_for_role(role)
        raw_state = self._read_gmgn_state_file_from_path(peer_paths["gmgn_state_path"])
        if not self._is_valid_gmgn_runtime_state(raw_state):
            return {}

        resolved_url, layout_url_source, fallback_to_default_template = self._resolve_gmgn_layout_seed_url(raw_state)
        template_token = str(
            raw_state.get("template_token")
            or self._extract_token_from_gmgn_url(resolved_url)
            or self.gmgn_template_token
        ).strip()
        peer_state = {
            "url": resolved_url,
            "title": str(raw_state.get("title") or ""),
            "template_token": template_token or self.gmgn_template_token,
            "last_known_good_layout_url": self._sanitize_gmgn_layout_url(
                raw_state.get("last_known_good_layout_url") or resolved_url
            ),
            "local_storage": {str(k): "" if v is None else str(v) for k, v in (raw_state.get("local_storage") or {}).items()} if isinstance(raw_state.get("local_storage") or {}, dict) else {},
            "session_storage": {str(k): "" if v is None else str(v) for k, v in (raw_state.get("session_storage") or {}).items()} if isinstance(raw_state.get("session_storage") or {}, dict) else {},
            "saved_at": raw_state.get("saved_at"),
            "layout_url_source": layout_url_source,
            "fallback_to_default_template": fallback_to_default_template,
        }
        return peer_state if self._is_valid_gmgn_runtime_state(peer_state) else {}

    def _resolve_gmgn_layout_seed_url(self, state: Optional[Dict[str, Any]] = None) -> Tuple[str, str, bool]:
        raw_state = state if isinstance(state, dict) else {}
        raw_url = self._sanitize_gmgn_layout_url(raw_state.get("url") or "")
        raw_title = str(raw_state.get("title") or "").strip().lower()
        last_known_good_layout_url = self._sanitize_gmgn_layout_url(raw_state.get("last_known_good_layout_url") or "")
        env_layout_url = self._sanitize_gmgn_layout_url(
            os.getenv("GMGN_BOOTSTRAP_LAYOUT_URL")
            or os.getenv("GMGN_LAYOUT_BOOTSTRAP_URL")
            or os.getenv("GMGN_LAYOUT_URL")
            or ""
        )

        raw_url_usable = self._is_usable_gmgn_work_url(raw_url, raw_title)
        candidates = []
        if raw_url_usable:
            candidates.extend(
                [
                    (raw_url, "saved_state_url", False),
                    (last_known_good_layout_url, "last_known_good_layout_url", False),
                    (env_layout_url, "env_bootstrap_layout_url", False),
                ]
            )
        else:
            candidates.extend(
                [
                    (last_known_good_layout_url, "last_known_good_layout_url", False),
                    (env_layout_url, "env_bootstrap_layout_url", False),
                ]
            )
        candidates.append((self._default_gmgn_layout_url(), "default_template_url", True))

        chosen_url = self._default_gmgn_layout_url()
        chosen_source = "default_template_url"
        fallback_to_default = True
        for candidate, source, fallback_default in candidates:
            if candidate:
                chosen_url = candidate
                chosen_source = source
                fallback_to_default = fallback_default
                break

        logger.info(
            "GMGNSeedTrace | chosen=%s | source=%s | raw_url_usable=%s",
            chosen_url,
            chosen_source,
            raw_url_usable,
        )
        return chosen_url, chosen_source, fallback_to_default

    def _extract_token_from_gmgn_url(self, url: str) -> str:
        try:
            m = re.search(r"/sol/token/([^/?#]+)", str(url or ""), re.IGNORECASE)
            return (m.group(1) if m else "").strip()
        except Exception:
            return ""

    def _load_gmgn_saved_state(self) -> Dict[str, Any]:
        try:
            if not os.path.exists(self.gmgn_state_path):
                return {}

            with open(self.gmgn_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return {}

            url = str(data.get("url") or "").strip()
            if not url.startswith("http") or "gmgn.ai" not in url:
                return {}

            local_storage = data.get("local_storage") or {}
            session_storage = data.get("session_storage") or {}
            if not isinstance(local_storage, dict):
                local_storage = {}
            if not isinstance(session_storage, dict):
                session_storage = {}

            template_token = str(
                data.get("template_token")
                or self._extract_token_from_gmgn_url(url)
                or self.gmgn_template_token
            ).strip()

            return {
                "url": url,
                "title": str(data.get("title") or ""),
                "template_token": template_token or self.gmgn_template_token,
                "local_storage": {str(k): "" if v is None else str(v) for k, v in local_storage.items()},
                "session_storage": {str(k): "" if v is None else str(v) for k, v in session_storage.items()},
                "saved_at": data.get("saved_at"),
            }
        except Exception as e:
            logger.warning(f"⚠️ GMGN 页面状态读取失败: {e}")
            return {}

    def _capture_gmgn_runtime_state(self, tab) -> Dict[str, Any]:
        if not tab:
            return {}

        try:
            raw = tab.run_js("""
                const dump = (store) => {
                    const out = {};
                    try {
                        for (let i = 0; i < store.length; i++) {
                            const key = store.key(i);
                            out[key] = store.getItem(key);
                        }
                    } catch (e) {}
                    return out;
                };

                return {
                    url: location.href || '',
                    title: document.title || '',
                    local_storage: dump(window.localStorage),
                    session_storage: dump(window.sessionStorage),
                };
            """) or {}
        except Exception as e:
            logger.warning(f"⚠️ GMGN 页面状态抓取失败: {e}")
            return {}

        if not isinstance(raw, dict):
            return {}

        url = str(raw.get("url") or "").strip()
        if not url.startswith("http") or "gmgn.ai" not in url:
            return {}

        sanitized_url = self._sanitize_gmgn_layout_url(url)
        current_is_token_work_page = self._is_usable_gmgn_work_url(sanitized_url, str(raw.get("title") or ""))
        existing_state = self._read_gmgn_state_file()
        if current_is_token_work_page:
            last_known_good_layout_url = sanitized_url
            write_last_known_good = "current_url"
        else:
            last_known_good_layout_url = self._sanitize_gmgn_layout_url((existing_state or {}).get("last_known_good_layout_url") or "")
            if not last_known_good_layout_url:
                last_known_good_layout_url = sanitized_url
            write_last_known_good = "existing_or_current_fallback"

        logger.info(
            "GMGNStateCapture | url=%s | write_last_known_good=%s",
            sanitized_url,
            write_last_known_good,
        )

        return {
            "url": sanitized_url,
            "title": str(raw.get("title") or ""),
            "template_token": self._extract_token_from_gmgn_url(sanitized_url) or self.gmgn_template_token,
            "last_known_good_layout_url": last_known_good_layout_url,
            "local_storage": raw.get("local_storage") if isinstance(raw.get("local_storage"), dict) else {},
            "session_storage": raw.get("session_storage") if isinstance(raw.get("session_storage"), dict) else {},
            "saved_at": int(time.time()),
        }

    def _clear_gmgn_runtime_storage(self, tab):
        if not tab:
            return
        try:
            tab.run_js(
                """
                try { window.localStorage.clear(); } catch (e) {}
                try { window.sessionStorage.clear(); } catch (e) {}
                return true;
                """
            )
        except Exception:
            pass

    def _gmgn_popup_block_reason(self, tab) -> str:
        if not tab:
            return ""
        try:
            reason = tab.run_js(
                """
                const isVisible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    return rect.width > 80 && rect.height > 40;
                };
                const selectors = [
                    '.ant-modal-mask',
                    '.ant-modal-wrap',
                    '.ant-modal',
                    '.ant-drawer-mask',
                    '.ant-tour',
                    '.ant-tour-mask',
                    '.driver-overlay',
                    '.driver-popover',
                    '.react-joyride__overlay',
                    '.react-joyride__tooltip',
                    '.tour-mask',
                    '.tour-overlay',
                    '.overlay-mask',
                    '.mask',
                    '.cover-mask',
                    '.shepherd-element',
                    '.shepherd-modal-overlay-container',
                    '[role="dialog"]',
                    '[data-tour-mask]',
                    '[data-overlay]',
                    '[class*="overlay"]',
                    '[class*="mask"]'
                ];
                const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
                let overlayVisible = false;
                for (const node of nodes) {
                    if (!isVisible(node)) continue;
                    overlayVisible = true;
                    const rect = node.getBoundingClientRect();
                    const txt = (node.innerText || node.textContent || '').trim().toLowerCase();
                    if (
                        txt.includes('welcome') ||
                        txt.includes('tutorial') ||
                        txt.includes('guide') ||
                        txt.includes('next') ||
                        txt.includes('continue') ||
                        txt.includes('got it') ||
                        txt.includes('skip') ||
                        txt.includes('风险提示') ||
                        txt.includes('下一步') ||
                        txt.includes('继续') ||
                        txt.includes('完成')
                    ) {
                        return 'popup_blocked';
                    }
                    if (rect.width >= window.innerWidth * 0.45 && rect.height >= window.innerHeight * 0.30) {
                        return 'overlay_mask';
                    }
                }
                const centerX = Math.max(0, Math.floor(window.innerWidth / 2));
                const centerY = Math.max(0, Math.floor(window.innerHeight / 2));
                const centerEl = document.elementFromPoint(centerX, centerY);
                if (centerEl) {
                    let node = centerEl;
                    while (node && node !== document.body) {
                        const style = window.getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        const zIndex = parseInt(style.zIndex || '0', 10);
                        const txt = (node.innerText || node.textContent || '').trim().toLowerCase();
                        if (
                            isVisible(node) &&
                            (style.position === 'fixed' || style.position === 'sticky' || zIndex >= 999) &&
                            rect.width >= window.innerWidth * 0.32 &&
                            rect.height >= window.innerHeight * 0.22
                        ) {
                            if (
                                txt.includes('welcome') ||
                                txt.includes('tutorial') ||
                                txt.includes('guide') ||
                                txt.includes('下一步') ||
                                txt.includes('continue') ||
                                txt.includes('got it') ||
                                txt.includes('skip')
                            ) {
                                return 'popup_blocked';
                            }
                            return 'overlay_mask';
                        }
                        node = node.parentElement;
                    }
                }
                try {
                    const bodyStyle = window.getComputedStyle(document.body);
                    if (bodyStyle.pointerEvents === 'none') {
                        return 'overlay_mask';
                    }
                } catch (e) {}
                return overlayVisible ? 'overlay_mask' : '';
                """
            )
            return str(reason or "").strip()
        except Exception:
            return ""

    def _gmgn_error_page_reason(self, current_url: str, title_text: str, page_text: str) -> str:
        combined_low = "\n".join([str(current_url or ""), str(title_text or ""), str(page_text or "")]).lower()
        patterns = [
            ("error_page", ["something went wrong", "unexpected application error", "load failed", "加载失败", "加载错误"]),
            ("access_denied", ["access denied", "forbidden", "403", "权限不足"]),
            ("not_found", ["not found", "404", "page not found"]),
            ("rate_limited", ["too many requests", "rate limited", "请求过于频繁"]),
            ("captcha_blocked", ["captcha", "human verification", "验证你是人类"]),
        ]
        for reason, keywords in patterns:
            if any(keyword in combined_low for keyword in keywords):
                return reason
        return ""

    def _gmgn_header_block_ready(self, tab, title_text: str = "", page_text: str = "") -> bool:
        if not tab:
            return False

        header_text = ""
        try:
            header_text = str(
                tab.run_js(
                    """
                    const isVisible = (el) => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                    };
                    const limit = window.innerHeight * 0.58;
                    const nodes = Array.from(document.querySelectorAll('body *'));
                    const collected = [];
                    for (const node of nodes) {
                        if (!isVisible(node)) continue;
                        const rect = node.getBoundingClientRect();
                        if (rect.bottom <= 0 || rect.top >= limit) continue;
                        const txt = (node.innerText || node.textContent || '').trim();
                        if (!txt || txt.length < 2) continue;
                        collected.push(txt);
                        if (collected.length >= 80) break;
                    }
                    return collected.join('\\n').slice(0, 2400);
                    """
                ) or ""
            ).strip()
        except Exception:
            header_text = ""

        combined_low = "\n".join([str(title_text or ""), header_text, str(page_text or "")[:1200]]).lower()
        header_markers = [
            "market cap",
            "市值",
            "liquidity",
            "池子",
            "top 10",
            "top10",
            "holder",
            "holders",
            "持有者",
            "dex paid",
            "dex付费",
        ]
        header_hits = sum(1 for marker in header_markers if marker in combined_low)
        return header_hits >= 2

    def _gmgn_page_gate_state(self, tab, ca: str = "", target_ready: Optional[bool] = None) -> Dict[str, Any]:
        if not tab:
            return {
                "valid": False,
                "blocked_reason": "tab_missing",
                "target_ready": False,
                "layout_ready": False,
                "header_ready": False,
                "popup_reason": "",
                "overlay_visible": False,
                "error_reason": "",
                "shell_page": False,
            }

        try:
            current_url = str(getattr(tab, "url", "") or "")
        except Exception:
            current_url = ""
        try:
            title_text = str(tab.title or "")
        except Exception:
            title_text = ""

        page_text = ""
        try:
            page_text = self._extract_visible_text(tab)
        except Exception:
            page_text = ""

        popup_reason = self._gmgn_popup_block_reason(tab)
        error_reason = self._gmgn_error_page_reason(current_url, title_text, page_text)
        shell_page = self._is_gmgn_shell_page(title_text, page_text)
        header_ready = self._gmgn_header_block_ready(tab, title_text, page_text)
        layout_ready = self._gmgn_layout_ready(tab)
        overlay_visible = popup_reason in {"popup_blocked", "overlay_mask"}
        target_token = str(ca or "").strip().lower()
        target_token_hit = bool(
            target_token
            and (
                target_token in current_url.lower()
                or target_token in page_text.lower()
                or target_token in title_text.lower()
            )
        )
        if target_ready is None:
            target_ready = self._wait_gmgn_target_page(tab, ca, timeout=0.8, interval=0.10) if ca else False

        blocked_reason = ""
        if popup_reason:
            blocked_reason = popup_reason
        elif error_reason:
            blocked_reason = error_reason
        elif shell_page:
            blocked_reason = "shell_page"
        elif target_token and not target_token_hit and not bool(target_ready):
            blocked_reason = "target_not_ready"
        elif not bool(target_ready):
            blocked_reason = "target_not_ready"
        elif not header_ready:
            blocked_reason = "header_not_ready"
        elif not layout_ready:
            blocked_reason = "layout_not_ready"

        return {
            "valid": not bool(blocked_reason),
            "blocked_reason": blocked_reason,
            "target_ready": bool(target_ready),
            "layout_ready": bool(layout_ready),
            "header_ready": bool(header_ready),
            "popup_reason": popup_reason,
            "overlay_visible": overlay_visible,
            "error_reason": error_reason,
            "shell_page": bool(shell_page),
            "target_token_hit": target_token_hit,
            "current_url": current_url,
            "title_text": title_text,
            "page_text": page_text,
        }
    
    def _gmgn_page_gate_state_passive(self, tab, ca: str = "") -> Dict[str, Any]:
        return self._gmgn_page_gate_state(tab, ca)

    def _gmgn_layout_ready(self, tab) -> bool:
        if not tab:
            return False

        try:
            current_url = str(getattr(tab, "url", "") or "")
        except Exception:
            current_url = ""
        if "gmgn.ai" not in current_url.lower() or "/sol/token/" not in current_url.lower():
            return False

        try:
            title_text = str(tab.title or "")
        except Exception:
            title_text = ""

        page_text = ""
        try:
            body = tab.ele("tag:body", timeout=1)
            if body and body.text:
                page_text = body.text
        except Exception:
            page_text = ""

        if len(str(page_text or "").strip()) < 80:
            try:
                visible_text = self._extract_visible_text(tab)
            except Exception:
                visible_text = ""
            if len(str(visible_text or "").strip()) > len(str(page_text or "").strip()):
                page_text = visible_text

        if self._gmgn_popup_block_reason(tab):
            return False
        if self._gmgn_error_page_reason(current_url, title_text, page_text):
            return False
        if self._is_gmgn_shell_page(title_text, page_text):
            return False

        header_ready = self._gmgn_header_block_ready(tab, title_text, page_text)
        combined_low = "\n".join([current_url, title_text, page_text]).lower()
        core_markers = [
            "market cap",
            "市值",
            "liquidity",
            "池子",
            "top 10",
            "top10",
            "holder",
            "holders",
            "持有者",
            "dex paid",
            "dex付费",
        ]
        tf_markers = ["1m", "5m", "15m", "30m", "1h", "4h", "6h", "24h", "1d"]
        marker_hits = sum(1 for marker in core_markers if marker in combined_low)
        tf_hits = sum(1 for marker in tf_markers if marker in combined_low)
        return bool(header_ready and (marker_hits >= 3 or (marker_hits >= 2 and tf_hits >= 1)))

    def _persist_gmgn_runtime_state(self, tab, expected_ca: str = "") -> bool:
        expected_token = str(expected_ca or "").strip() or self._extract_token_from_gmgn_url(str(getattr(tab, "url", "") or "")) or self.gmgn_template_token
        popup_reason = self._gmgn_popup_block_reason(tab)
        if popup_reason:
            logger.info(
                "GMGNStatePersist | skipped=true | reason=%s | role=%s | target=%s",
                popup_reason,
                self._fetcher_role,
                expected_token[:8],
            )
            return False
        snapshot = self._gmgn_page_gate_state(tab, expected_token)
        if snapshot.get("error_reason"):
            logger.info(
                "GMGNStatePersist | skipped=true | reason=%s | role=%s | target=%s",
                snapshot.get("error_reason"),
                self._fetcher_role,
                expected_token[:8],
            )
            return False
        if not snapshot.get("layout_ready"):
            logger.info(
                "GMGNStatePersist | skipped=true | reason=layout_not_ready | role=%s | target=%s",
                self._fetcher_role,
                expected_token[:8],
            )
            return False
        if expected_token and not snapshot.get("target_ready"):
            logger.info(
                "GMGNStatePersist | skipped=true | reason=target_not_ready | role=%s | target=%s",
                self._fetcher_role,
                expected_token[:8],
            )
            return False

        state = self._capture_gmgn_runtime_state(tab)
        if not state:
            return False
        state["last_known_good_layout_url"] = self._sanitize_gmgn_layout_url(
            state.get("last_known_good_layout_url") or state.get("url") or ""
        )
        if not state.get("last_known_good_layout_url"):
            logger.info(
                "GMGNStatePersist | skipped=true | reason=missing_last_known_good | role=%s | target=%s",
                self._fetcher_role,
                expected_token[:8],
            )
            return False

        success = self._write_gmgn_state_file_to_path(state, self.gmgn_state_path, self.gmgn_marker_path)
        if not success:
            return False

        logger.info(
            "GMGNStatePersist | skipped=false | role=%s | target=%s | url=%s | last_known_good=%s",
            self._fetcher_role,
            expected_token[:8],
            state.get("url") or "",
            state.get("last_known_good_layout_url") or "",
        )
        if self._fetcher_role == "interactive" and self._is_valid_gmgn_runtime_state(state):
            self._sync_gmgn_state_to_peer("background", state)
        return True

    def _apply_gmgn_saved_state(self, tab, state: Optional[Dict[str, Any]] = None, include_session: bool = True) -> bool:
        if not tab:
            return False

        self._inject_gmgn_local_flags(tab)
        state = state or self._load_gmgn_saved_state()
        if not state:
            return False

        payload_js = json.dumps({
            "local": state.get("local_storage") or {},
            "session": state.get("session_storage") or {},
            "include_session": bool(include_session),
        }, ensure_ascii=False)

        try:
            tab.run_js(f"""
                const payload = {payload_js};
                const applyStore = (store, data) => {{
                    if (!data || typeof data !== 'object') return;
                    for (const [k, v] of Object.entries(data)) {{
                        try {{
                            store.setItem(String(k), v == null ? '' : String(v));
                        }} catch (e) {{}}
                    }}
                }};

                applyStore(window.localStorage, payload.local);
                if (payload.include_session) {{
                    applyStore(window.sessionStorage, payload.session);
                }}
                localStorage.setItem('has_seen_welcome', 'true');
                localStorage.setItem('driver_tutorial_token_sol', 'true');
                localStorage.setItem('risk_warning_accepted', 'true');
                return true;
            """)
            return True
        except Exception:
            return False

    def _build_gmgn_token_url(self, ca: str, state: Optional[Dict[str, Any]] = None) -> str:
        target_ca = (ca or "").strip() or self.gmgn_template_token
        state = state or self._load_gmgn_saved_state()

        seed_url = str((state or {}).get("url") or self._default_gmgn_layout_url()).strip()
        if not seed_url.startswith("http"):
            seed_url = self._default_gmgn_layout_url()

        parsed = urlparse(seed_url)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or "gmgn.ai"
        path = parsed.path or f"/sol/token/{target_ca}"

        if re.search(r"/sol/token/[^/?#]+", path, re.IGNORECASE):
            path = re.sub(r"/sol/token/[^/?#]+", f"/sol/token/{target_ca}", path, count=1, flags=re.IGNORECASE)
        else:
            path = f"/sol/token/{target_ca}"

        query_items = parse_qsl(parsed.query, keep_blank_values=True)
        rebuilt_query = []
        has_chain = False
        for key, value in query_items:
            low_key = key.lower()
            if low_key in {"token", "address", "ca", "mint", "contract_address"}:
                rebuilt_query.append((key, target_ca))
                continue
            if low_key == "chain":
                rebuilt_query.append((key, "sol"))
                has_chain = True
                continue
            rebuilt_query.append((key, value))
        if not has_chain:
            rebuilt_query.append(("chain", "sol"))

        fragment = parsed.fragment or ""
        old_token = str((state or {}).get("template_token") or self._extract_token_from_gmgn_url(seed_url) or "").strip()
        if old_token and fragment:
            fragment = fragment.replace(old_token, target_ca)

        return urlunparse((scheme, netloc, path, "", urlencode(rebuilt_query, doseq=True), fragment))

    def _bootstrap_gmgn_tab_layout(self, tab, state: Optional[Dict[str, Any]] = None, force_fresh: bool = False) -> bool:
        if not tab:
            return False

        state = state or self._load_gmgn_saved_state()
        target_token = str((state or {}).get("template_token") or self.gmgn_template_token).strip() or self.gmgn_template_token
        seed_url = self._build_gmgn_token_url(target_token, state=state)
        direct_seed_open_ok = False
        homepage_fallback_ok = False

        try:
            if force_fresh:
                self._clear_gmgn_runtime_storage(tab)
            tab.get(seed_url)
            tab.wait.ele("tag:body", timeout=10)
            direct_seed_open_ok = True
        except Exception:
            direct_seed_open_ok = False
        logger.info(
            "GMGNBootstrapTrace | step=direct_seed_open | ok=%s | role=%s | seed_url=%s",
            direct_seed_open_ok,
            self._fetcher_role,
            seed_url,
        )
        if direct_seed_open_ok:
            logger.info(
                "GMGNBootstrapTrace | step=homepage_fallback | ok=%s | role=%s | skipped=%s",
                False,
                self._fetcher_role,
                True,
            )

        if not direct_seed_open_ok:
            try:
                tab.get("https://gmgn.ai/")
                tab.wait.ele("tag:body", timeout=8)
                homepage_fallback_ok = True
            except Exception:
                homepage_fallback_ok = False
            logger.info(
                "GMGNBootstrapTrace | step=homepage_fallback | ok=%s | role=%s",
                homepage_fallback_ok,
                self._fetcher_role,
            )
            if not homepage_fallback_ok:
                logger.info(
                    "GMGNBootstrapTrace | final_url=%s | popup_reason=%s | success=%s",
                    "",
                    "homepage_fallback_failed",
                    False,
                )
                return False
            try:
                self._inject_gmgn_local_flags(tab)
                self._apply_gmgn_saved_state(tab, state)
            except Exception:
                pass
            try:
                self._finish_gmgn_walkthrough(tab, max_clicks=8 if force_fresh else 6, interval=0.22 if force_fresh else 0.18)
            except Exception:
                pass
            try:
                tab.get(seed_url)
                tab.wait.ele("tag:body", timeout=10)
                direct_seed_open_ok = True
            except Exception:
                direct_seed_open_ok = False

        if not direct_seed_open_ok:
            try:
                final_url = str(getattr(tab, "url", "") or "")
            except Exception:
                final_url = ""
            logger.info(
                "GMGNBootstrapTrace | final_url=%s | popup_reason=%s | success=%s",
                final_url,
                "seed_open_failed",
                False,
            )
            return False

        try:
            self._inject_gmgn_local_flags(tab)
            self._apply_gmgn_saved_state(tab, state)
        except Exception:
            pass

        try:
            self._finish_gmgn_walkthrough(tab, max_clicks=14 if force_fresh else 12, interval=0.26 if force_fresh else 0.30)
        except Exception:
            pass

        popup_reason = self._gmgn_popup_block_reason(tab)
        target_ready = False
        try:
            target_ready = self._wait_gmgn_target_page(tab, target_token, timeout=2.2 if force_fresh else 1.6, interval=0.12)
        except Exception:
            target_ready = False
        page_gate = self._gmgn_page_gate_state(tab, target_token, target_ready)
        try:
            final_url = str(getattr(tab, "url", "") or "")
        except Exception:
            final_url = ""
        try:
            title_text = str(tab.title or "")
        except Exception:
            title_text = ""
        success = bool(
            self._is_usable_gmgn_work_url(final_url, title_text)
            and not str(page_gate.get("popup_reason") or popup_reason or "")
            and bool(page_gate.get("layout_ready"))
            and (not target_token or bool(page_gate.get("target_ready")))
            and bool(page_gate.get("valid"))
        )
        logger.info(
            "GMGNBootstrapTrace | final_url=%s | target_ready=%s | layout_ready=%s | popup_reason=%s | blocked_reason=%s | success=%s",
            final_url,
            bool(page_gate.get("target_ready")),
            bool(page_gate.get("layout_ready")),
            str(page_gate.get("popup_reason") or popup_reason or ""),
            str(page_gate.get("blocked_reason") or ""),
            success,
        )
        if not success:
            return False
        return True

    def _wait_gmgn_target_page(self, tab, ca: str, timeout: float = 10.0, interval: float = 0.4, trace: Optional[Dict[str, Any]] = None) -> bool:
        if not tab or not ca:
            return False

        deadline = time.time() + max(1.0, timeout)
        ca_low = str(ca).lower()
        short_prefix = ca_low[:6]
        short_suffix = ca_low[-4:] if len(ca_low) >= 4 else ca_low
        core_markers = [
            "市值", "Market Cap", "MCap", "MC",
            "池子", "Liquidity", "LP",
            "Dex付费", "Dex Paid",
            "Top 10", "Top10", "持有者", "Holder", "Holders",
            "DEV", "狙击者", "老鼠仓", "捆绑交易", "钓鱼钱包",
            "Mint丢弃", "无黑名单", "烧池子",
        ]
        tf_markers = ["1m", "5m", "15m", "30m", "1h", "4h", "6h", "24h", "1D"]

        while time.time() < deadline:
            try:
                current_url = str(tab.url or "")
            except Exception:
                current_url = ""

            try:
                title_text = str(tab.title or "")
            except Exception:
                title_text = ""

            page_text = self._extract_visible_text(tab)
            combined = "\n".join([current_url, title_text, page_text])
            combined_low = combined.lower()
            core_hits = sum(1 for x in core_markers if x.lower() in combined_low)
            tf_hits = sum(1 for x in tf_markers if x.lower() in combined_low)

            id_hits = 0
            if ca_low in current_url.lower():
                id_hits += 3
            if ca_low in combined_low:
                id_hits += 3
            if short_prefix and short_prefix in combined_low:
                id_hits += 1
            if short_suffix and short_suffix in combined_low:
                id_hits += 1

            if (id_hits >= 3 and core_hits >= 2) or (core_hits >= 5 and tf_hits >= 2):
                return True

            try:
                self._finish_gmgn_walkthrough(tab, max_clicks=2, interval=0.15)
            except Exception:
                pass

            time.sleep(interval)

        return False

    async def _get_ca_lock(self, ca: str):
        async with self._ca_locks_lock:
            if ca not in self._ca_locks:
                self._ca_locks[ca] = asyncio.Lock()
            return self._ca_locks[ca]

    def _avatar_path(self, ca: str):
        return os.path.join(self.avatar_dir, f"{re.sub(r'[^a-zA-Z0-9]', '', ca)[:80]}.jpg")

    def _avatar_meta_path(self, ca: str):
        return os.path.join(self.avatar_dir, f"{re.sub(r'[^a-zA-Z0-9]', '', ca)[:80]}.json")

    def _screenshot_path(self, ca: str):
        return os.path.join(self.img_dir, f"{re.sub(r'[^a-zA-Z0-9]', '', ca)[:80]}_chart.png")

    def _existing_avatar_path(self, ca: str) -> Optional[str]:
        path = self._avatar_path(ca)
        try:
            if os.path.exists(path) and os.path.getsize(path) > 200:
                with Image.open(path) as im:
                    im.verify()
                return path
        except Exception:
            try:
                os.remove(path)
            except Exception:
                pass
        return None

    def _load_avatar_meta(self, ca: str) -> Dict[str, Any]:
        path = self._avatar_meta_path(ca)
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _save_avatar_meta(self, ca: str, source_url: str, source: str = ""):
        path = self._avatar_meta_path(ca)
        payload = {
            "source_url": self._normalize_image_url(source_url),
            "source": str(source or ""),
            "updated_at": int(time.time()),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception:
            pass

    def _log_avatar_trace(self, stage: str, ca: str, **fields: Any):
        parts = []
        for key, value in fields.items():
            if value in (None, ""):
                continue
            parts.append(f"{key}={value}")
        suffix = f" | {' | '.join(parts)}" if parts else ""
        logger.info("AvatarTrace | stage=%s | ca=%s%s", stage, (ca or "")[:8], suffix)

    def _normalize_avatar_source(self, source: str, url: str = "") -> str:
        src = str(source or "").strip().lower()
        if src in {"dexscreener", "birdeye", "pump", "gmgn/dom", "gmgn/meta", "stable_cache"}:
            return src

        low_url = self._normalize_image_url(url).lower()
        if "gmgn" in low_url:
            return "gmgn/meta"
        if "pump.fun" in low_url:
            return "pump"
        if "birdeye" in low_url:
            return "birdeye"
        if "dexscreener" in low_url or "dex-screen" in low_url:
            return "dexscreener"
        return src

    def _avatar_source_priority(self, source: str, *, has_existing: bool = False) -> int:
        src = self._normalize_avatar_source(source)
        if src == "stable_cache":
            return 100
        if src in {"dexscreener", "birdeye", "pump"}:
            return 90
        if src == "gmgn/dom":
            return 60
        if src == "gmgn/meta":
            return 20
        if has_existing and not src:
            return 100
        return 40 if src else 0

    def _avatar_source_is_strong(self, source: str) -> bool:
        return self._normalize_avatar_source(source) in {"dexscreener", "birdeye", "pump", "gmgn/dom", "stable_cache"}

    def _avatar_candidate_score(self, source: str) -> int:
        src = self._normalize_avatar_source(source)
        if src == "stable_cache":
            return 100
        if src == "dexscreener":
            return 95
        if src == "pump":
            return 92
        if src == "gmgn/dom":
            return 80
        if src == "birdeye":
            return 72
        if src == "gmgn/meta":
            return 20
        return 0

    def _should_probe_pump(self, ca: str, token_data: Optional[dict] = None) -> bool:
        if str(ca or "").lower().endswith("pump"):
            return True
        td = token_data if isinstance(token_data, dict) else {}
        dex_id = str(td.get("dex_id") or "").strip().lower()
        if dex_id in {"pump", "pumpfun", "pump.fun"}:
            return True
        source_text = str(td.get("source") or "").strip().lower()
        if "pump" in source_text:
            return True
        token_url = str(td.get("token_image_url") or "").strip().lower()
        if "pump.fun" in token_url:
            return True
        pair_address = str(td.get("pair_address") or "").strip().lower()
        if pair_address.endswith("pump"):
            return True
        pair_url = " ".join(
            str(td.get(k) or "").strip().lower()
            for k in ("pair_url", "url", "source_url", "website", "web_url")
        )
        if "pump.fun" in pair_url or "/pump" in pair_url:
            return True
        name = str(td.get("name") or "").strip().lower()
        symbol = str(td.get("symbol") or "").strip().lower()
        if "pump" in name or "pump" in symbol:
            return True
        token_age_min = _to_int(td.get("token_age_min"), 0)
        if 0 < token_age_min <= 240 and dex_id in {"", "raydium", "raydium-cpmm", "meteora", "meteora-dlmm", "unknown"}:
            return True
        if 0 < token_age_min <= 120 and not pair_address and dex_id in {"", "unknown"}:
            return True
        return False

    def _existing_chart_path(self, ca: str) -> Optional[str]:
        path = self._screenshot_path(ca)
        try:
            if os.path.exists(path) and os.path.getsize(path) > 500:
                return path
        except Exception:
            pass
        return None

    def _normalize_image_url(self, url: str) -> str:
        if not url:
            return ""
        u = str(url).strip()
        if u.startswith("ipfs://"):
            return "https://ipfs.io/ipfs/" + u.replace("ipfs://", "").lstrip("/")
        return u

    def _looks_like_html(self, data: bytes) -> bool:
        head = (data[:256] or b"").lstrip().lower()
        return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head

    def _verify_and_convert_to_jpeg(self, data: bytes) -> Optional[bytes]:
        try:
            im = Image.open(BytesIO(data))
            im.verify()
        except Exception:
            return None
        try:
            im = Image.open(BytesIO(data))
            im = im.convert("RGB")
            out = BytesIO()
            im.save(out, format="JPEG", quality=92, optimize=True)
            return out.getvalue()
        except Exception:
            return None

    async def _download_image_cached(self, ca: str, url: str, source: str = "", fast_mode: bool = False) -> Optional[str]:
        url = self._normalize_image_url(url)
        if not url.startswith("http"):
            return None

        path = self._avatar_path(ca)
        lock = await self._get_ca_lock(f"avatar:{ca}")

        async with lock:
            existing = self._existing_avatar_path(ca)
            meta = self._load_avatar_meta(ca)
            source_url = self._normalize_image_url(meta.get("source_url") or "")
            old_source = self._normalize_avatar_source(meta.get("source") or "", source_url)
            if existing and not old_source:
                old_source = "stable_cache"
            new_source = self._normalize_avatar_source(source, url)
            old_priority = self._avatar_source_priority(old_source, has_existing=bool(existing))
            new_priority = self._avatar_source_priority(new_source)
            if existing and source_url and source_url == url:
                self._log_avatar_trace("cache_hit", ca, path=existing, source_url=source_url, source=old_source or new_source)
                return existing
            if existing and new_source == "gmgn/meta" and self._avatar_source_is_strong(old_source or "stable_cache"):
                self._log_avatar_trace(
                    "reject",
                    ca,
                    old_source=old_source or "stable_cache",
                    new_source="gmgn/meta",
                    reason="weaker_than_existing",
                )
                return existing
            if existing and new_priority < old_priority:
                self._log_avatar_trace(
                    "reject",
                    ca,
                    old_source=old_source or "stable_cache",
                    new_source=new_source or "unknown",
                    reason="weaker_than_existing",
                )
                return existing
            if existing and url and source_url != url:
                self._log_avatar_trace(
                    "replace",
                    ca,
                    old=source_url or existing,
                    new=url,
                    old_source=old_source or "stable_cache",
                    new_source=new_source or "unknown",
                )

            urls_to_try = [url]
            if "ipfs" in url.lower():
                hash_part = url.split("/ipfs/")[-1] if "/ipfs/" in url else url.split("/")[-1]
                if fast_mode:
                    urls_to_try = [
                        url,
                        f"https://ipfs.io/ipfs/{hash_part}",
                    ]
                else:
                    urls_to_try = [
                        f"https://ipfs.io/ipfs/{hash_part}",
                        f"https://dweb.link/ipfs/{hash_part}",
                        f"https://gateway.pinata.cloud/ipfs/{hash_part}",
                        url,
                    ]

            session = await self._get_session()
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            }

            for try_url in urls_to_try:
                try:
                    async with session.get(try_url, headers=headers, ssl=False, timeout=3 if fast_mode else 6) as resp:
                        if resp.status != 200:
                            continue

                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if ctype and ("image/" not in ctype):
                            continue

                        data = await resp.read()
                        if not data or len(data) < 256:
                            continue
                        if self._looks_like_html(data):
                            continue

                        jpeg_bytes = self._verify_and_convert_to_jpeg(data)
                        if not jpeg_bytes or len(jpeg_bytes) < 300:
                            continue

                        tmp_path = f"{path}.tmp"
                        with open(tmp_path, "wb") as f:
                            f.write(jpeg_bytes)
                            f.flush()
                            os.fsync(f.fileno())
                        os.replace(tmp_path, path)
                        self._save_avatar_meta(ca, try_url, source=new_source)
                        if fast_mode:
                            self._log_avatar_trace(
                                "first_card_download",
                                ca,
                                source=new_source or "unknown",
                                fast_mode="true",
                                success="true",
                            )
                        return path
                except Exception:
                    continue

            if fast_mode:
                self._log_avatar_trace(
                    "first_card_download",
                    ca,
                    source=new_source or "unknown",
                    fast_mode="true",
                    success="false",
                )
            return None

    async def ensure_token_avatar(self, ca: str, token_image_url: str, source: str = "", fast_mode: bool = False) -> Optional[str]:
        token_image_url = self._normalize_image_url(token_image_url)
        existing = self._existing_avatar_path(ca)
        if existing and not token_image_url:
            meta = self._load_avatar_meta(ca)
            self._log_avatar_trace(
                "keep",
                ca,
                path=existing,
                old_source=self._normalize_avatar_source(meta.get("source") or "", meta.get("source_url") or "") or "stable_cache",
                reason="no_new_url",
            )
            if fast_mode:
                self._log_avatar_trace(
                    "first_card_download",
                    ca,
                    source="stable_cache",
                    fast_mode="true",
                    success="true",
                )
            return existing
        if not token_image_url:
            if fast_mode:
                self._log_avatar_trace(
                    "first_card_download",
                    ca,
                    source=self._normalize_avatar_source(source, token_image_url) or "unknown",
                    fast_mode="true",
                    success="false",
                )
            return None
        return await self._download_image_cached(ca, token_image_url, source=source, fast_mode=fast_mode)

    async def _fetch_dex_avatar_url(self, ca: str) -> Tuple[str, str]:
        try:
            session = await self._get_session()
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            async with session.get(
                f"{self.dex_api_url.format(ca)}?avatar_only=1&t={int(time.time())}",
                headers=headers,
                timeout=2.4,
            ) as resp:
                if resp.status != 200:
                    return "", ""
                payload = await resp.json()
                pairs = payload.get("pairs", []) if isinstance(payload, dict) else []
                if not pairs:
                    self._log_avatar_trace("dex_probe", ca, success="false", url_present="false")
                    return "", ""
                valid = [p for p in pairs if _to_float((p.get("liquidity") or {}).get("usd")) > 100.0]
                if not valid:
                    valid = pairs
                ranked_pairs = sorted(
                    valid,
                    key=lambda p: _to_float((p.get("liquidity") or {}).get("usd")),
                    reverse=True,
                )[:4]

                def _pick_candidate(pair: dict) -> str:
                    info = pair.get("info", {}) or {}
                    base = pair.get("baseToken", {}) or {}
                    candidates = [
                        info.get("imageUrl"),
                        info.get("openGraph"),
                        info.get("image"),
                        base.get("logoURI"),
                        base.get("imageUrl"),
                        base.get("imageURI"),
                        base.get("icon"),
                        base.get("iconUrl"),
                        pair.get("imageUrl"),
                        pair.get("logoURI"),
                    ]
                    for candidate in candidates:
                        url = self._normalize_image_url(candidate or "")
                        if url.startswith("http"):
                            return url
                    return ""

                url = ""
                for pair in ranked_pairs:
                    url = _pick_candidate(pair)
                    if url:
                        break

                if not url and isinstance(payload, dict):
                    for container in (payload.get("token"), payload.get("baseToken"), payload.get("data")):
                        if not isinstance(container, dict):
                            continue
                        for field in ("logoURI", "imageUrl", "imageURI", "icon", "iconUrl"):
                            url = self._normalize_image_url(container.get(field) or "")
                            if url.startswith("http"):
                                break
                        if url:
                            break

                self._log_avatar_trace("dex_probe", ca, success=str(bool(url)).lower(), url_present=str(bool(url)).lower())
                return (url, "dexscreener") if url else ("", "")
        except Exception:
            self._log_avatar_trace("dex_probe", ca, success="false", url_present="false")
            return "", ""

    async def _fetch_pump_avatar_url(self, ca: str, token_data: Optional[dict] = None) -> Tuple[str, str]:
        if not self._should_probe_pump(ca, token_data):
            return "", ""
        try:
            session = await self._get_session()
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            async with session.get(
                f"https://frontend-api.pump.fun/coins/{ca}",
                headers=headers,
                timeout=2.4,
            ) as resp:
                if resp.status != 200:
                    self._log_avatar_trace("pump_probe", ca, success="false", url_present="false")
                    return "", ""
                payload = await resp.json()
                url = self._normalize_image_url((payload or {}).get("image_uri"))
                self._log_avatar_trace("pump_probe", ca, success=str(bool(url)).lower(), url_present=str(bool(url)).lower())
                return (url, "pump") if url else ("", "")
        except Exception:
            self._log_avatar_trace("pump_probe", ca, success="false", url_present="false")
            return "", ""

    async def _fetch_birdeye_avatar_url(self, ca: str) -> Tuple[str, str]:
        if not self.birdeye_api_key:
            return "", ""
        cached_overview = self._get_cached_birdeye_overview(ca)
        cached_logo = self._normalize_image_url((cached_overview or {}).get("logoURI") or "")
        if cached_logo:
            self._log_avatar_trace("birdeye_probe", ca, success="true", url_present="true", cache_hit="true")
            return cached_logo, "birdeye"
        if self._birdeye_avatar_cooldown_active(ca):
            self._log_avatar_trace("birdeye_probe", ca, success="false", url_present="false", cooldown="true")
            return "", ""
        try:
            session = await self._get_session()
            headers = {
                "X-API-KEY": self.birdeye_api_key,
                "accept": "application/json",
                "x-chain": "solana",
            }
            async with session.get(
                f"https://public-api.birdeye.so/defi/token_overview?address={ca}",
                headers=headers,
                timeout=2.4,
            ) as resp:
                body_text = await resp.text()
                low_body = body_text.lower()
                if resp.status in {400, 429} or "compute units usage limit exceeded" in low_body:
                    self._set_birdeye_avatar_cooldown(ca, reason=f"status_{resp.status}" if resp.status in {400, 429} else "compute_units")
                    return "", ""
                if resp.status != 200:
                    self._log_avatar_trace("birdeye_probe", ca, success="false", url_present="false")
                    return "", ""
                try:
                    payload = json.loads(body_text or "{}")
                except Exception:
                    payload = {}
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                url = self._normalize_image_url((data or {}).get("logoURI"))
                if isinstance(data, dict) and data:
                    self._cache_birdeye_overview(ca, data)
                self._log_avatar_trace("birdeye_probe", ca, success=str(bool(url)).lower(), url_present=str(bool(url)).lower())
                return (url, "birdeye") if url else ("", "")
        except Exception:
            self._log_avatar_trace("birdeye_probe", ca, success="false", url_present="false")
            return "", ""

    async def _fetch_warm_gmgn_avatar_url(self, ca: str, token_data: Optional[dict] = None) -> Tuple[str, str]:
        td = token_data if isinstance(token_data, dict) else {}
        cached_url, cached_source = self._get_cached_gmgn_avatar(ca)
        if cached_url:
            self._log_avatar_trace("pick", ca, source=cached_source, url=cached_url, cache_hit="true")
            return cached_url, cached_source

        current_url = self._normalize_image_url(td.get("token_image_url") or "")
        current_source = self._normalize_avatar_source(td.get("token_image_source") or "", current_url)
        if current_url and current_source in {"gmgn/dom", "gmgn/meta"}:
            current_url, current_source = self._cache_gmgn_avatar(ca, current_url, current_source)
            self._log_avatar_trace("pick", ca, source=current_source, url=current_url)
            return current_url, current_source

        if not await self._ensure_browser():
            return "", ""

        lock_acquired = False
        try:
            try:
                await asyncio.wait_for(self._gmgn_lock.acquire(), timeout=0.90)
                lock_acquired = True
            except asyncio.TimeoutError:
                return "", ""

            def _read_avatar() -> Tuple[str, str]:
                tab = self._get_or_create_gmgn_tab()
                if not tab:
                    return "", ""

                try:
                    current_tab_url = str(getattr(tab, "url", "") or "")
                except Exception:
                    current_tab_url = ""

                current_ca = self._extract_token_from_gmgn_url(current_tab_url)
                if current_ca != ca:
                    return "", ""

                picked_url = self._pick_gmgn_avatar(tab)
                if not picked_url:
                    return "", ""

                picked_source = self._normalize_avatar_source(
                    (self._last_gmgn_avatar_pick or {}).get("source") or "",
                    picked_url,
                )
                return picked_url, picked_source or "gmgn/dom"

            url, source = await asyncio.to_thread(_read_avatar)
            url = self._normalize_image_url(url)
            source = self._normalize_avatar_source(source, url)
            if not url or source not in {"gmgn/dom", "gmgn/meta"}:
                return "", ""

            url, source = self._cache_gmgn_avatar(ca, url, source)
            self._log_avatar_trace("pick", ca, source=source, url=url)
            return url, source
        except Exception:
            return "", ""
        finally:
            if lock_acquired:
                try:
                    self._gmgn_lock.release()
                except Exception:
                    pass

    async def prime_avatar_sources(self, ca: str, token_data: dict, allow_warm_probe: bool = True) -> Tuple[str, str]:
        td = token_data or {}
        existing = self._existing_avatar_path(ca)
        if existing:
            logger.info(
                "GMGNAvatarTrace | ca=%s | source=%s | url_present=%s | cache_hit=%s",
                ca[:8],
                "stable_cache",
                False,
                True,
            )
            return "", "stable_cache"

        current_url = self._normalize_image_url(td.get("token_image_url") or "")
        current_source = self._normalize_avatar_source(td.get("token_image_source") or "", current_url)
        if current_url and current_source in {"dexscreener", "pump", "birdeye", "gmgn/dom"}:
            logger.info(
                "GMGNAvatarTrace | ca=%s | source=%s | url_present=%s | cache_hit=%s",
                ca[:8],
                current_source,
                True,
                False,
            )
            return current_url, current_source

        cached_url, cached_source = self._get_cached_gmgn_avatar(ca)
        if cached_url:
            self._log_avatar_trace("pick", ca, source=cached_source, url=cached_url, cache_hit="true")
            logger.info(
                "GMGNAvatarTrace | ca=%s | source=%s | url_present=%s | cache_hit=%s",
                ca[:8],
                cached_source,
                True,
                True,
            )
            return cached_url, cached_source

        best_fallback: Tuple[str, str] = ("", "")
        if current_url and current_source == "gmgn/meta":
            best_fallback = (current_url, current_source)

        stage1_tasks: Dict[asyncio.Task, str] = {
            asyncio.create_task(self._fetch_dex_avatar_url(ca)): "dexscreener",
        }
        if allow_warm_probe:
            stage1_tasks[asyncio.create_task(self._fetch_warm_gmgn_avatar_url(ca, td))] = "gmgn"
        pending = set(stage1_tasks.keys())
        all_tasks = set(stage1_tasks.keys())

        def _log_choice(url: str, source: str):
            logger.info(
                "GMGNAvatarTrace | ca=%s | source=%s | url_present=%s | cache_hit=%s",
                ca[:8],
                source,
                bool(url),
                False,
            )

        def _remember_fallback(url: str, source: str):
            nonlocal best_fallback
            if not url:
                return
            prev_source = best_fallback[1] if best_fallback else ""
            if self._avatar_candidate_score(source) > self._avatar_candidate_score(prev_source):
                best_fallback = (url, source)

        try:
            stage1_deadline = time.perf_counter() + 0.75
            while pending and time.perf_counter() < stage1_deadline:
                remaining = max(0.0, stage1_deadline - time.perf_counter())
                done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    break
                for task in done:
                    try:
                        url, source = task.result()
                    except Exception:
                        continue
                    url = self._normalize_image_url(url)
                    source = self._normalize_avatar_source(source, url)
                    if not url or source not in {"dexscreener", "pump", "birdeye", "gmgn/dom", "gmgn/meta"}:
                        continue
                    _remember_fallback(url, source)
                    if source in {"dexscreener", "gmgn/dom"}:
                        _log_choice(url, source)
                        return url, source

            pump_tasks: Dict[asyncio.Task, str] = {}
            if self._should_probe_pump(ca, td):
                pump_tasks[asyncio.create_task(self._fetch_pump_avatar_url(ca, td))] = "pump"
            if pump_tasks:
                pending |= set(pump_tasks.keys())
                all_tasks |= set(pump_tasks.keys())
                pump_deadline = time.perf_counter() + 1.25

                while pending and time.perf_counter() < pump_deadline:
                    remaining = max(0.0, pump_deadline - time.perf_counter())
                    done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
                    if not done:
                        break
                    for task in done:
                        try:
                            url, source = task.result()
                        except Exception:
                            continue
                        url = self._normalize_image_url(url)
                        source = self._normalize_avatar_source(source, url)
                        if not url or source not in {"dexscreener", "pump", "birdeye", "gmgn/dom", "gmgn/meta"}:
                            continue
                        _remember_fallback(url, source)
                        if source in {"dexscreener", "pump", "gmgn/dom"}:
                            _log_choice(url, source)
                            return url, source

            birdeye_tasks: Dict[asyncio.Task, str] = {
                asyncio.create_task(self._fetch_birdeye_avatar_url(ca)): "birdeye",
            }
            pending |= set(birdeye_tasks.keys())
            all_tasks |= set(birdeye_tasks.keys())
            birdeye_deadline = time.perf_counter() + 0.75

            while pending and time.perf_counter() < birdeye_deadline:
                remaining = max(0.0, birdeye_deadline - time.perf_counter())
                done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    break
                for task in done:
                    try:
                        url, source = task.result()
                    except Exception:
                        continue
                    url = self._normalize_image_url(url)
                    source = self._normalize_avatar_source(source, url)
                    if not url or source not in {"dexscreener", "pump", "birdeye", "gmgn/dom", "gmgn/meta"}:
                        continue
                    _remember_fallback(url, source)
                    if source in {"dexscreener", "pump", "gmgn/dom"}:
                        _log_choice(url, source)
                        return url, source

            if best_fallback[0]:
                _log_choice(best_fallback[0], best_fallback[1])
                return best_fallback
            return "", ""
        finally:
            for task in all_tasks:
                if not task.done():
                    task.cancel()

    def _clip_http_body(self, body: str, limit: int = 240) -> str:
        text = str(body or "").replace("\r", " ").replace("\n", " ").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    def _get_cached_birdeye_overview(self, mint: str) -> Optional[Dict[str, Any]]:
        mint = str(mint or "").strip()
        if not mint:
            return None
        cached = self._birdeye_overview_cache.get(mint)
        if not cached:
            return None
        ts, data = cached
        if time.time() - float(ts or 0.0) > self._birdeye_overview_cache_ttl:
            self._birdeye_overview_cache.pop(mint, None)
            return None
        return dict(data or {}) if isinstance(data, dict) else None

    def _cache_birdeye_overview(self, mint: str, data: Optional[Dict[str, Any]]) -> None:
        mint = str(mint or "").strip()
        if not mint or not isinstance(data, dict) or not data:
            return
        self._birdeye_overview_cache[mint] = (time.time(), dict(data))

    def _birdeye_avatar_cooldown_active(self, mint: str) -> bool:
        mint = str(mint or "").strip()
        if not mint:
            return False
        until = float(self._birdeye_avatar_cooldown.get(mint) or 0.0)
        if until <= 0:
            return False
        if time.time() >= until:
            self._birdeye_avatar_cooldown.pop(mint, None)
            return False
        return True

    def _set_birdeye_avatar_cooldown(self, mint: str, reason: str = "", ttl: Optional[float] = None) -> None:
        mint = str(mint or "").strip()
        if not mint:
            return
        cooldown_ttl = float(ttl or self._birdeye_avatar_cooldown_ttl or 90.0)
        self._birdeye_avatar_cooldown[mint] = time.time() + max(30.0, cooldown_ttl)
        self._log_avatar_trace(
            "birdeye_probe",
            mint,
            success="false",
            url_present="false",
            cooldown="true",
            reason=reason or "cooldown",
        )

    def _get_cached_gmgn_avatar(self, ca: str) -> Tuple[str, str]:
        mint = str(ca or "").strip()
        if not mint:
            return "", ""
        cached = self._gmgn_avatar_runtime_cache.get(mint)
        if not cached:
            return "", ""
        ts, url, source = cached
        if time.time() - float(ts or 0.0) > self._gmgn_avatar_runtime_cache_ttl:
            self._gmgn_avatar_runtime_cache.pop(mint, None)
            return "", ""
        norm_url = self._normalize_image_url(url)
        norm_source = self._normalize_avatar_source(source, norm_url)
        if not norm_url or norm_source not in {"gmgn/dom", "gmgn/meta"}:
            self._gmgn_avatar_runtime_cache.pop(mint, None)
            return "", ""
        return norm_url, norm_source

    def _cache_gmgn_avatar(self, ca: str, url: str, source: str = "") -> Tuple[str, str]:
        mint = str(ca or "").strip()
        norm_url = self._normalize_image_url(url)
        norm_source = self._normalize_avatar_source(source, norm_url)
        if not mint or not norm_url or norm_source not in {"gmgn/dom", "gmgn/meta"}:
            return "", ""
        prev_url, prev_source = self._get_cached_gmgn_avatar(mint)
        if prev_url and self._avatar_candidate_score(prev_source) >= self._avatar_candidate_score(norm_source):
            return prev_url, prev_source
        self._gmgn_avatar_runtime_cache[mint] = (time.time(), norm_url, norm_source)
        return norm_url, norm_source

    async def _fetch_birdeye_overview(self, mint: str) -> Optional[Dict]:
        if not self.birdeye_api_key:
            logger.warning("Birdeye overview unavailable: missing API key | mint=%s", (mint or "")[:8])
            return None
        cached = self._get_cached_birdeye_overview(mint)
        if cached:
            return cached
        try:
            session = await self._get_session()
            headers = {
                "X-API-KEY": self.birdeye_api_key,
                "accept": "application/json",
                "x-chain": "solana",
            }
            async with session.get(
                f"https://public-api.birdeye.so/defi/token_overview?address={mint}",
                headers=headers,
                timeout=5
            ) as resp:
                if resp.status == 200:
                    data = (await resp.json()).get("data", {})
                    if isinstance(data, dict) and data:
                        self._cache_birdeye_overview(mint, data)
                    return data
                raw_body = await resp.text()
                body = self._clip_http_body(raw_body)
                if resp.status in {400, 429} or "compute units usage limit exceeded" in str(raw_body or "").lower():
                    self._set_birdeye_avatar_cooldown(
                        mint,
                        reason=f"overview_status_{resp.status}" if resp.status in {400, 429} else "overview_compute_units",
                    )
                logger.warning(
                    "BirdeyeOverview failed | mint=%s | status=%s | body=%s",
                    (mint or "")[:8],
                    resp.status,
                    body,
                )
        except Exception as e:
            logger.warning("Birdeye overview exception | mint=%s | err=%s", (mint or "")[:8], e)
        return None

    async def _fetch_birdeye_exit_liquidity(self, mint: str) -> Optional[Dict]:
        if not self.birdeye_api_key:
            logger.warning("Birdeye exit liquidity unavailable: missing API key | mint=%s", (mint or "")[:8])
            return None
        try:
            session = await self._get_session()
            headers = {
                "X-API-KEY": self.birdeye_api_key,
                "accept": "application/json",
                "x-chain": "solana",
            }
            async with session.get(
                f"https://public-api.birdeye.so/defi/v3/token/exit-liquidity?address={mint}",
                headers=headers,
                timeout=5
            ) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    if isinstance(payload, dict):
                        data = payload.get("data")
                        if isinstance(data, dict):
                            return data
                        if isinstance(data, list):
                            return {"items": data}
                        return payload
                    return {}
                body = self._clip_http_body(await resp.text())
                logger.warning(
                    "BirdeyeExitLiquidity failed | mint=%s | status=%s | body=%s",
                    (mint or "")[:8],
                    resp.status,
                    body,
                )
        except Exception as e:
            logger.warning("Birdeye exit liquidity exception | mint=%s | err=%s", (mint or "")[:8], e)
        return None

    def _extract_birdeye_exit_liquidity_usd(self, payload: Any) -> float:
        nodes: List[Dict[str, Any]] = []
        if isinstance(payload, dict):
            nodes.append(payload)
            if isinstance(payload.get("result"), dict):
                nodes.append(payload["result"])
            if isinstance(payload.get("data"), dict):
                nodes.append(payload["data"])
            items = payload.get("items")
            if isinstance(items, list):
                nodes.extend(item for item in items if isinstance(item, dict))

        key_candidates = (
            "liquidity",
            "liquidityUsd",
            "liquidity_usd",
            "exitLiquidity",
            "exit_liquidity",
            "exitLiquidityUsd",
            "exit_liquidity_usd",
            "usd",
            "value",
            "amount",
        )
        nested_key_candidates = (
            "liquidity",
            "exitLiquidity",
            "exit_liquidity",
            "usd",
            "value",
            "amount",
        )

        for node in nodes:
            for key in key_candidates:
                value = _to_float(node.get(key), 0.0)
                if value > 0:
                    return value
            for container_key in ("liquidity", "exitLiquidity", "exit_liquidity", "data"):
                container = node.get(container_key)
                if not isinstance(container, dict):
                    continue
                for key in nested_key_candidates:
                    value = _to_float(container.get(key), 0.0)
                    if value > 0:
                        return value
        return 0.0

    async def _helius_rpc(self, method, params):
        if not self.helius_rpc_url:
            return None
        try:
            session = await self._get_session()
            async with session.post(
                self.helius_rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            ) as r:
                if r.status == 200:
                    return (await r.json()).get("result")
        except Exception:
            pass
        return None

    def _cache_get_market(self, ca: str) -> Optional[Dict[str, Any]]:
        try:
            ts, payload = self._market_cache.get(ca, (0.0, None))
            if payload and (time.time() - ts) <= self._market_cache_ttl:
                out = dict(payload)
                if isinstance(out.get("txns"), dict):
                    out["txns"] = dict(out["txns"])
                return out
        except Exception:
            pass
        return None

    def _cache_set_market(self, ca: str, payload: Dict[str, Any]):
        try:
            self._market_cache[ca] = (time.time(), dict(payload))
        except Exception:
            pass

    async def _fetch_dexscreener(self, ca: str) -> Optional[Dict[str, Any]]:
        try:
            session = await self._get_session()
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            async with session.get(
                f"{self.dex_api_url.format(ca)}?t={int(time.time())}",
                headers=headers,
                timeout=6
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(
                    "DexScreener request failed | ca=%s | status=%s",
                    (ca or "")[:8],
                    resp.status,
                )
        except Exception as e:
            logger.warning("DexScreener exception | ca=%s | err=%s", (ca or "")[:8], e)
        return None

    async def get_market_data(self, ca: str, force: bool = False) -> Optional[Dict[str, Any]]:
        ca = (ca or "").strip()
        if not ca:
            return None

        lock = await self._get_ca_lock(f"market:{ca}")
        async with lock:
            if not force:
                cached = self._cache_get_market(ca)
                if cached is not None:
                    return cached

            ds_data, be_overview, be_exit = await asyncio.gather(
                self._fetch_dexscreener(ca),
                self._fetch_birdeye_overview(ca),
                self._fetch_birdeye_exit_liquidity(ca),
            )

            result: Dict[str, Any] = {
                "pair_liquidity_usd": None,
                "exit_liquidity_usd": None,
                "birdeye_liquidity_usd": None,
                "liquidity_usd": None,
                "token_age_min": 0,
                "symbol": "UNK",
                "market_data_ready": False,
                "liquidity_data_ready": False,
                "liquidity_source_error": "",
            }
            pairs = ds_data.get("pairs", []) if ds_data else []
            source_errors: List[str] = []
            if ds_data is None:
                source_errors.append("DEXSCREENER_FETCH_FAILED")
            elif not pairs:
                source_errors.append("DEXSCREENER_NO_PAIRS")
            if be_overview is None:
                source_errors.append("BIRDEYE_OVERVIEW_FAILED")
            if be_exit is None:
                source_errors.append("BIRDEYE_EXIT_LIQUIDITY_FAILED")

            if pairs:
                valid = [p for p in pairs if _to_float((p.get("liquidity") or {}).get("usd")) > 100.0]
                if not valid:
                    valid = pairs

                best = max(valid, key=lambda p: _to_float((p.get("liquidity") or {}).get("usd")))
                info = best.get("info", {}) or {}
                is_dex_paid = bool(info.get("imageUrl") or info.get("socials") or info.get("websites"))
                pair_liquidity_usd = _to_float((best.get("liquidity") or {}).get("usd"), 0)

                result = {
                    "symbol": (best.get("baseToken") or {}).get("symbol", "UNK"),
                    "name": (best.get("baseToken") or {}).get("name", ""),
                    "price_usd": best.get("priceUsd", "0"),
                    "pair_liquidity_usd": pair_liquidity_usd,
                    "exit_liquidity_usd": None,
                    "liquidity_usd": pair_liquidity_usd if pair_liquidity_usd > 0 else None,
                    "mcap": _to_float(best.get("marketCap") or best.get("fdv"), 0),
                    "pair_address": best.get("pairAddress"),
                    "dex_id": (best.get("dexId") or "").lower(),
                    "token_image_url": info.get("imageUrl") or (best.get("baseToken") or {}).get("logoURI"),
                    "token_image_source": "dexscreener" if (info.get("imageUrl") or (best.get("baseToken") or {}).get("logoURI")) else "",
                    "chg_5m": (best.get("priceChange") or {}).get("m5"),
                    "chg_1h": (best.get("priceChange") or {}).get("h1"),
                    "chg_6h": (best.get("priceChange") or {}).get("h6"),
                    "chg_24h": (best.get("priceChange") or {}).get("h24"),
                    "volume_h24": _to_float((best.get("volume") or {}).get("h24"), 0),
                    "txns": best.get("txns", {}) or {},
                    "dex_paid": is_dex_paid,
                    "market_data_ready": True,
                }

                h24 = result["txns"].get("h24", {}) if isinstance(result.get("txns"), dict) else {}
                result["buys_24h"] = _to_int(h24.get("buys", 0))
                result["sells_24h"] = _to_int(h24.get("sells", 0))
                result["buy_sell_ratio"] = result["buys_24h"] / result["sells_24h"] if result["sells_24h"] > 0 else 999.0

                created = best.get("pairCreatedAt")
                result["token_age_min"] = max(0, int((time.time() * 1000 - created) / 60000)) if created else 0
            if be_overview:
                result["market_data_ready"] = True
                result["chg_1m"] = be_overview.get("priceChange1mPercent")
                result["chg_15m"] = be_overview.get("priceChange15mPercent")
                result["chg_30m"] = be_overview.get("priceChange30mPercent")

                if _to_float(result.get("price_usd"), 0) <= 0 and _to_float(be_overview.get("price"), 0) > 0:
                    result["price_usd"] = be_overview.get("price")
                if _to_float(result.get("mcap"), 0) <= 0 and _to_float(be_overview.get("mc"), 0) > 0:
                    result["mcap"] = be_overview.get("mc")

                if not result.get("token_image_url") and be_overview.get("logoURI"):
                    result["token_image_url"] = be_overview.get("logoURI")
                    result["token_image_source"] = "birdeye"
                    self._log_avatar_trace("pick", ca, source="birdeye", url=result["token_image_url"])

            if be_exit is not None:
                be_exit_liq = self._extract_birdeye_exit_liquidity_usd(be_exit)
                if be_exit_liq > 0:
                    result["birdeye_liquidity_usd"] = be_exit_liq
                    result["exit_liquidity_usd"] = be_exit_liq

            if self._should_probe_pump(ca, result) and (not result.get("token_image_url") or result.get("mcap", 0) == 0):
                try:
                    session = await self._get_session()
                    headers = {"User-Agent": random.choice(USER_AGENTS)}
                    async with session.get(
                        f"https://frontend-api.pump.fun/coins/{ca}",
                        headers=headers,
                        timeout=3.0
                    ) as resp:
                        if resp.status == 200:
                            pump_data = await resp.json()

                            if not result.get("token_image_url"):
                                result["token_image_url"] = pump_data.get("image_uri")
                                result["token_image_source"] = "pump"
                                self._log_avatar_trace("pick", ca, source="pump", url=result["token_image_url"])
                            if result.get("symbol") == "UNK":
                                result["symbol"] = pump_data.get("symbol", "UNK")
                            if not result.get("name"):
                                result["name"] = pump_data.get("name", "")

                            if result.get("mcap", 0) == 0 and pump_data.get("usd_market_cap"):
                                result["mcap"] = float(pump_data.get("usd_market_cap"))
                                result["cap_usd"] = result["mcap"]

                            if result.get("token_age_min", 0) == 0 and pump_data.get("created_timestamp"):
                                created_ts = float(pump_data.get("created_timestamp")) / 1000
                                result["token_age_min"] = max(0, int((time.time() - created_ts) / 60))
                except Exception as e:
                    logger.debug(f"⚠️ Pump官方直连接口调用异常: {e}")

            existing_avatar = self._existing_avatar_path(ca)
            if existing_avatar:
                result["token_image_path"] = existing_avatar

            result["cap_usd"] = result.get("mcap") or result.get("fdv") or 0
            liquidity_value = (
                _to_float(result.get("exit_liquidity_usd"), None)
                or _to_float(result.get("pair_liquidity_usd"), None)
            )
            result["liquidity_usd"] = liquidity_value
            result["liquidity_data_ready"] = bool(_to_float(liquidity_value, 0) > 0)
            if not result["liquidity_data_ready"]:
                source_errors.append("LIQUIDITY_UNAVAILABLE")
            result["liquidity_source_error"] = ",".join(dict.fromkeys(source_errors))

            self._cache_set_market(ca, result)
            return dict(result)

    async def _get_goplus_token(self) -> Optional[str]:
        if not self.goplus_app_key or not self.goplus_app_secret:
            logger.warning("⚠️ GoPlus 未配置 APP_KEY / APP_SECRET")
            return None

        now = time.time()
        if self._goplus_token and now < self._goplus_token_expire:
            return self._goplus_token

        t = str(int(now))
        sign_str = self.goplus_app_key + t + self.goplus_app_secret
        sign = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()

        try:
            session = await self._get_session()
            payload = {"app_key": self.goplus_app_key, "sign": sign, "time": t}
            async with session.post(
                "https://api.gopluslabs.io/api/v1/token",
                json=payload,
                timeout=5
            ) as r:
                text = await r.text()
                if r.status != 200:
                    logger.error(f"⚠️ GoPlus Token 获取失败: HTTP {r.status} | body={text[:300]}")
                    return None

                try:
                    data = json.loads(text)
                except Exception:
                    logger.error(f"⚠️ GoPlus Token 获取失败: 非JSON响应 | body={text[:300]}")
                    return None

                if data.get("code") != 1:
                    logger.error(f"⚠️ GoPlus Token 获取失败: code={data.get('code')} | body={text[:300]}")
                    return None

                token_info = data.get("result") or data.get("data") or {}
                self._goplus_token = token_info.get("access_token", "")
                if not self._goplus_token:
                    logger.error(f"⚠️ GoPlus Token 获取失败: access_token 为空 | body={text[:300]}")
                    return None

                self._goplus_token_expire = now + float(token_info.get("expires_in", 7200)) - 60
                logger.info("🔐 GoPlus 鉴权成功")
                return self._goplus_token
        except Exception as e:
            logger.error(f"⚠️ GoPlus Token 获取异常: {e}")
            return None

    async def fetch_goplus_security(self, ca: str) -> Dict[str, Any]:
        if not ca:
            return {}

        token = await self._get_goplus_token()
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        if token:
            if token.startswith("Bearer"):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"

        try:
            session = await self._get_session()
            async with session.get(
                f"https://api.gopluslabs.io/api/v1/token_security/solana?contract_addresses={ca}",
                headers=headers,
                timeout=5
            ) as r:
                text = await r.text()
                if r.status != 200:
                    logger.error(f"⚠️ GoPlus Security 请求失败: HTTP {r.status} | body={text[:300]}")
                    return {}

                try:
                    d = json.loads(text)
                except Exception:
                    logger.error(f"⚠️ GoPlus Security 请求失败: 非JSON响应 | body={text[:300]}")
                    return {}

                res = (d.get("result", {}) or {}).get(ca.lower(), {})
                return {
                    "is_honeypot": res.get("is_honeypot") == "1",
                    "is_blacklisted": res.get("is_blacklisted") == "1",
                    "is_mintable": res.get("is_mintable") == "1",
                    "transfer_pausable": res.get("transfer_pausable") == "1",
                }
        except Exception as e:
            logger.error(f"⚠️ GoPlus Security 请求异常: {e}")
        return {}

    async def fetch_rugcheck_data(self, mint: str) -> Dict[str, Any]:
        if not mint:
            return {}

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json",
        }

        try:
            session = await self._get_session()
            async with session.get(
                f"https://api.rugcheck.xyz/v1/tokens/{mint}/report",
                headers=headers,
                timeout=5
            ) as r:
                if r.status == 200:
                    d = await r.json()
                    m = (d.get("markets") or [{}])[0]
                    return {
                        "lp_locked_pct": m.get("lpLockedPct", 0),
                        "lp_burned_pct": m.get("lpBurnedPct", 0),
                        "rugcheck_score": d.get("score", 0),
                    }
        except Exception:
            pass
        return {}

    async def get_helius_security(self, mint: str) -> Dict[str, Any]:
        mint = (mint or "").strip()
        if not mint:
            return {}

        mint_authority_present = None
        freeze_authority_present = None

        acc = await self._helius_rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        try:
            info = acc.get("value", {}).get("data", {}).get("parsed", {}).get("info", {})
            mint_authority_present = bool(info.get("mintAuthority"))
            freeze_authority_present = bool(info.get("freezeAuthority"))
        except Exception:
            pass

        return {
            "mint_authority_present": mint_authority_present,
            "freeze_authority_present": freeze_authority_present,
            "top10_ratio": None,
            "is_mint_renounced": (not mint_authority_present) if mint_authority_present is not None else None,
        }

    def _pick_gmgn_avatar(self, tab) -> str:
        self._last_gmgn_avatar_pick = {"source": "", "url": ""}

        def _remember(source: str, url: str) -> str:
            url = _norm_img_url(url)
            self._last_gmgn_avatar_pick = {"source": source, "url": url}
            return url

        def _norm_img_url(u: str) -> str:
            u = (u or "").strip()
            if not u:
                return ""
            if u.startswith("//"):
                return "https:" + u
            return u

        def _usable(u: str) -> bool:
            u = _norm_img_url(u)
            if not u:
                return False
            if u.startswith("data:image/"):
                return True
            if not (u.startswith("http://") or u.startswith("https://")):
                return False
            low = u.lower()
            if "gmgn.ai/static" in low or "favicon" in low:
                return False
            return True

        def _usable_meta(u: str) -> bool:
            u = _norm_img_url(u)
            if not _usable(u):
                return False
            low = u.lower()
            bad_keywords = [
                "banner", "hero", "cover", "poster", "campaign", "marketing",
                "speaker", "founder", "team", "profile", "event", "promo",
            ]
            if any(k in low for k in bad_keywords):
                return False
            good_keywords = ["logo", "avatar", "icon", "token", "coin"]
            return any(k in low for k in good_keywords) or "/ipfs/" in low or "image" in low

        def _looks_token_related(img) -> bool:
            try:
                hints = " ".join(
                    [
                        str(img.attr("class") or ""),
                        str(img.attr("alt") or ""),
                        str(img.attr("title") or ""),
                    ]
                ).lower()
                if any(k in hints for k in ["token", "logo", "avatar", "coin", "icon"]):
                    return True
                parent_hints = str(
                    img.run_js(
                        """
                        const el = this;
                        const p = el.closest('header, [class*="token"], [class*="coin"], [class*="header"], [class*="card"]');
                        return p ? [p.className || '', p.getAttribute('data-testid') || ''].join(' ') : '';
                        """
                    ) or ""
                ).lower()
                return any(k in parent_hints for k in ["token", "coin", "header", "card"])
            except Exception:
                return False

        candidate_selectors = [
            ('css:header img[class*="logo"]', "gmgn/dom"),
            ('css:[class*="token"] img[class*="logo"]', "gmgn/dom"),
            ('css:[class*="token"] img[class*="avatar"]', "gmgn/dom"),
            ('css:[class*="coin"] img[class*="logo"]', "gmgn/dom"),
            ('css:[class*="header"] img[alt*="logo"]', "gmgn/dom"),
            ('css:[class*="card"] img[alt*="token"]', "gmgn/dom"),
            ('css:img[class*="token"]', "gmgn/dom"),
            ('css:img[class*="logo"]', "gmgn/dom"),
            ('css:img[class*="avatar"]', "gmgn/dom"),
        ]

        for selector, source in candidate_selectors:
            try:
                els = tab.eles(selector)
                for img in els or []:
                    if not _looks_token_related(img):
                        continue
                    for attr in ("src", "data-src", "srcset"):
                        src = _norm_img_url(img.attr(attr) or "")
                        if attr == "srcset" and src:
                            src = _norm_img_url(src.split(",")[0].strip().split(" ")[0])
                        if _usable(src):
                            return _remember(source, src)
            except Exception:
                pass

        try:
            meta = tab.run_js("""
                const m = document.querySelector('meta[property="og:image"], meta[name="twitter:image"], meta[property="twitter:image"]');
                return m ? (m.content || '') : '';
            """)
            meta = _norm_img_url(str(meta or ""))
            if _usable_meta(meta):
                return _remember("gmgn/meta", meta)
        except Exception:
            pass

        return ""

    def _gmgn_result_is_thin(self, result: dict) -> bool:
        if not isinstance(result, dict):
            return True

        raw = result.get("raw_data") if isinstance(result.get("raw_data"), dict) else {}
        tag_non_null_count = _to_int(result.get("gmgn_tag_non_null_count"), 0)
        if tag_non_null_count <= 0 and raw:
            tag_non_null_count = sum(1 for v in raw.values() if v is not None)

        has_tag_block_hint = bool(result.get("gmgn_has_tag_block_hint"))
        has_1m = bool(result.get("chg_1m") or result.get("price_change_1m"))
        has_top10 = bool(result.get("top10_ratio"))
        has_header_liq = _to_float(result.get("header_liq_usd"), 0.0) > 0
        safety_hits = sum(
            1
            for key in ("dex_paid", "is_burned", "is_locked", "mint_authority_present", "freeze_authority_present")
            if result.get(key) is not None
        )
        avatar_ready = bool(result.get("token_image_url"))

        if has_tag_block_hint and tag_non_null_count == 0 and not any([has_1m, has_top10, has_header_liq, safety_hits, avatar_ready]):
            return True
        if tag_non_null_count <= 2 and has_tag_block_hint and safety_hits == 0 and not any([has_1m, has_top10, has_header_liq]):
            return True
        if not has_1m and not has_top10 and not has_header_liq and tag_non_null_count < 4 and safety_hits < 2:
            return True
        return False

    def _gmgn_invalid_result(self, result: Optional[Dict[str, Any]], reason: str, snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        out = dict(result or {})
        snap = snapshot if isinstance(snapshot, dict) else {}
        out["top10_ratio"] = None
        out["header_liq_usd"] = 0
        out["raw_data"] = {}
        out["gmgn_result_strength"] = "invalid"
        out["gmgn_fast_needs_followup"] = True
        out["gmgn_followup_required"] = True
        out["gmgn_followup_priority"] = "high"
        out["gmgn_fast_weak_reason"] = str(reason or "page_invalid")
        out["gmgn_fast_page_ready"] = bool(snap.get("target_ready"))
        out["gmgn_fast_header_ready"] = bool(snap.get("header_ready"))
        out["gmgn_fast_tag_ready"] = False
        out["gmgn_fast_safety_ready"] = False
        out["gmgn_fast_avatar_ready"] = False
        out["gmgn_tag_non_null_count"] = 0
        out["gmgn_has_tag_block_hint"] = False
        out["gmgn_tags_present"] = False
        out["gmgn_page_blocked_reason"] = str(snap.get("blocked_reason") or reason or "")
        out["gmgn_popup_reason"] = str(snap.get("popup_reason") or "")
        out["gmgn_overlay_visible"] = bool(snap.get("overlay_visible"))
        out["gmgn_error_reason"] = str(snap.get("error_reason") or "")
        return out

    def _gmgn_queue_timeout_result(self, weak_reason: str = "queue_timeout") -> Dict[str, Any]:
        return {
            "top10_ratio": None,
            "screenshot": "",
            "header_liq_usd": 0,
            "raw_data": {},
            "gmgn_result_strength": "weak",
            "gmgn_fast_needs_followup": True,
            "gmgn_followup_required": True,
            "gmgn_followup_priority": "high",
            "gmgn_fast_weak_reason": str(weak_reason or "queue_timeout"),
            "gmgn_fast_page_ready": False,
            "gmgn_fast_header_ready": False,
            "gmgn_fast_tag_ready": False,
            "gmgn_fast_safety_ready": False,
            "gmgn_fast_avatar_ready": False,
            "gmgn_tag_non_null_count": 0,
            "gmgn_has_tag_block_hint": False,
            "gmgn_tags_present": False,
        }

    def _extract_visible_text(self, tab) -> str:
        texts = []

        try:
            body = tab.ele("tag:body")
            if body and body.text:
                texts.append(body.text)
        except Exception:
            pass

        js_snippets = [
            "return document.body ? document.body.innerText : ''",
            "return document.documentElement ? document.documentElement.innerText : ''",
            """
            return Array.from(document.querySelectorAll('main, section, div, aside, span, p, a'))
                .map(el => (el.innerText || '').trim())
                .filter(Boolean)
                .filter(t => t.length >= 2)
                .slice(0, 600)
                .join('\n');
            """,
        ]

        for js in js_snippets:
            try:
                val = tab.run_js(js)
                if val:
                    texts.append(str(val))
            except Exception:
                pass

        uniq = []
        seen = set()
        for t in texts:
            t = (t or "").strip()
            if not t:
                continue
            if t not in seen:
                uniq.append(t)
                seen.add(t)

        return "\n".join(uniq)

    def _normalize_pct_value(self, raw: str) -> Optional[str]:
        if raw is None:
            return None
        s = str(raw).strip()
        if not s:
            return None

        s = (
            s.replace("＋", "+")
             .replace("－", "-")
             .replace("−", "-")
             .replace("–", "-")
             .replace("—", "-")
             .replace("％", "%")
             .replace(" ", "")
        )

        m = re.search(r"([+-]?\d+(?:\.\d+)?)%?$", s)
        if not m:
            return None
        return f"{m.group(1)}%"

    def _extract_gmgn_money_value(self, text: str, labels: List[str], max_gap: int = 18) -> Optional[float]:
        if not text or not labels:
            return None

        txt = str(text).replace("\u00A0", " ")
        label_pat = "|".join(re.escape(x) for x in labels if x)
        patterns = [
            rf"(?:{label_pat})[^\n]{{0,{max_gap}}}?\$?([0-9][0-9\.,]*[KkMmBb]?)",
            rf"(?:{label_pat})\s*[:：]?\s*\$?([0-9][0-9\.,]*[KkMmBb]?)",
        ]

        for pat in patterns:
            m = re.search(pat, txt, re.IGNORECASE)
            if m:
                val = _to_float(m.group(1), 0.0)
                if val > 0:
                    return val
        return None

    def _extract_gmgn_money_raw(self, text: str, labels: List[str], max_gap: int = 18) -> str:
        if not text or not labels:
            return ""

        txt = str(text).replace("\u00A0", " ")
        label_pat = "|".join(re.escape(x) for x in labels if x)
        patterns = [
            rf"(?:{label_pat})[^\n]{{0,{max_gap}}}?\$?([0-9][0-9\.,]*[KkMmBb]?)",
            rf"(?:{label_pat})\s*[:：]?\s*\$?([0-9][0-9\.,]*[KkMmBb]?)",
        ]

        for pat in patterns:
            m = re.search(pat, txt, re.IGNORECASE)
            if m:
                return str(m.group(1) or "").strip()
        return ""

    def _assess_gmgn_header_liquidity(self, raw_value: str, parsed_value: Optional[float], market_cap: Optional[float]) -> tuple[bool, str]:
        parsed = _to_float(parsed_value, 0.0)
        mcap = _to_float(market_cap, 0.0)
        raw = str(raw_value or "").strip()

        if parsed <= 0:
            return False, "missing"
        if parsed <= 10 and mcap > 1000:
            return False, "too_small_vs_mcap"
        if raw and parsed < 100 and not re.search(r"[$KkMmBb]", raw):
            return False, "bare_number_suspicious"
        return True, "accepted"

    def _extract_gmgn_lock_state(self, text: str) -> Optional[bool]:
        if not text:
            return None
        txt = str(text).replace("\u00A0", " ")
        positive_patterns = [
            r"(?:流动性锁定|Liquidity Locked|LP Locked|Pool Locked)[^\n]{0,24}?(?:100%|已锁定|锁定中|Locked\b|Yes\b|True\b)",
            r"(?:锁池|锁定)[^\n]{0,16}?(?:100%|已锁定|Locked\b)",
        ]
        negative_patterns = [
            r"(?:流动性锁定|Liquidity Locked|LP Locked|Pool Locked)[^\n]{0,24}?(?:0%|未锁定|Unlocked\b|Not Locked|No\b|False\b)",
            r"(?:锁池|锁定)[^\n]{0,16}?(?:0%|未锁定|Unlocked\b|Not Locked)",
        ]
        for pattern in positive_patterns:
            if re.search(pattern, txt, re.IGNORECASE):
                return True
        for pattern in negative_patterns:
            if re.search(pattern, txt, re.IGNORECASE):
                return False
        return None

    def _is_gmgn_shell_page(self, title_text: str, page_text: str) -> bool:
        title_low = str(title_text or "").lower()
        text_low = str(page_text or "").lower()

        generic_title = (
            "fast trade" in title_low and
            "fast copy trade" in title_low and
            "afk automation" in title_low
        )
        content_markers = [
            "top 10", "top10", "holders", "holder", "dev", "smart money", "dex paid",
            "liquidity", "market cap", "24h volume", "价格", "市值", "池子", "持有者",
            "狙击者", "老鼠仓", "捆绑交易", "钓鱼钱包", "dex付费", "烧池子"
        ]
        marker_hits = sum(1 for x in content_markers if x in text_low)
        return generic_title and marker_hits < 3

    def _extract_gmgn_pct(self, text: str, label: str) -> Optional[str]:
        if not text:
            return None

        txt = (
            str(text)
            .replace("\u00A0", " ")
            .replace("＋", "+")
            .replace("－", "-")
            .replace("−", "-")
            .replace("–", "-")
            .replace("—", "-")
            .replace("％", "%")
        )

        label_text = str(label or "")
        label_re = re.escape(label_text)
        if label_text.lower() == "1m":
            label_token = r"(?<![\d.])(?-i:1m)(?=$|[\s:：\|\+\-])"
        else:
            label_token = rf"(?<![A-Za-z0-9]){label_re}(?![A-Za-z0-9])"
        patterns = [
            rf"{label_token}\s*[\.\:：·•\|\-/–—]*\s*([+\-]?\d+(?:\.\d+)?)\s*%",
            rf"{label_token}[\s\r\n]*([+\-]?\d+(?:\.\d+)?)\s*%",
        ]

        for pat in patterns:
            m = re.search(pat, txt, re.IGNORECASE)
            if m:
                return self._normalize_pct_value(m.group(1))

        return None

    def _extract_gmgn_pct_trace(self, text: str, label: str) -> Dict[str, Any]:
        if not text:
            return {"raw_text": "", "parsed": None, "accepted": False, "source": ""}

        txt = (
            str(text)
            .replace("\u00A0", " ")
            .replace("＋", "+")
            .replace("－", "-")
            .replace("−", "-")
            .replace("–", "-")
            .replace("—", "-")
            .replace("％", "%")
        )

        label_text = str(label or "")
        label_re = re.escape(label_text)
        if label_text.lower() == "1m":
            label_token = r"(?<![\d.])(?-i:1m)(?=$|[\s:：\|\+\-])"
        else:
            label_token = rf"(?<![A-Za-z0-9]){label_re}(?![A-Za-z0-9])"
        line_patterns = [
            rf"({label_token}\s*[\.\:：·•\|\-/–—]*\s*[+\-]?\d+(?:\.\d+)?\s*%)",
            rf"({label_token}[\s\r\n]*[+\-]?\d+(?:\.\d+)?\s*%)",
        ]
        for line in txt.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            for pat in line_patterns:
                m = re.search(pat, stripped, re.IGNORECASE)
                if not m:
                    continue
                num_match = re.search(r"([+\-]?\d+(?:\.\d+)?)\s*%", m.group(1))
                if not num_match:
                    continue
                parsed = self._normalize_pct_value(num_match.group(1))
                return {
                    "raw_text": stripped,
                    "parsed": parsed,
                    "accepted": parsed is not None,
                    "source": label,
                }

        compact_txt = re.sub(r"\s+", " ", txt).strip()
        if compact_txt:
            for pat in line_patterns:
                m = re.search(pat, compact_txt, re.IGNORECASE)
                if not m:
                    continue
                raw_text = str(m.group(1) or "").strip()
                if not raw_text:
                    continue
                num_match = re.search(r"([+\-]?\d+(?:\.\d+)?)\s*%", raw_text)
                if not num_match:
                    continue
                parsed = self._normalize_pct_value(num_match.group(1))
                return {
                    "raw_text": raw_text,
                    "parsed": parsed,
                    "accepted": parsed is not None,
                    "source": label,
                }
        return {
            "raw_text": "",
            "parsed": None,
            "accepted": False,
            "source": label,
        }

    def _extract_gmgn_label_snippet(self, text: str, labels: List[str], follow_lines: int = 1) -> str:
        if not text or not labels:
            return ""

        txt = str(text).replace("\u00A0", " ")
        patterns = [re.compile(label, re.IGNORECASE) for label in labels if label]
        lines = [line.strip() for line in txt.splitlines() if str(line or "").strip()]

        for idx, line in enumerate(lines):
            if not any(p.search(line) for p in patterns):
                continue
            window = [line]
            for offset in range(1, max(1, follow_lines) + 1):
                if idx + offset < len(lines):
                    window.append(lines[idx + offset])
            return " ".join(window).strip()

        joined = "|".join(labels)
        try:
            m = re.search(rf"((?:{joined})[\s\S]{{0,64}})", txt, re.IGNORECASE)
            if m:
                return str(m.group(1) or "").strip()
        except Exception:
            pass
        return ""

    def _extract_gmgn_dex_paid_state(self, text: str) -> Optional[bool]:
        snippet = self._extract_gmgn_label_snippet(text, [r"Dex付费", r"Dex Paid", r"DexPaid"], follow_lines=1)
        if not snippet:
            return None

        if re.search(r"(?:已付费|Paid\b|Yes\b|True\b)", snippet, re.IGNORECASE):
            return True

        amt_match = re.search(r"(?:\$|SOL\s*)?([0-9][0-9\.,]*[KkMmBb]?)", snippet, re.IGNORECASE)
        if amt_match and _to_float(amt_match.group(1), 0.0) > 0:
            return True

        if re.search(
            r"(?:未付费|未支付|No\b|False\b|\b0(?:\.0+)?(?:\s*(?:SOL|\$))?\b)",
            snippet,
            re.IGNORECASE,
        ):
            return False

        return None

    def _extract_gmgn_burn_state(self, text: str) -> Optional[bool]:
        snippet = self._extract_gmgn_label_snippet(text, [r"烧池子", r"Liquidity Burned", r"LP Burned"], follow_lines=1)
        if not snippet:
            return None
        pct_match = re.search(r"([0-9]+(?:\.\d+)?)\s*%", snippet)
        if pct_match:
            pct_val = _to_float(pct_match.group(1), -1.0)
            if pct_val >= 95:
                return True
            if pct_val == 0:
                return False
        if re.search(r"(?:已烧|Yes\b|True\b|Burned\b)", snippet, re.IGNORECASE):
            return True
        if re.search(r"(?:未烧|No\b|False\b|Not Burned\b)", snippet, re.IGNORECASE):
            return False
        return None

    def _extract_gmgn_mint_state(self, text: str) -> Optional[bool]:
        snippet = self._extract_gmgn_label_snippet(text, [r"Mint丢弃", r"Mint Renounced", r"Mint", r"增发"], follow_lines=1)
        if not snippet:
            return None
        if re.search(r"(?:丢弃|Renounced|No Mint|不可增发|Disabled|False\b|No\b)", snippet, re.IGNORECASE):
            return False
        if re.search(r"(?:未丢弃|Mintable|Can Mint|可增发|Enabled|True\b|Yes\b)", snippet, re.IGNORECASE):
            return True
        return None

    def _extract_gmgn_freeze_state(self, text: str) -> Optional[bool]:
        snippet = self._extract_gmgn_label_snippet(text, [r"Freeze", r"冻结", r"黑名单", r"Blacklist"], follow_lines=1)
        if not snippet:
            return None
        if re.search(r"(?:无黑名单|不可冻结|Disabled|Renounced|False\b|No\b)", snippet, re.IGNORECASE):
            return False
        if re.search(r"(?:有黑名单|可冻结|Enabled|True\b|Yes\b|冻结权限)", snippet, re.IGNORECASE):
            return True
        return None

    def _extract_gmgn_timeframe_changes(self, text: str) -> Dict[str, Any]:
        mapping = [
            ("1m", "chg_1m", "price_change_m1"),
            ("5m", "chg_5m", "price_change_m5"),
            ("15m", "chg_15m", "price_change_m15"),
            ("30m", "chg_30m", "price_change_m30"),
            ("1h", "chg_1h", "price_change_h1"),
            ("3h", "chg_3h", "price_change_h3"),
            ("6h", "chg_6h", "price_change_h6"),
            ("24h", "chg_24h", "price_change_h24"),
        ]

        out: Dict[str, Any] = {}
        for label, key1, key2 in mapping:
            pct = self._extract_gmgn_pct(text, label)
            if pct is not None:
                out[key1] = pct
                out[key2] = pct
                out[f"price_change_{label}"] = pct
        return out

    def _extract_gmgn_top10_trace(self, text: str) -> Dict[str, Any]:
        if not text:
            return {
                "raw_text": "",
                "parsed_raw": None,
                "normalized": None,
                "correction_reason": "",
                "match_source": "",
                "reject_reason": "",
            }

        txt = (
            str(text)
            .replace("\u00A0", " ")
            .replace("＋", "+")
            .replace("－", "-")
            .replace("−", "-")
            .replace("–", "-")
            .replace("—", "-")
            .replace("％", "%")
        )

        def _build_trace(
            raw_text: str,
            raw_value: Optional[str],
            correction_reason: str = "",
            match_source: str = "",
            reject_reason: str = "",
        ) -> Dict[str, Any]:
            normalized = self._normalize_pct_value(raw_value) if raw_value is not None else None
            return {
                "raw_text": str(raw_text or "").strip(),
                "parsed_raw": raw_value,
                "normalized": normalized,
                "correction_reason": correction_reason,
                "match_source": match_source,
                "reject_reason": reject_reason,
            }

        label_patterns = (
            r"Top\s*10(?:\s*Holders?)?",
            r"Top10(?:\s*Holders?)?",
            r"前\s*10(?:持仓|地址|持有者)?",
            r"前十(?:持仓|地址|持有者)?",
        )
        reject_label_patterns = (
            r"捆绑交易",
            r"Bundle",
            r"老鼠仓",
            r"\bRat\b",
            r"钓鱼钱包",
            r"Phishing",
            r"狙击",
            r"Sniper",
            r"Bot\s*Degen",
        )

        def _contains_reject_label(segment: str) -> bool:
            return any(re.search(pattern, segment or "", re.IGNORECASE) for pattern in reject_label_patterns)

        last_reject_trace: Optional[Dict[str, Any]] = None

        for line in txt.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            label_match = None
            for pattern in label_patterns:
                label_match = re.search(pattern, stripped, re.IGNORECASE)
                if label_match:
                    break
            if not label_match:
                continue
            after_label = stripped[label_match.end():]
            after_matches = list(re.finditer(r"([+\-]?\d+(?:\.\d+)?)\s*%", after_label))
            if not after_matches:
                continue
            prefix_before_pct = after_label[: after_matches[0].start()]
            if _contains_reject_label(prefix_before_pct):
                last_reject_trace = _build_trace(stripped, None, "", "line_label", "non_top10_label_before_pct")
                continue
            chosen_raw = after_matches[0].group(1)
            reject_reason = "ignored_non_top10_pct_same_line" if len(after_matches) > 1 else ""
            return _build_trace(stripped, chosen_raw, "", "line_label", reject_reason)

        combined_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in label_patterns]
        for compiled in combined_patterns:
            for match in compiled.finditer(txt):
                start = max(0, match.start() - 12)
                end = min(len(txt), match.end() + 96)
                window = txt[start:end].replace("\n", " ").strip()
                after_window = txt[match.end(): min(len(txt), match.end() + 96)]
                pct_matches = list(re.finditer(r"([+\-]?\d+(?:\.\d+)?)\s*%", after_window))
                if not pct_matches:
                    continue
                prefix_before_pct = after_window[: pct_matches[0].start()]
                if _contains_reject_label(prefix_before_pct):
                    last_reject_trace = _build_trace(window[:180], None, "", "label_window", "non_top10_label_before_pct")
                    continue
                chosen_raw = pct_matches[0].group(1)
                reject_reason = "ignored_non_top10_pct_window" if len(pct_matches) > 1 else ""
                return _build_trace(window[:180], chosen_raw, "", "label_window", reject_reason)

        patterns = [
            r"((?:Top\s*10(?:\s*Holders?)?|Top10(?:\s*Holders?)?|前\s*10(?:持仓|地址|持有者)?|前十(?:持仓|地址|持有者)?)[^\n%]{0,40}?([+\-]?\d+(?:\.\d+)?)\s*%)",
        ]
        for pat in patterns:
            m = re.search(pat, txt, re.IGNORECASE)
            if m:
                raw_value = str(m.group(2) or "").strip()
                return _build_trace(str(m.group(1) or "").strip(), raw_value, "", "regex_context")

        return last_reject_trace or {
            "raw_text": "",
            "parsed_raw": None,
            "normalized": None,
            "correction_reason": "",
            "match_source": "",
            "reject_reason": "",
        }

    def _extract_gmgn_top10_context(self, tab) -> str:
        if not tab:
            return ""
        try:
            snippet = tab.run_js(
                """
                const isVisible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                };
                const nodes = Array.from(document.querySelectorAll('body *'));
                const labels = [/top\\s*10/i, /top10/i, /前\\s*10/, /前十/];
                for (const node of nodes) {
                    if (!isVisible(node)) continue;
                    const txt = (node.innerText || node.textContent || '').trim();
                    if (!txt) continue;
                    if (!labels.some((re) => re.test(txt))) continue;
                    const parent = node.parentElement ? (node.parentElement.innerText || node.parentElement.textContent || '') : '';
                    const grand = node.parentElement && node.parentElement.parentElement
                        ? (node.parentElement.parentElement.innerText || node.parentElement.parentElement.textContent || '')
                        : '';
                    const next = node.nextElementSibling ? (node.nextElementSibling.innerText || node.nextElementSibling.textContent || '') : '';
                    const block = [txt, parent, grand, next].filter(Boolean).join(' | ').trim();
                    if (block) return block.slice(0, 420);
                }
                return '';
                """
            )
            return str(snippet or "").strip()
        except Exception:
            return ""

    def _extract_gmgn_top10_ratio(self, text: str) -> Optional[str]:
        return self._extract_gmgn_top10_trace(text).get("normalized")

    def _try_save_chart_screenshot(self, tab, ca: str) -> Optional[str]:
        stable_path = self._screenshot_path(ca)
        ca_key = re.sub(r'[^a-zA-Z0-9]', '', ca)[:80]
        unique_path = os.path.join(self.img_dir, f"{ca_key}_{int(time.time() * 1000)}_chart.png")

        try:
            tmp = f"{unique_path}.tmp"
            tab.get_screenshot(path=tmp, full_page=False)

            if os.path.exists(tmp) and os.path.getsize(tmp) > 500:
                os.replace(tmp, unique_path)

                try:
                    stable_tmp = f"{stable_path}.tmp"
                    with open(unique_path, "rb") as src, open(stable_tmp, "wb") as dst:
                        dst.write(src.read())
                        dst.flush()
                        os.fsync(dst.fileno())
                    os.replace(stable_tmp, stable_path)
                except Exception:
                    pass

                return unique_path

            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

        return self._existing_chart_path(ca)

    def _extract_tag_count(self, text: str, keywords: List[str]) -> Optional[int]:
        if not text:
            return None

        variants = [re.escape(k) for k in keywords if k]
        if not variants:
            return None
        p = "|".join(variants)

        patterns = [
            rf"(?:{p})\s*[:：xX×]?\s*(\d{{1,4}})(?!\s*%)",
            rf"(\d{{1,4}})\s*(?:个|名|位)?\s*(?:{p})",
            rf"(?:{p})[\s\S]{{0,8}}?(\d{{1,4}})(?!\s*%)",
        ]

        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    pass
        return None

    def _extract_gmgn_tag_windows(self, tab, tag_map: Dict[str, List[str]]) -> Dict[str, str]:
        if not tab or not isinstance(tag_map, dict) or not tag_map:
            return {}

        try:
            payload = json.dumps(tag_map, ensure_ascii=False)
            raw = tab.run_js(
                f"""
                const spec = {payload};
                const isVisible = (el) => {{
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                }};
                const collect = (el) => {{
                    const parts = [];
                    const pull = (node) => {{
                        if (!node || !isVisible(node)) return;
                        const txt = (node.innerText || node.textContent || '').trim();
                        if (txt) parts.push(txt);
                    }};
                    pull(el);
                    pull(el.nextElementSibling);
                    pull(el.previousElementSibling);
                    pull(el.parentElement);
                    pull(el.parentElement ? el.parentElement.nextElementSibling : null);
                    pull(el.parentElement ? el.parentElement.parentElement : null);
                    return parts.join(' | ').slice(0, 420);
                }};
                const nodes = Array.from(document.querySelectorAll('body *'));
                const out = {{}};
                for (const [key, labels] of Object.entries(spec)) {{
                    let best = '';
                    for (const node of nodes) {{
                        if (!isVisible(node)) continue;
                        const txt = (node.innerText || node.textContent || '').trim();
                        if (!txt || txt.length > 120) continue;
                        const low = txt.toLowerCase();
                        if (!labels.some((label) => low.includes(String(label || '').toLowerCase()))) continue;
                        const block = collect(node);
                        if (block.length > best.length) best = block;
                    }}
                    out[key] = best;
                }}
                return out;
                """
            ) or {}
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _inject_gmgn_local_flags(self, tab):
        if not tab:
            return
        try:
            tab.run_js("""
                localStorage.setItem('has_seen_welcome', 'true');
                localStorage.setItem('driver_tutorial_token_sol', 'true');
                localStorage.setItem('risk_warning_accepted', 'true');
            """)
        except Exception:
            pass

    def _wait_gmgn_metrics_ready(self, tab, timeout: float = 4.0, interval: float = 0.35) -> bool:
        if not tab:
            return False

        deadline = time.time() + max(0.5, timeout)
        core_markers = [
            "市值", "market cap", "mcap", "mc",
            "池子", "liquidity", "lp",
            "24h成交额", "24h volume", "volume",
            "top 10", "top10", "持有者", "holder", "holders",
            "dev", "狙击者", "老鼠仓", "捆绑交易", "钓鱼钱包",
            "dex付费", "dex paid", "mint丢弃", "无黑名单", "烧池子",
        ]
        tf_markers = ["1m", "5m", "15m", "30m", "1h", "4h", "6h", "24h", "1d"]

        while time.time() < deadline:
            try:
                txt = self._extract_visible_text(tab)
                title = str(tab.title or "")
                combined = "\n".join([title, txt]).lower()
                if not combined:
                    time.sleep(interval)
                    continue

                core_hits = sum(1 for x in core_markers if x in combined)
                tf_hits = sum(1 for x in tf_markers if x in combined)

                if core_hits >= 3:
                    return True
                if core_hits >= 2 and tf_hits >= 2:
                    return True
                if self._is_gmgn_shell_page(title, txt):
                    return False
            except Exception:
                pass
            time.sleep(interval)

        return False

    def _finish_gmgn_walkthrough(self, tab, max_clicks: int = 12, interval: float = 0.35) -> int:
        if not tab or max_clicks <= 0:
            return 0

        popup_reason = self._gmgn_popup_block_reason(tab)
        if not popup_reason:
            return 0

        clicked = 0
        labels = ["下一步", "下一个", "完成", "Next", "Done", "Finish"]
        attempts = max(3, min(max_clicks, 6))

        def _click_in_scope(roots_only: bool) -> str:
            payload = json.dumps(labels, ensure_ascii=False)
            roots_flag = "true" if roots_only else "false"
            try:
                return str(
                    tab.run_js(
                        f"""
                        const labels = {payload};
                        const rootsOnly = {roots_flag};
                        const isVisible = (el) => {{
                            if (!el) return false;
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                        }};
                        const scopes = rootsOnly
                            ? Array.from(document.querySelectorAll('.ant-modal, .ant-modal-root, [role="dialog"], .ant-drawer, .ant-drawer-content, .ant-tour, .driver-popover, .shepherd-element, .react-joyride__tooltip, .overlay, .modal, .popup'))
                            : [document];
                        for (const scope of scopes) {{
                            if (scope !== document && !isVisible(scope)) continue;
                            const nodes = Array.from(scope.querySelectorAll('button, [role="button"], .ant-btn, a, div[tabindex], span'));
                            for (const label of labels) {{
                                for (const node of nodes) {{
                                    if (!isVisible(node)) continue;
                                    const txt = (node.innerText || node.textContent || '').trim();
                                    if (txt === label) {{
                                        node.click();
                                        return label;
                                    }}
                                }}
                            }}
                        }}
                        return '';
                        """
                    ) or ""
                ).strip()
            except Exception:
                return ""

        for _ in range(attempts):
            popup_reason = self._gmgn_popup_block_reason(tab)
            if not popup_reason:
                return clicked

            clicked_label = _click_in_scope(True)
            if not clicked_label:
                clicked_label = _click_in_scope(False)
            if not clicked_label:
                break

            clicked += 1
            time.sleep(interval)
            popup_after = self._gmgn_popup_block_reason(tab)
            logger.info(
                "GMGNWalkthrough | clicked=%s | label=%s | popup_after=%s",
                clicked,
                clicked_label,
                popup_after or "",
            )
            if not popup_after:
                return clicked

        popup_reason = self._gmgn_popup_block_reason(tab)
        logger.info("GMGNWalkthrough | exhausted=true | popup_reason=%s", popup_reason or "")
        return clicked

    def _get_or_create_gmgn_tab(self):
        if not self._browser:
            return None

        saved_state = self._load_gmgn_saved_state()
        seed_token = str((saved_state or {}).get("template_token") or self.gmgn_template_token).strip() or self.gmgn_template_token
        seed_url = self._build_gmgn_token_url(seed_token, state=saved_state)

        if self._gmgn_tab:
            try:
                _ = self._gmgn_tab.url
                self._inject_gmgn_local_flags(self._gmgn_tab)
                if saved_state:
                    self._apply_gmgn_saved_state(self._gmgn_tab, saved_state, include_session=False)
                return self._gmgn_tab
            except Exception:
                self._gmgn_tab = None

        try:
            tab = self._browser.new_tab(seed_url)
            self._gmgn_tab = tab
        except Exception:
            return None

        try:
            tab.wait.ele("tag:body", timeout=6)
        except Exception:
            pass

        self._inject_gmgn_local_flags(tab)
        if saved_state:
            try:
                self._apply_gmgn_saved_state(tab, saved_state, include_session=False)
            except Exception:
                pass

        try:
            self._finish_gmgn_walkthrough(tab, max_clicks=8, interval=0.20)
        except Exception:
            pass

        return tab

    def _sync_scrape_gmgn(self, ca: str, full_scan: bool = False, priority: str = "normal", force_fast_retry: bool = False) -> Dict[str, Any]:
        priority_norm = str(priority or "").lower()
        hard_deadline_sec = 2.5 if not full_scan else (22.0 if priority_norm == "high" else 12.0)
        deadline_at = time.perf_counter() + hard_deadline_sec
        result = {
            "top10_ratio": None,
            "header_liq_usd": 0,
            "dex_paid": None,
            "is_burned": None,
            "is_locked": None,
            "mint_authority_present": None,
            "freeze_authority_present": None,
            "token_image_url": "",
            "token_image_source": "",
            "raw_data": {},
            "screenshot": "",
            "gmgn_fast_needs_followup": False,
            "gmgn_followup_required": False,
            "gmgn_fast_weak_reason": "",
        }

        def _mark_weak(reason: str) -> Dict[str, Any]:
            result["gmgn_fast_needs_followup"] = True
            result["gmgn_followup_required"] = True
            if reason and not result.get("gmgn_fast_weak_reason"):
                result["gmgn_fast_weak_reason"] = reason
            return result

        def _deadline_expired(reason: str) -> bool:
            if time.perf_counter() <= deadline_at:
                return False
            _mark_weak(reason)
            return True

        def _budget(max_timeout: float, floor: float = 0.15) -> float:
            remaining = deadline_at - time.perf_counter()
            if remaining <= 0:
                return floor
            return max(floor, min(max_timeout, remaining))

        if not self._browser:
            return _mark_weak("page_not_ready")

        saved_state = self._load_gmgn_saved_state()
        target_url = self._build_gmgn_token_url(ca, state=saved_state)
        tab = None
        persist_runtime_state = True
        try:
            tab = self._get_or_create_gmgn_tab()
            if not tab:
                time.sleep(0.15 if not full_scan else 0.30)
                tab = self._get_or_create_gmgn_tab()
                if not tab:
                    return _mark_weak("page_not_ready")
            if _deadline_expired("deadline_after_tab"):
                return result

            if saved_state:
                try:
                    current_url = str(getattr(tab, "url", "") or "")
                except Exception:
                    current_url = ""

                if "gmgn.ai" not in current_url.lower():
                    try:
                        self._bootstrap_gmgn_tab_layout(tab, saved_state)
                    except Exception:
                        pass
                    if _deadline_expired("deadline_after_bootstrap"):
                        return result

                try:
                    self._apply_gmgn_saved_state(tab, saved_state, include_session=False)
                except Exception:
                    pass
                if _deadline_expired("deadline_after_restore"):
                    return result

            try:
                if full_scan:
                    tab.get(target_url)
                else:
                    tab.run_js(f"window.location.href = {json.dumps(target_url)};")
            except Exception:
                if full_scan:
                    raise
                try:
                    tab.get(target_url)
                except Exception:
                    raise
            if _deadline_expired("deadline_after_nav"):
                return result

            try:
                tab.wait.ele("tag:body", timeout=_budget(4.0 if full_scan else 1.0))
            except Exception:
                pass
            if _deadline_expired("deadline_after_body_wait"):
                return result

            if saved_state:
                try:
                    self._apply_gmgn_saved_state(tab, saved_state, include_session=False)
                except Exception:
                    pass
                if _deadline_expired("deadline_after_body_restore"):
                    return result

            sleep_budget = max(0.0, min(0.35 if full_scan else 0.05, deadline_at - time.perf_counter()))
            if sleep_budget > 0:
                time.sleep(sleep_budget)
            if _deadline_expired("deadline_after_nav_sleep"):
                return result

            try:
                self._finish_gmgn_walkthrough(tab, max_clicks=2 if full_scan else 3, interval=0.12 if full_scan else 0.08)
            except Exception:
                pass
            if _deadline_expired("deadline_after_walkthrough"):
                return result

            popup_reason = self._gmgn_popup_block_reason(tab)
            if not full_scan and popup_reason in {"overlay_mask", "popup_blocked"}:
                return _mark_weak(popup_reason)

            if _deadline_expired("deadline_before_target_wait"):
                return result
            target_page_ready = self._wait_gmgn_target_page(
                tab,
                ca,
                timeout=_budget(6.0 if full_scan else 1.2, floor=0.20),
                interval=0.25 if full_scan else 0.12,
            )
            if _deadline_expired("deadline_after_target_wait"):
                return result
            if not target_page_ready and not full_scan:
                if _deadline_expired("deadline_before_reprobe"):
                    return result
                try:
                    tab.run_js(f"window.location.href = {json.dumps(target_url)};")
                except Exception:
                    try:
                        tab.get(target_url)
                    except Exception:
                        pass
                if _deadline_expired("deadline_after_reprobe_nav"):
                    return result
                try:
                    tab.wait.ele("tag:body", timeout=_budget(1.2 if force_fast_retry else 0.8))
                except Exception:
                    pass
                if _deadline_expired("deadline_after_reprobe_body_wait"):
                    return result
                if saved_state:
                    try:
                        self._apply_gmgn_saved_state(tab, saved_state, include_session=False)
                    except Exception:
                        pass
                    if _deadline_expired("deadline_after_reprobe_restore"):
                        return result
                popup_reason = self._gmgn_popup_block_reason(tab)
                if popup_reason in {"overlay_mask", "popup_blocked"}:
                    return _mark_weak(popup_reason)
                target_page_ready = self._wait_gmgn_target_page(
                    tab,
                    ca,
                    timeout=_budget(1.8 if force_fast_retry else 1.0, floor=0.20),
                    interval=0.12 if force_fast_retry else 0.10,
                )
                if _deadline_expired("deadline_after_reprobe_target_wait"):
                    return result

            if not target_page_ready:
                _mark_weak("page_not_ready")

            current_url = str(getattr(tab, "url", "") or "")
            title_text = str(tab.title or "")
            if _deadline_expired("deadline_before_parse"):
                return result

            page_text = ""
            try:
                body = tab.ele("tag:body", timeout=1)
                if body and body.text:
                    page_text = body.text
            except Exception:
                page_text = ""
            if _deadline_expired("deadline_after_body_read"):
                return result

            if not full_scan and len(page_text.strip()) < 80:
                try:
                    time.sleep(0.12 if not force_fast_retry else 0.18)
                    body = tab.ele("tag:body", timeout=1)
                    if body and body.text:
                        page_text = body.text
                except Exception:
                    pass
                if _deadline_expired("deadline_after_body_retry"):
                    return result

            if not full_scan:
                try:
                    visible_text = self._extract_visible_text(tab)
                except Exception:
                    visible_text = ""
                if len(str(visible_text or "").strip()) > len(page_text.strip()):
                    page_text = visible_text
                if _deadline_expired("deadline_after_visible_text"):
                    return result

            text_source = page_text
            if not text_source:
                try:
                    text_source = self._extract_visible_text(tab)
                except Exception:
                    text_source = ""
                if _deadline_expired("deadline_after_text_fallback"):
                    return result

            if len((text_source or "").strip()) < 20 and len(title_text.strip()) < 4:
                return _mark_weak("page_not_ready")

            combined_parts = [current_url, title_text]
            if text_source:
                combined_parts.append(text_source)
            combined_text = "\n".join(part for part in combined_parts if part)

            if full_scan:
                if _deadline_expired("deadline_before_screenshot"):
                    return result
                chart_path = self._try_save_chart_screenshot(tab, ca)
                if chart_path:
                    result["screenshot"] = chart_path
                if _deadline_expired("deadline_after_screenshot"):
                    return result

            mcap_val = self._extract_gmgn_money_value(combined_text, ["市值", "market cap", "mcap", "mc"], max_gap=16)
            if mcap_val is None:
                m_title_cap = re.search(r"\|\s*\$([0-9][0-9\.,]*[KkMmBb]?)\s*\|\s*GMGN", title_text, re.IGNORECASE)
                if m_title_cap:
                    mcap_val = _to_float(m_title_cap.group(1), 0.0)

            liq_raw = self._extract_gmgn_money_raw(combined_text, ["池子", "liquidity", "lp"], max_gap=12)
            liq_val = self._extract_gmgn_money_value(combined_text, ["池子", "liquidity", "lp"], max_gap=12)
            liq_accepted, _ = self._assess_gmgn_header_liquidity(liq_raw, liq_val, mcap_val)
            if liq_accepted and liq_val is not None:
                result["header_liq_usd"] = liq_val

            dex_paid_text = self._extract_gmgn_label_snippet(combined_text, [r"Dex付费", r"Dex Paid", r"DexPaid"], follow_lines=1)
            burned_text = self._extract_gmgn_label_snippet(combined_text, [r"烧池子", r"Liquidity Burned", r"LP Burned"], follow_lines=1)
            locked_text = self._extract_gmgn_label_snippet(combined_text, [r"流动性锁定", r"Liquidity Locked", r"LP Locked", r"Pool Locked", r"锁池", r"锁定"], follow_lines=1)
            mint_text = self._extract_gmgn_label_snippet(combined_text, [r"Mint丢弃", r"Mint Renounced", r"Mint", r"增发"], follow_lines=1)
            freeze_text = self._extract_gmgn_label_snippet(combined_text, [r"Freeze", r"冻结", r"黑名单", r"Blacklist"], follow_lines=1)

            result["dex_paid"] = self._extract_gmgn_dex_paid_state(dex_paid_text or combined_text)
            result["is_burned"] = self._extract_gmgn_burn_state(burned_text or combined_text)

            lock_state = self._extract_gmgn_lock_state(locked_text or combined_text)
            if lock_state is not None:
                result["is_locked"] = lock_state

            mint_state = self._extract_gmgn_mint_state(mint_text or combined_text)
            if mint_state is not None:
                result["mint_authority_present"] = mint_state

            freeze_state = self._extract_gmgn_freeze_state(freeze_text or combined_text)
            if freeze_state is not None:
                result["freeze_authority_present"] = freeze_state

            top10_context = self._extract_gmgn_top10_context(tab)
            top10_source_text = top10_context or text_source or combined_text
            top10_trace = self._extract_gmgn_top10_trace(top10_source_text)
            if not top10_trace.get("normalized") and top10_source_text != combined_text:
                fallback_trace = self._extract_gmgn_top10_trace(combined_text)
                if fallback_trace.get("normalized"):
                    top10_trace = fallback_trace
            if top10_trace.get("normalized"):
                result["top10_ratio"] = top10_trace.get("normalized")
            if _deadline_expired("deadline_after_top10"):
                return result

            raw = {}

            def _count_label(kws: List[str]) -> Optional[int]:
                p = "|".join(re.escape(k) for k in kws if k)
                for txt in (text_source, combined_text):
                    if not txt or not p:
                        continue
                    m = re.search(rf"(?:{p})[^0-9\n<]*([0-9]+)", txt, re.IGNORECASE)
                    if m:
                        try:
                            return int(m.group(1))
                        except Exception:
                            pass
                cnt = self._extract_tag_count(combined_text, kws)
                return cnt if cnt is not None else None

            tag_map = {
                "smart": ["Smart Money", "聪明钱", "Smart", "GGer", "GG者", "GG"],
                "rat": ["Rat Farm", "老鼠仓", "Rat"],
                "sniper": ["Sniper", "狙击手", "狙击者"],
                "dev": ["Developer", "Dev", "开发者", "DEV"],
                "bundle": ["Bundled", "Bundle", "Bundler", "捆绑", "捆绑交易", "捆绑者"],
                "kol": ["KOL"],
                "blue_chip": ["Blue Chip", "蓝筹", "蓝筹持有者"],
                "phishing_wallets": ["Phishing", "Fish", "钓鱼钱包"],
            }
            for key, kws in tag_map.items():
                raw[key] = _count_label(kws)
            result["raw_data"] = raw

            token_image_url = self._pick_gmgn_avatar(tab)
            if token_image_url:
                result["token_image_url"] = token_image_url
                result["token_image_source"] = (self._last_gmgn_avatar_pick or {}).get("source") or "gmgn/dom"
            if _deadline_expired("deadline_after_avatar"):
                return result

            has_raw_signal = any(v is not None for v in raw.values())
            has_safety = any(
                result.get(key) is not None
                for key in ("dex_paid", "is_burned", "is_locked", "mint_authority_present", "freeze_authority_present")
            )
            if not any(
                [
                    result.get("top10_ratio"),
                    _to_float(result.get("header_liq_usd"), 0.0) > 0,
                    has_raw_signal,
                    has_safety,
                    result.get("token_image_url"),
                ]
            ):
                _mark_weak("no_blocks_found")
            if _deadline_expired("deadline_after_parse"):
                return result

        except Exception as e:
            if isinstance(e, PageDisconnectedError) or "PageDisconnectedError" in str(e):
                persist_runtime_state = False
                self._gmgn_tab = None
                self._browser = None
                raise
            if "GMGN_BROWSER_BLANK_PAGE" in str(e):
                persist_runtime_state = False
                self._gmgn_tab = None
                raise
            logger.debug(f"⚠️ GMGN 抓取异常 ({ca[:6]}...): {e}")
        finally:
            if tab and persist_runtime_state:
                try:
                    self._persist_gmgn_runtime_state(tab, ca)
                except Exception:
                    pass

        return result

    async def fetch_gmgn_analytics(self, ca: str, mode: str = "fast", priority: str = "normal") -> Dict[str, Any]:
        if not ca:
            return {}
        mode = "full" if str(mode or "").lower() == "full" else "fast"
        priority = "high" if str(priority or "").lower() == "high" else "normal"
        logger.info(
            "GMGNRouteTrace | role=%s | ca=%s | mode=%s | priority=%s",
            self._fetcher_role,
            ca[:8],
            mode,
            priority,
        )
        is_interactive_fast = bool(self._fetcher_role == "interactive" and mode == "fast")
        same_ca_bypass = mode == "full"
        now = time.time()
        weak_state = self._gmgn_weak_state.get(ca, {}) if isinstance(self._gmgn_weak_state.get(ca, {}), dict) else {}
        weak_count = int(weak_state.get("count") or 0)
        weak_reason = str(weak_state.get("reason") or "")
        weak_age = now - float(weak_state.get("ts") or 0.0)
        skip_state = self._gmgn_skip_state.get(ca, {}) if isinstance(self._gmgn_skip_state.get(ca, {}), dict) else {}
        skip_count = int(skip_state.get("count") or 0)
        skip_age = now - float(skip_state.get("ts") or 0.0)
        force_fast_retry = False
        if priority == "normal" and mode == "fast" and not same_ca_bypass:
            if weak_count >= 3 and weak_age < 30:
                logger.info(
                    "GMGNRetryTrace | ca=%s | weak_count=%s | action=skip_fast_retry | reason=%s",
                    ca[:8],
                    weak_count,
                    weak_reason or "weak_result",
                )
                return self._gmgn_queue_timeout_result("skip_fast_retry")
            if weak_count >= 1 and weak_age < 6:
                logger.info(
                    "GMGNRetryTrace | ca=%s | weak_count=%s | action=backoff | reason=%s",
                    ca[:8],
                    weak_count,
                    weak_reason or "weak_result",
                )
                return self._gmgn_queue_timeout_result("backoff")
            if weak_count >= 2 and weak_age < 60 and not bool(weak_state.get("fallback_used")):
                force_fast_retry = True
                logger.info(
                    "GMGNRetryTrace | ca=%s | weak_count=%s | action=retry_fallback | reason=%s",
                    ca[:8],
                    weak_count,
                    weak_reason or "weak_result",
                )
        await self._gmgn_mark_pending(priority, +1)
        starvation_guard = (
            priority == "normal"
            and mode == "fast"
            and not same_ca_bypass
            and skip_count >= 2
            and skip_age < 20
        )
        if priority == "high":
            self._gmgn_priority_ca = ca
            self._gmgn_priority_until = now + 10.0
        lock_wait_start = time.perf_counter()
        lock_acquired = False
        should_short_wait = bool(
            priority == "normal"
            and mode == "fast"
            and not same_ca_bypass
            and self._gmgn_high_priority_waiting(ca, priority)
            and not starvation_guard
        )
        try:
            if should_short_wait:
                short_wait_budget = 1.20 if skip_count <= 0 else 0.65
                try:
                    await asyncio.wait_for(self._gmgn_lock.acquire(), timeout=short_wait_budget)
                    lock_acquired = True
                except asyncio.TimeoutError:
                    self._gmgn_skip_state[ca] = {"ts": time.time(), "count": skip_count + 1}
                    logger.info(
                        "GMGNQueueTrace | ca=%s | priority=%s | queue_len=%s | lock_wait=%.2fs | yielded_to_high=true | same_ca_bypass=%s | reason=yield_to_high_priority",
                        ca[:8],
                        priority,
                        self._gmgn_queue_len(),
                        time.perf_counter() - lock_wait_start,
                        same_ca_bypass,
                    )
                    return self._gmgn_queue_timeout_result()

            if not lock_acquired:
                if is_interactive_fast:
                    interactive_fast_budget = 1.25 if priority == "high" else 0.85
                    try:
                        await asyncio.wait_for(self._gmgn_lock.acquire(), timeout=interactive_fast_budget)
                        lock_acquired = True
                    except asyncio.TimeoutError:
                        self._gmgn_skip_state[ca] = {"ts": time.time(), "count": max(1, skip_count + 1)}
                        logger.info(
                            "GMGNQueueTrace | ca=%s | priority=%s | queue_len=%s | lock_wait=%.2fs | yielded_to_high=false | same_ca_bypass=%s | reason=interactive_fast_budget",
                            ca[:8],
                            priority,
                            self._gmgn_queue_len(),
                            time.perf_counter() - lock_wait_start,
                            same_ca_bypass,
                        )
                        return self._gmgn_queue_timeout_result("interactive_lock_timeout")
                else:
                    await self._gmgn_lock.acquire()
                    lock_acquired = True

            lock_wait_sec = time.perf_counter() - lock_wait_start
            high_waiting = self._gmgn_high_priority_waiting(ca, priority) and not same_ca_bypass
            effective_mode = "fast" if (high_waiting and mode != "fast" and not same_ca_bypass) else mode
            self._gmgn_skip_state.pop(ca, None)
            logger.info(
                "GMGNQueueTrace | ca=%s | priority=%s | queue_len=%s | lock_wait=%.2fs | yielded_to_high=%s | same_ca_bypass=%s",
                ca[:8],
                priority,
                self._gmgn_queue_len(),
                lock_wait_sec,
                high_waiting,
                same_ca_bypass,
            )
            if starvation_guard:
                logger.info(
                    "GMGNQueueTrace | ca=%s | priority=%s | queue_len=%s | lock_wait=%.2fs | yielded_to_high=false | same_ca_bypass=%s | reason=starvation_guard",
                    ca[:8],
                    priority,
                    self._gmgn_queue_len(),
                    lock_wait_sec,
                    same_ca_bypass,
                )

            reset_retry_triggered = False

            for attempt in (1, 2):
                if attempt == 2 and not reset_retry_triggered:
                    break

                if not await self._ensure_browser():
                    logger.warning(f"GMGN browser unavailable before attempt {attempt}: {ca[:8]}...")
                    return {}

                started = time.perf_counter()
                released_early = bool(high_waiting and effective_mode == "fast")
                lock_wait_sec = time.perf_counter() - lock_wait_start
                try:
                    result = await asyncio.to_thread(self._sync_scrape_gmgn, ca, effective_mode == "full", priority, force_fast_retry)
                    if isinstance(result, dict):
                        cached_avatar_url, cached_avatar_source = self._cache_gmgn_avatar(
                            ca,
                            result.get("token_image_url") or "",
                            result.get("token_image_source") or "",
                        )
                        if cached_avatar_url:
                            result["token_image_url"] = cached_avatar_url
                            result["token_image_source"] = cached_avatar_source
                    elapsed = time.perf_counter() - started
                    raw_data = result.get("raw_data") if isinstance(result, dict) else {}
                    has_raw_signal = isinstance(raw_data, dict) and any(_to_int(v, 0) > 0 for v in raw_data.values())
                    released_early = released_early or bool(result.get("gmgn_released_early"))
                    result_strength = str(result.get("gmgn_result_strength") or "").strip().lower()
                    result_is_weak = bool(
                        effective_mode == "fast"
                        and (
                            self._gmgn_result_is_thin(result)
                            or bool(result.get("gmgn_fast_needs_followup"))
                            or result_strength in {"weak", "partial"}
                        )
                    )
                    has_useful_result = bool(
                        result.get("top10_ratio")
                        or result.get("screenshot")
                        or has_raw_signal
                        or result.get("gmgn_tags_present")
                        or _to_float(result.get("header_liq_usd"), 0.0) > 0
                        or result.get("dex_paid") is not None
                        or result.get("is_burned") is not None
                        or result.get("is_locked") is not None
                        or result.get("token_image_url")
                    )

                    if has_useful_result and not result_is_weak:
                        self._gmgn_weak_state.pop(ca, None)
                        logger.info(
                            f"GMGN scrape attempt {attempt} completed in {elapsed:.2f}s | "
                            f"mode={effective_mode} | priority={priority} | reset_retry={reset_retry_triggered} | {ca[:8]}..."
                        )
                        logger.info(
                            "GMGNQueueTrace | ca=%s | priority=%s | released_early=%s",
                            ca[:8],
                            priority,
                            released_early,
                        )
                        return result if isinstance(result, dict) else {}

                    if has_useful_result and result_is_weak:
                        logger.info(
                            f"GMGN scrape attempt {attempt} returned thin result in {elapsed:.2f}s | "
                            f"mode={effective_mode} | priority={priority} | reset_retry={reset_retry_triggered} | {ca[:8]}..."
                        )
                        new_reason = str(result.get("gmgn_fast_weak_reason") or "thin_result")
                        same_reason = new_reason == weak_reason and weak_age < 120
                        self._gmgn_weak_state[ca] = {
                            "ts": time.time(),
                            "reason": new_reason,
                            "count": (weak_count + 1) if same_reason else 1,
                            "fallback_used": bool(weak_state.get("fallback_used")) or force_fast_retry,
                        }
                        logger.info(
                            "GMGNRetryTrace | ca=%s | weak_count=%s | action=record_weak | reason=%s",
                            ca[:8],
                            self._gmgn_weak_state[ca]["count"],
                            new_reason,
                        )
                        logger.info(
                            "GMGNQueueTrace | ca=%s | priority=%s | released_early=%s",
                            ca[:8],
                            priority,
                            released_early,
                        )
                        return result if isinstance(result, dict) else {}

                    logger.info(
                        f"GMGN scrape attempt {attempt} returned weak result in {elapsed:.2f}s | "
                        f"mode={effective_mode} | priority={priority} | reset_retry={reset_retry_triggered} | {ca[:8]}..."
                    )
                    new_reason = str(result.get("gmgn_fast_weak_reason") or "weak_result")
                    same_reason = new_reason == weak_reason and weak_age < 120
                    self._gmgn_weak_state[ca] = {
                        "ts": time.time(),
                        "reason": new_reason,
                        "count": (weak_count + 1) if same_reason else 1,
                        "fallback_used": bool(weak_state.get("fallback_used")) or force_fast_retry,
                    }
                    logger.info(
                        "GMGNRetryTrace | ca=%s | weak_count=%s | action=record_weak | reason=%s",
                        ca[:8],
                        self._gmgn_weak_state[ca]["count"],
                        new_reason,
                    )
                    logger.info(
                        "GMGNQueueTrace | ca=%s | priority=%s | released_early=%s",
                        ca[:8],
                        priority,
                        released_early,
                    )
                    return {}
                except PageDisconnectedError as e:
                    elapsed = time.perf_counter() - started
                    logger.warning(
                        f"GMGN scrape attempt {attempt} failed in {elapsed:.2f}s | "
                        f"mode={effective_mode} | priority={priority} | "
                        f"browser_level=True | reset_retry={reset_retry_triggered} | "
                        f"reason=PageDisconnectedError | {ca[:8]}... | {e}"
                    )
                    if attempt == 1:
                        logger.warning(f"GMGN reset retry triggered after browser disconnect: {ca[:8]}...")
                        await self._reset_browser()
                        reset_retry_triggered = True
                        continue
                    return {}
                except Exception as e:
                    elapsed = time.perf_counter() - started
                    msg = str(e)
                    is_browser_level = "GMGN_BROWSER_BLANK_PAGE" in msg or "PageDisconnectedError" in msg
                    logger.warning(
                        f"GMGN scrape attempt {attempt} failed in {elapsed:.2f}s | "
                        f"mode={effective_mode} | priority={priority} | "
                        f"browser_level={is_browser_level} | reset_retry={reset_retry_triggered} | "
                        f"{ca[:8]}... | {e}"
                    )
                    if attempt == 1 and is_browser_level:
                        logger.warning(f"GMGN reset retry triggered after browser-level failure: {ca[:8]}...")
                        await self._reset_browser()
                        reset_retry_triggered = True
                        continue
                    logger.info(
                        "GMGNQueueTrace | ca=%s | priority=%s | released_early=%s",
                        ca[:8],
                        priority,
                        released_early,
                    )
                    return {}
            logger.info(
                "GMGNQueueTrace | ca=%s | priority=%s | released_early=%s",
                ca[:8],
                priority,
                bool(high_waiting and effective_mode == "fast"),
            )
            return {}
        finally:
            if lock_acquired:
                try:
                    self._gmgn_lock.release()
                except Exception:
                    pass
            await self._gmgn_mark_pending(priority, -1)
            if priority == "high" and self._gmgn_priority_ca == ca:
                self._gmgn_priority_ca = ""
                self._gmgn_priority_until = 0.0

    async def _get_jupiter_price_only(self, ca: str) -> Tuple[float, str]:
        if not ca:
            return 0.0, ""

        session = await self._get_session()
        headers = {"Accept": "application/json"}
        url = self.jup_lite_price_url
        source = "jupiter_lite"

        if self.jup_api_key:
            url = self.jup_price_url
            headers["x-api-key"] = self.jup_api_key
            source = "jupiter"

        try:
            async with session.get(
                url,
                params={"ids": ca},
                headers=headers,
                timeout=3.0
            ) as resp:
                if resp.status != 200:
                    return 0.0, ""
                data = await resp.json()

                node = None
                if isinstance(data, dict):
                    if ca in data:
                        node = data.get(ca)
                    elif "data" in data and isinstance(data["data"], dict):
                        node = data["data"].get(ca)

                if not isinstance(node, dict):
                    return 0.0, ""

                price = _to_float(node.get("usdPrice"), 0.0)
                return price, source if price > 0 else ""
        except Exception:
            return 0.0, ""

    async def get_price_only(self, ca: str) -> tuple:
        if not ca:
            return 0.0, 0.0

        jup_price, jup_source = await self._get_jupiter_price_only(ca)

        try:
            ds_data = await self._fetch_dexscreener(ca)
            pairs = ds_data.get("pairs", []) if ds_data else []
            if pairs:
                sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
                best_pair = sol_pairs[0] if sol_pairs else pairs[0]
                dex_price = _to_float(best_pair.get("priceUsd"), 0.0)
                mcap = _to_float(best_pair.get("fdv") or best_pair.get("marketCap"), 0.0)

                if jup_price > 0:
                    logger.debug(f"✅ 极速查价来源: {jup_source} | {ca[:6]}... | price={jup_price}")
                    return jup_price, mcap

                return dex_price, mcap

            if jup_price > 0:
                logger.debug(f"✅ 极速查价来源: {jup_source} | {ca[:6]}... | price={jup_price}")
                return jup_price, 0.0

            return 0.0, 0.0
        except Exception as e:
            if jup_price > 0:
                logger.debug(f"✅ 极速查价来源: {jup_source} | {ca[:6]}... | price={jup_price}")
                return jup_price, 0.0
            logger.debug(f"⚠️ 极速查价 API 超时或失败 ({ca[:6]}...): {e}")
            return 0.0, 0.0

    async def close(self):
        await self._reset_browser()
        if self._session:
            await self._session.close()


def _normalize_gmgn_route(route: str) -> str:
    text = str(route or "interactive").strip().lower()
    return "background" if text in {"background", "bg", "worker", "patrol"} else "interactive"


def _route_fetcher(route: str = "interactive") -> DataFetcher:
    return background_fetcher if _normalize_gmgn_route(route) == "background" else interactive_fetcher


def _background_pct_change(curr: float, prev: float) -> float:
    curr_val = _to_float(curr, 0.0)
    prev_val = _to_float(prev, 0.0)
    if curr_val <= 0 or prev_val <= 0:
        return 0.0
    return abs(curr_val - prev_val) / prev_val


def _background_market_liquidity(raw_market: Optional[Dict[str, Any]]) -> float:
    market = raw_market if isinstance(raw_market, dict) else {}
    liquidity = max(
        _to_float(market.get("liquidity_usd"), 0.0),
        _to_float(market.get("pair_liquidity_usd"), 0.0),
        _to_float(market.get("exit_liquidity_usd"), 0.0),
        _to_float(market.get("birdeye_liquidity_usd"), 0.0),
    )
    if liquidity <= 0 and isinstance(market.get("liquidity"), dict):
        liquidity = _to_float((market.get("liquidity") or {}).get("usd"), 0.0)
    return liquidity


async def _background_gmgn_allowed(ca: str, raw_market: Optional[Dict[str, Any]] = None) -> bool:
    try:
        market = raw_market if isinstance(raw_market, dict) and raw_market else await background_fetcher.get_market_data(ca)
        if not isinstance(market, dict) or not market:
            logger.info("BackgroundGMGNGate | ca=%s | allowed=false | reason=no_market", (ca or "")[:8])
            return False

        snapshot = await db.get_signal_snapshot(ca)
        terminal = snapshot.get("terminal_states", {}) if isinstance(snapshot, dict) else {}
        stable = terminal.get("stable_snapshot") if isinstance(terminal.get("stable_snapshot"), dict) else {}

        curr_price = max(
            _to_float(market.get("priceUsd"), 0.0),
            _to_float(market.get("price_usd"), 0.0),
        )
        prev_price = max(
            _to_float((snapshot or {}).get("last_notified_price"), 0.0),
            _to_float((snapshot or {}).get("entry_price"), 0.0),
            _to_float(terminal.get("entry_price"), 0.0),
            _to_float(stable.get("price_usd"), 0.0),
        )

        curr_liq = _background_market_liquidity(market)
        prev_liq = max(
            _to_float((snapshot or {}).get("exit_liquidity_usd"), 0.0),
            _to_float((snapshot or {}).get("pair_liquidity_usd"), 0.0),
            _to_float(terminal.get("exit_liquidity_usd"), 0.0),
            _to_float(terminal.get("pair_liquidity_usd"), 0.0),
            _to_float(terminal.get("liquidity_usd"), 0.0),
            _to_float(stable.get("exit_liquidity_usd"), 0.0),
            _to_float(stable.get("pair_liquidity_usd"), 0.0),
            _to_float(stable.get("liquidity_usd"), 0.0),
        )

        price_threshold = _to_float(os.getenv("PATROL_GMGN_PRICE_CHANGE_THRESHOLD", "0.18"), 0.18)
        liq_threshold = _to_float(os.getenv("PATROL_GMGN_LIQ_CHANGE_THRESHOLD", "0.30"), 0.30)
        price_change = _background_pct_change(curr_price, prev_price)
        liq_change = _background_pct_change(curr_liq, prev_liq)

        missing_top10 = terminal.get("top10_ratio_gmgn") in (None, "", "—")
        missing_tags = not bool(terminal.get("gmgn_tags_present"))
        weak_strength = str(terminal.get("gmgn_result_strength") or "").strip().lower() in {"", "weak", "partial"}
        missing_safety = any(terminal.get(key) is None for key in ("dex_paid", "is_locked", "is_burned"))

        if missing_top10 or missing_tags or weak_strength or missing_safety:
            logger.info(
                "BackgroundGMGNGate | ca=%s | allowed=true | reason=backfill | price_change=%.4f | liq_change=%.4f",
                (ca or "")[:8],
                price_change,
                liq_change,
            )
            return True

        if price_change >= price_threshold:
            logger.info(
                "BackgroundGMGNGate | ca=%s | allowed=true | reason=price_change | price_change=%.4f | liq_change=%.4f",
                (ca or "")[:8],
                price_change,
                liq_change,
            )
            return True

        if liq_change >= liq_threshold:
            logger.info(
                "BackgroundGMGNGate | ca=%s | allowed=true | reason=liquidity_change | price_change=%.4f | liq_change=%.4f",
                (ca or "")[:8],
                price_change,
                liq_change,
            )
            return True

        logger.info(
            "BackgroundGMGNGate | ca=%s | allowed=false | reason=api_gate | price_change=%.4f | liq_change=%.4f",
            (ca or "")[:8],
            price_change,
            liq_change,
        )
        return False
    except Exception as e:
        logger.warning("BackgroundGMGNGate | ca=%s | allowed=false | reason=gate_exception | err=%s", (ca or "")[:8], e)
        return False


interactive_fetcher = DataFetcher(profile_dir="data/browser_profile_interactive")
background_fetcher = DataFetcher(profile_dir="data/browser_profile_background")
fetcher = interactive_fetcher


async def prepare_fetcher_profiles():
    results = await asyncio.gather(
        interactive_fetcher.prepare_browser_profile(),
        background_fetcher.prepare_browser_profile(),
    )
    out: Dict[str, Dict[str, Any]] = {}
    for item in results:
        if isinstance(item, dict):
            out[str(item.get("role") or "")] = item
    return out


async def close_fetchers():
    await asyncio.gather(
        interactive_fetcher.close(),
        background_fetcher.close(),
    )


async def get_market_data(ca: str):
    return await fetcher.get_market_data(ca)


async def get_gmgn_analytics(ca: str, mode: str = "fast", priority: str = "normal", route: str = "background", raw_market: Optional[Dict[str, Any]] = None):
    selected_route = _normalize_gmgn_route(route)
    selected_fetcher = _route_fetcher(selected_route)
    if selected_route == "background" and str(priority or "").lower() != "high":
        if not await _background_gmgn_allowed(ca, raw_market=raw_market):
            return {}
    return await selected_fetcher.fetch_gmgn_analytics(ca, mode=mode, priority=priority)


async def get_helius_security(ca: str):
    return await fetcher.get_helius_security(ca)


async def get_rugcheck_data(ca: str):
    return await fetcher.fetch_rugcheck_data(ca)


async def get_goplus_security(ca: str):
    return await fetcher.fetch_goplus_security(ca)


async def get_price_only(ca: str):
    return await fetcher.get_price_only(ca)
