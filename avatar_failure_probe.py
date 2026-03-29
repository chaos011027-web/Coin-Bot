import argparse
import asyncio
import csv
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from modules.data_fetcher import DataFetcher


DEFAULT_FAILED_CAS = [
    "5JAXbqTMJc2ZcdQL8kKxeBwpG9HN76MMAnTdExyRpump",
    "6vikMVXwa987yVenBn3P1iHsoTcjAp42SsSKUYcwpump",
    "9TAykmz2RK97apRV3rwyJNnPgJY3Fu98yZQXcUJSpump",
    "6naLvwxo84oFeK8sEYeuSDmyCMzpJLJvzADuXbQmpump",
    "9boMocazJCnA41HRFa5q1WPzHMU83sQswmVMsdT1pump",
    "F8yiuqyAeUHseuHUJLJTZGpcJo69QHZD8MKAn5oYpump",
    "BUYoUoSMuhXhjcnFZn7Ym6Z8SSL3bnBbPXVS5H3ipump",
    "91ZNjmsjMVdi6jYx313yBonvPbBSDT16B8joFrFxpump",
    "J95Nvz1NaX32gfTyq62uPDNaHPWeJ49vNJoH2eiMpump",
    "8d7CDhkxj5zvfam9qysCG8zUm1fcsRn7GmU2475epump",
    "DjDjxZWLmcafABUzWoAHjkVVyAw3ukEsVk59RkCTpump",
]


def read_ca_file(path: Optional[str]) -> List[str]:
    if not path:
        return list(DEFAULT_FAILED_CAS)
    if not os.path.exists(path):
        raise FileNotFoundError(f"CA file not found: {path}")
    cas: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            ca = line.strip()
            if not ca or ca.startswith("#"):
                continue
            cas.append(ca)
    return cas


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


async def _fetch_json(session: aiohttp.ClientSession, url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        async with session.get(url, headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                return None, f"http_{resp.status}:{text[:180]}"
            try:
                return json.loads(text), "ok"
            except Exception:
                return None, f"json_decode_failed:{text[:180]}"
    except Exception as exc:
        return None, f"exc:{type(exc).__name__}:{exc}"


class AvatarFailureProbe:
    def __init__(self, with_gmgn: bool = False, profile_dir: str = "data/browser_profile_probe"):
        self.with_gmgn = with_gmgn
        self.fetcher = DataFetcher(profile_dir=profile_dir)

    async def close(self) -> None:
        await self.fetcher.close()

    async def probe_one(self, ca: str) -> Dict[str, Any]:
        t0 = time.perf_counter()
        session = await self.fetcher._get_session()
        row: Dict[str, Any] = {
            "ca": ca,
            "elapsed_ms": 0,
            "dex_pair_count": 0,
            "dex_best_liq": 0.0,
            "dex_has_image_fields": False,
            "dex_candidate_fields": "",
            "dex_selected_url": "",
            "dex_selected_source": "",
            "dex_reason": "",
            "pump_should_probe": self.fetcher._should_probe_pump(ca, None),
            "pump_image_uri": "",
            "pump_other_image_keys": "",
            "pump_selected_url": "",
            "pump_selected_source": "",
            "pump_reason": "",
            "gmgn_selected_url": "",
            "gmgn_selected_source": "",
            "gmgn_reason": "skipped",
            "path_hit": False,
            "path_value": "",
            "final_class": "",
            "notes": "",
        }

        # --- Dex raw probe ---
        dex_url = self.fetcher.dex_api_url.format(ca)
        dex_payload, dex_status = await _fetch_json(session, dex_url)
        if dex_payload is None:
            row["dex_reason"] = dex_status
        else:
            pairs = dex_payload.get("pairs") or []
            row["dex_pair_count"] = len(pairs)
            best_pair = None
            best_liq = -1.0
            candidate_field_set = set()
            has_any_image = False
            for pair in pairs:
                liq = _safe_float(((pair or {}).get("liquidity") or {}).get("usd"), 0.0)
                if liq > best_liq:
                    best_liq = liq
                    best_pair = pair
                info = (pair or {}).get("info") or {}
                base = (pair or {}).get("baseToken") or {}
                candidates = {
                    "info.imageUrl": info.get("imageUrl"),
                    "info.openGraph": info.get("openGraph"),
                    "info.image": info.get("image"),
                    "baseToken.logoURI": base.get("logoURI"),
                    "baseToken.imageUrl": base.get("imageUrl"),
                    "baseToken.imageURI": base.get("imageURI"),
                    "baseToken.icon": base.get("icon"),
                    "baseToken.iconUrl": base.get("iconUrl"),
                    "pair.imageUrl": (pair or {}).get("imageUrl"),
                    "pair.logoURI": (pair or {}).get("logoURI"),
                }
                for key, value in candidates.items():
                    if value:
                        has_any_image = True
                        candidate_field_set.add(key)
            row["dex_best_liq"] = max(0.0, best_liq)
            row["dex_has_image_fields"] = has_any_image
            row["dex_candidate_fields"] = ";".join(sorted(candidate_field_set))
            dex_url_selected, dex_source_selected = await self.fetcher._fetch_dex_avatar_url(ca)
            row["dex_selected_url"] = dex_url_selected or ""
            row["dex_selected_source"] = dex_source_selected or ""
            if dex_url_selected:
                row["dex_reason"] = "selected"
            elif has_any_image:
                row["dex_reason"] = "payload_has_image_but_selector_missed"
            elif not pairs:
                row["dex_reason"] = "no_pairs"
            else:
                row["dex_reason"] = "pairs_present_but_no_image_fields"

        # --- Pump raw probe ---
        pump_url = f"https://frontend-api.pump.fun/coins/{ca}"
        pump_payload, pump_status = await _fetch_json(session, pump_url)
        if pump_payload is None:
            row["pump_reason"] = pump_status
        else:
            image_uri = (pump_payload or {}).get("image_uri") or ""
            row["pump_image_uri"] = image_uri
            other_keys = [k for k in (pump_payload or {}).keys() if "image" in str(k).lower() and k != "image_uri"]
            row["pump_other_image_keys"] = ";".join(sorted(other_keys))
            pump_url_selected, pump_source_selected = await self.fetcher._fetch_pump_avatar_url(ca)
            row["pump_selected_url"] = pump_url_selected or ""
            row["pump_selected_source"] = pump_source_selected or ""
            if pump_url_selected:
                row["pump_reason"] = "selected"
            elif image_uri:
                row["pump_reason"] = "payload_has_image_uri_but_selector_missed"
            elif other_keys:
                row["pump_reason"] = "payload_has_other_image_keys_only"
            else:
                row["pump_reason"] = "payload_no_image_fields"

        # --- GMGN warm probe (optional) ---
        if self.with_gmgn:
            try:
                gmgn_url_selected, gmgn_source_selected = await self.fetcher._fetch_warm_gmgn_avatar_url(ca)
                row["gmgn_selected_url"] = gmgn_url_selected or ""
                row["gmgn_selected_source"] = gmgn_source_selected or ""
                row["gmgn_reason"] = "selected" if gmgn_url_selected else "source_empty"
            except Exception as exc:
                row["gmgn_reason"] = f"exc:{type(exc).__name__}:{exc}"

        # --- Materialize winning source ---
        winning_url = row["dex_selected_url"] or row["pump_selected_url"] or row["gmgn_selected_url"]
        winning_source = row["dex_selected_source"] or row["pump_selected_source"] or row["gmgn_selected_source"]
        if winning_url:
            try:
                path = await self.fetcher.ensure_token_avatar(ca, winning_url, winning_source, fast_mode=False)
                row["path_hit"] = bool(path)
                row["path_value"] = path or ""
            except Exception as exc:
                row["notes"] = f"materialize_exc:{type(exc).__name__}:{exc}"

        # --- Final class ---
        if row["dex_selected_url"]:
            row["final_class"] = "dex_has_image"
        elif row["pump_selected_url"]:
            row["final_class"] = "pump_has_image"
        elif row["gmgn_selected_url"]:
            row["final_class"] = "page_only_image"
        elif row["dex_has_image_fields"]:
            row["final_class"] = "dex_parser_miss"
        elif row["pump_image_uri"] or row["pump_other_image_keys"]:
            row["final_class"] = "pump_parser_miss"
        else:
            row["final_class"] = "no_public_image_source"

        row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        return row


async def amain() -> int:
    parser = argparse.ArgumentParser(description="Probe failed avatar samples across Dex/Pump/GMGN and classify root cause.")
    parser.add_argument("--ca-file", default="", help="Text file with one CA per line. Defaults to built-in failed sample list.")
    parser.add_argument("--with-gmgn", action="store_true", help="Also probe GMGN DOM/meta avatar (requires browser and current correct token tab).")
    parser.add_argument("--profile-dir", default="data/browser_profile_probe", help="Browser profile dir when --with-gmgn is enabled.")
    parser.add_argument("--out-dir", default="research_output", help="Output directory.")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    cas = read_ca_file(args.ca_file)
    probe = AvatarFailureProbe(with_gmgn=args.with_gmgn, profile_dir=args.profile_dir)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(args.out_dir, f"avatar_failure_probe_{timestamp}.csv")
    jsonl_path = os.path.join(args.out_dir, f"avatar_failure_probe_{timestamp}.jsonl")
    rows: List[Dict[str, Any]] = []
    try:
        for idx, ca in enumerate(cas, start=1):
            print(f"[{idx}/{len(cas)}] probing {ca} ...")
            row = await probe.probe_one(ca)
            rows.append(row)
    finally:
        await probe.close()

    if not rows:
        print("No rows produced.")
        return 1

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[OK] csv written to: {csv_path}")
    print(f"[OK] jsonl written to: {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
