import argparse
import asyncio
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


try:
    from modules.data_fetcher import DataFetcher
except Exception:
    from data_fetcher import DataFetcher  # type: ignore


CSV_HEADERS = [
    "experiment_id",
    "ca",
    "sample_type",
    "start_time",
    "end_time",
    "elapsed_ms",
    "success",
    "source",
    "depends_on_page",
    "stage",
    "gate_valid",
    "blocked_reason",
    "result_strength",
    "url_hit",
    "path_hit",
    "display_hit",
    "field_group",
    "top10_value",
    "liq_value",
    "tag_count",
    "error_type",
    "notes",
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_ca_file(path: Optional[str]) -> List[str]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CA sample file not found: {path}")
    cas: List[str] = []
    if p.suffix.lower() in {".csv"}:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            first_field = reader.fieldnames[0] if reader.fieldnames else None
            for row in reader:
                ca = (row.get("ca") or row.get("contract") or row.get("mint") or (row.get(first_field) if first_field else "") or "").strip()
                if ca:
                    cas.append(ca)
    else:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                ca = line.strip()
                if ca and not ca.startswith("#"):
                    cas.append(ca)
    seen = set()
    out = []
    for ca in cas:
        if ca not in seen:
            seen.add(ca)
            out.append(ca)
    return out


def read_page_samples(path: Optional[str]) -> List[Dict[str, str]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Page sample file not found: {path}")
    rows: List[Dict[str, str]] = []
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean = {str(k or "").strip(): str(v or "").strip() for k, v in row.items()}
            if clean.get("ca") or clean.get("url"):
                rows.append(clean)
    return rows


@dataclass
class ExperimentContext:
    output_csv: Path
    output_jsonl: Path


class Recorder:
    def __init__(self, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        self.output_csv = output_dir / f"research_results_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        self.output_jsonl = output_dir / f"research_results_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        ensure_parent(self.output_csv)
        with self.output_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()

    def write(self, row: Dict[str, Any]) -> None:
        record = {k: row.get(k, "") for k in CSV_HEADERS}
        with self.output_csv.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writerow(record)
        with self.output_jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


class ResearchRunner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.recorder = Recorder(Path(args.output_dir))
        self.fetcher = DataFetcher(profile_dir=args.profile_dir) if args.profile_dir else DataFetcher()
        self._browser_prepared = False

    async def close(self) -> None:
        try:
            session = getattr(self.fetcher, "_session", None)
            if session and not session.closed:
                await session.close()
        except Exception:
            pass

    async def ensure_browser_ready(self) -> None:
        if self._browser_prepared:
            return
        await self.fetcher.prepare_browser_profile()
        self._browser_prepared = True

    def record(self, **kwargs: Any) -> None:
        self.recorder.write(kwargs)

    def _base_row(self, experiment_id: str, ca: str = "", sample_type: str = "", stage: str = "") -> Dict[str, Any]:
        return {
            "experiment_id": experiment_id,
            "ca": ca,
            "sample_type": sample_type,
            "start_time": now_iso(),
            "end_time": "",
            "elapsed_ms": "",
            "success": "",
            "source": "",
            "depends_on_page": "",
            "stage": stage,
            "gate_valid": "",
            "blocked_reason": "",
            "result_strength": "",
            "url_hit": "",
            "path_hit": "",
            "display_hit": "",
            "field_group": "",
            "top10_value": "",
            "liq_value": "",
            "tag_count": "",
            "error_type": "",
            "notes": "",
        }

    async def run(self) -> None:
        exps = [e.strip().upper() for e in self.args.experiments.split(",") if e.strip()]
        avatar_cas = read_ca_file(self.args.ca_file)
        page_samples = read_page_samples(self.args.page_samples)
        for exp in exps:
            fn = getattr(self, f"run_{exp}", None)
            if not fn:
                print(f"[WARN] unsupported experiment: {exp}")
                continue
            if exp.startswith("A"):
                await fn(avatar_cas)
            else:
                await fn(page_samples or [{"ca": ca, "label": "built_token_url", "url": ""} for ca in avatar_cas])

    async def run_A1(self, cas: Sequence[str]) -> None:
        for i, ca in enumerate(cas, 1):
            row = self._base_row(f"A1-{i:03d}", ca, "avatar", "avatar_cache")
            t0 = time.perf_counter()
            try:
                path = self.fetcher._existing_avatar_path(ca)
                row.update({
                    "source": "stable_cache",
                    "depends_on_page": False,
                    "success": bool(path),
                    "path_hit": bool(path),
                    "display_hit": bool(path),
                    "notes": path or "cache_miss",
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e)})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_A2(self, cas: Sequence[str]) -> None:
        for i, ca in enumerate(cas, 1):
            row = self._base_row(f"A2-{i:03d}", ca, "avatar", "avatar_url")
            t0 = time.perf_counter()
            try:
                url, source = await self.fetcher._fetch_dex_avatar_url(ca)
                row.update({
                    "source": source or "dex",
                    "depends_on_page": False,
                    "success": bool(url),
                    "url_hit": bool(url),
                    "notes": url or "source_empty",
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e)})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_A3(self, cas: Sequence[str]) -> None:
        for i, ca in enumerate(cas, 1):
            row = self._base_row(f"A3-{i:03d}", ca, "avatar", "avatar_url")
            t0 = time.perf_counter()
            try:
                url, source = await self.fetcher._fetch_pump_avatar_url(ca)
                row.update({
                    "source": source or "pump",
                    "depends_on_page": False,
                    "success": bool(url),
                    "url_hit": bool(url),
                    "notes": url or "source_empty",
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e)})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_A4(self, cas: Sequence[str]) -> None:
        for i, ca in enumerate(cas, 1):
            row = self._base_row(f"A4-{i:03d}", ca, "avatar", "avatar_url")
            t0 = time.perf_counter()
            try:
                url, source = await self.fetcher._fetch_birdeye_avatar_url(ca)
                row.update({
                    "source": source or "birdeye",
                    "depends_on_page": False,
                    "success": bool(url),
                    "url_hit": bool(url),
                    "notes": url or "source_empty_or_rate_limited",
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e)})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_A5(self, cas: Sequence[str]) -> None:
        await self.ensure_browser_ready()
        for i, ca in enumerate(cas, 1):
            row = self._base_row(f"A5-{i:03d}", ca, "avatar", "avatar_url")
            t0 = time.perf_counter()
            try:
                url, source = await self.fetcher._fetch_warm_gmgn_avatar_url(ca)
                row.update({
                    "source": source or "gmgn/warm",
                    "depends_on_page": True,
                    "success": bool(url),
                    "url_hit": bool(url),
                    "notes": url or "source_empty_or_page_not_matching",
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e)})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_A6(self, cas: Sequence[str]) -> None:
        for i, ca in enumerate(cas, 1):
            row = self._base_row(f"A6-{i:03d}", ca, "avatar", "avatar_materialize")
            t0 = time.perf_counter()
            try:
                url, source = await self.fetcher._fetch_dex_avatar_url(ca)
                if not url:
                    url, source = await self.fetcher._fetch_pump_avatar_url(ca)
                if not url and self.args.include_birdeye_in_a6:
                    url, source = await self.fetcher._fetch_birdeye_avatar_url(ca)
                path = await self.fetcher.ensure_token_avatar(ca, url, source or "", fast_mode=False) if url else ""
                row.update({
                    "source": source or "none",
                    "depends_on_page": False,
                    "success": bool(path),
                    "url_hit": bool(url),
                    "path_hit": bool(path),
                    "display_hit": bool(path),
                    "notes": path or url or "source_empty",
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e)})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_A7(self, cas: Sequence[str]) -> None:
        budget = float(self.args.avatar_budget_ms) / 1000.0
        for i, ca in enumerate(cas, 1):
            row = self._base_row(f"A7-{i:03d}", ca, "avatar", "first_card_avatar")
            t0 = time.perf_counter()
            url = ""
            source = ""
            path = self.fetcher._existing_avatar_path(ca) or ""
            try:
                if not path:
                    async def _dex():
                        return await self.fetcher._fetch_dex_avatar_url(ca)

                    async def _pump():
                        return await self.fetcher._fetch_pump_avatar_url(ca)

                    tasks = [asyncio.create_task(_dex()), asyncio.create_task(_pump())]
                    done, pending = await asyncio.wait(tasks, timeout=budget, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        u, s = task.result()
                        if u:
                            url, source = u, s
                            break
                    if not url:
                        for task in tasks:
                            if task.done() and not task.cancelled():
                                try:
                                    u, s = task.result()
                                    if u:
                                        url, source = u, s
                                        break
                                except Exception:
                                    pass
                    for task in pending:
                        task.cancel()
                    remaining = max(0.0, budget - (time.perf_counter() - t0))
                    if url and remaining > 0.05:
                        path = await asyncio.wait_for(
                            self.fetcher.ensure_token_avatar(ca, url, source or "", fast_mode=True),
                            timeout=remaining,
                        ) or ""
                row.update({
                    "source": source or ("stable_cache" if path else "none"),
                    "depends_on_page": False,
                    "success": bool(path),
                    "url_hit": bool(url) or bool(path),
                    "path_hit": bool(path),
                    "display_hit": bool(path),
                    "notes": path or url or "budget_exhausted_or_no_source",
                })
            except asyncio.TimeoutError:
                row.update({
                    "success": bool(path),
                    "source": source or ("stable_cache" if path else "none"),
                    "url_hit": bool(url) or bool(path),
                    "path_hit": bool(path),
                    "display_hit": bool(path),
                    "error_type": "TimeoutError",
                    "notes": path or url or "budget_timeout",
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e)})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def _open_sample_url(self, sample: Dict[str, str]) -> Tuple[Any, str]:
        await self.ensure_browser_ready()
        tab = await asyncio.to_thread(self.fetcher._get_or_create_gmgn_tab)
        if not tab:
            raise RuntimeError("gmgn_tab_unavailable")
        url = sample.get("url") or ""
        ca = sample.get("ca") or ""
        if not url and ca:
            url = self.fetcher._build_gmgn_token_url(ca)
        if url and self.args.navigate_gmgn:
            await asyncio.to_thread(tab.get, url)
            await asyncio.sleep(float(self.args.navigate_settle_s))
        return tab, url

    async def run_B1(self, samples: Sequence[Dict[str, str]]) -> None:
        for i, sample in enumerate(samples, 1):
            ca = sample.get("ca", "")
            row = self._base_row(f"B1-{i:03d}", ca, sample.get("label", ""), "page_gate")
            t0 = time.perf_counter()
            try:
                tab, url = await self._open_sample_url(sample)
                gate = await asyncio.to_thread(self.fetcher._gmgn_page_gate_state, tab, ca)
                row.update({
                    "source": "page_gate",
                    "depends_on_page": True,
                    "success": bool(gate.get("valid")),
                    "gate_valid": bool(gate.get("valid")),
                    "blocked_reason": gate.get("blocked_reason", ""),
                    "result_strength": "full" if gate.get("valid") else "invalid",
                    "notes": sample.get("label", "") + (f" | url={url}" if url else ""),
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e), "depends_on_page": True, "source": "page_gate"})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_B2(self, samples: Sequence[Dict[str, str]]) -> None:
        timeout = float(self.args.target_timeout_s)
        for i, sample in enumerate(samples, 1):
            ca = sample.get("ca", "")
            row = self._base_row(f"B2-{i:03d}", ca, sample.get("label", ""), "page_target")
            t0 = time.perf_counter()
            try:
                tab, url = await self._open_sample_url(sample)
                trace: Dict[str, Any] = {}
                ok = await asyncio.to_thread(self.fetcher._wait_gmgn_target_page, tab, ca, timeout, 0.20, trace)
                row.update({
                    "source": "target_wait",
                    "depends_on_page": True,
                    "success": bool(ok),
                    "gate_valid": bool(ok),
                    "notes": f"url={url}",
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e), "source": "target_wait", "depends_on_page": True})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_B3(self, samples: Sequence[Dict[str, str]]) -> None:
        for i, sample in enumerate(samples, 1):
            ca = sample.get("ca", "")
            row = self._base_row(f"B3-{i:03d}", ca, sample.get("label", ""), "header_block")
            t0 = time.perf_counter()
            try:
                tab, _ = await self._open_sample_url(sample)
                gate = await asyncio.to_thread(self.fetcher._gmgn_page_gate_state, tab, ca)
                row.update({
                    "source": "header_block",
                    "depends_on_page": True,
                    "success": bool(gate.get("header_ready")),
                    "gate_valid": bool(gate.get("valid")),
                    "blocked_reason": gate.get("blocked_reason", ""),
                    "field_group": "header",
                    "notes": (gate.get("title_text") or "")[:120],
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e), "source": "header_block", "depends_on_page": True})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_B4(self, samples: Sequence[Dict[str, str]]) -> None:
        for i, sample in enumerate(samples, 1):
            ca = sample.get("ca", "")
            row = self._base_row(f"B4-{i:03d}", ca, sample.get("label", ""), "safety_block")
            t0 = time.perf_counter()
            try:
                result = await self.fetcher.fetch_gmgn_analytics(ca, mode=self.args.gmgn_mode, priority="normal")
                has_safety = any(result.get(k) is not None for k in ["is_burned", "is_locked", "mint_disabled", "freeze_disabled", "is_mint_disabled", "is_freeze_disabled"])  # tolerant
                row.update({
                    "source": "gmgn_reader",
                    "depends_on_page": True,
                    "success": bool(has_safety),
                    "blocked_reason": result.get("blocked_reason", ""),
                    "result_strength": result.get("result_strength", ""),
                    "field_group": "safety",
                    "notes": json.dumps({k: result.get(k) for k in ["is_burned", "is_locked", "is_mint_disabled", "is_freeze_disabled"]}, ensure_ascii=False),
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e), "source": "gmgn_reader", "depends_on_page": True})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_B5(self, samples: Sequence[Dict[str, str]]) -> None:
        for i, sample in enumerate(samples, 1):
            ca = sample.get("ca", "")
            row = self._base_row(f"B5-{i:03d}", ca, sample.get("label", ""), "top10_tags")
            t0 = time.perf_counter()
            try:
                result = await self.fetcher.fetch_gmgn_analytics(ca, mode=self.args.gmgn_mode, priority="normal")
                tags = result.get("holder_tags") or result.get("gmgn_tags") or result.get("tags") or []
                if isinstance(tags, str):
                    tags = [x.strip() for x in tags.split(",") if x.strip()]
                top10 = result.get("top10_ratio")
                liq = result.get("header_liq_usd")
                row.update({
                    "source": "gmgn_reader",
                    "depends_on_page": True,
                    "success": bool(top10 or tags),
                    "blocked_reason": result.get("blocked_reason", ""),
                    "result_strength": result.get("result_strength", ""),
                    "field_group": "top10_holder_tags",
                    "top10_value": top10,
                    "liq_value": liq,
                    "tag_count": len(tags) if isinstance(tags, list) else 0,
                    "notes": json.dumps(tags[:10] if isinstance(tags, list) else tags, ensure_ascii=False),
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e), "source": "gmgn_reader", "depends_on_page": True})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_B6(self, samples: Sequence[Dict[str, str]]) -> None:
        for i, sample in enumerate(samples, 1):
            ca = sample.get("ca", "")
            row = self._base_row(f"B6-{i:03d}", ca, sample.get("label", ""), "fast_reader")
            t0 = time.perf_counter()
            try:
                result = await self.fetcher.fetch_gmgn_analytics(ca, mode="fast", priority="normal")
                tags = result.get("holder_tags") or result.get("gmgn_tags") or result.get("tags") or []
                if isinstance(tags, str):
                    tags = [x.strip() for x in tags.split(",") if x.strip()]
                row.update({
                    "source": "gmgn_fast",
                    "depends_on_page": True,
                    "success": bool(result),
                    "blocked_reason": result.get("blocked_reason", ""),
                    "result_strength": result.get("result_strength", ""),
                    "field_group": "fast_reader",
                    "top10_value": result.get("top10_ratio"),
                    "liq_value": result.get("header_liq_usd"),
                    "tag_count": len(tags) if isinstance(tags, list) else 0,
                    "notes": sample.get("label", ""),
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e), "source": "gmgn_fast", "depends_on_page": True})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)

    async def run_B7(self, samples: Sequence[Dict[str, str]]) -> None:
        # Warm-vs-cold comparison scaffold. Use one fetcher without prepare, then warm fetcher with prepare.
        for i, sample in enumerate(samples, 1):
            ca = sample.get("ca", "")
            row = self._base_row(f"B7-{i:03d}", ca, sample.get("label", ""), "prewarm_benefit")
            t0 = time.perf_counter()
            cold_elapsed = None
            warm_elapsed = None
            cold_strength = ""
            warm_strength = ""
            try:
                cold_fetcher = DataFetcher(profile_dir=self.args.profile_dir) if self.args.profile_dir else DataFetcher()
                t1 = time.perf_counter()
                cold = await cold_fetcher.fetch_gmgn_analytics(ca, mode="fast", priority="normal")
                cold_elapsed = int((time.perf_counter() - t1) * 1000)
                cold_strength = str(cold.get("result_strength", ""))
                try:
                    sess = getattr(cold_fetcher, "_session", None)
                    if sess and not sess.closed:
                        await sess.close()
                except Exception:
                    pass

                warm_fetcher = DataFetcher(profile_dir=self.args.profile_dir) if self.args.profile_dir else DataFetcher()
                await warm_fetcher.prepare_browser_profile()
                t2 = time.perf_counter()
                warm = await warm_fetcher.fetch_gmgn_analytics(ca, mode="fast", priority="normal")
                warm_elapsed = int((time.perf_counter() - t2) * 1000)
                warm_strength = str(warm.get("result_strength", ""))
                try:
                    sess = getattr(warm_fetcher, "_session", None)
                    if sess and not sess.closed:
                        await sess.close()
                except Exception:
                    pass

                row.update({
                    "source": "prewarm_compare",
                    "depends_on_page": True,
                    "success": True,
                    "result_strength": f"cold={cold_strength};warm={warm_strength}",
                    "notes": f"cold_ms={cold_elapsed};warm_ms={warm_elapsed}",
                })
            except Exception as e:
                row.update({"success": False, "error_type": type(e).__name__, "notes": str(e), "source": "prewarm_compare", "depends_on_page": True})
            row["end_time"] = now_iso()
            row["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            self.record(**row)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Avatar + GMGN clean-room research runner")
    p.add_argument("--experiments", required=True, help="Comma-separated experiment IDs, e.g. A2,A3,A6,A7,B1,B6")
    p.add_argument("--ca-file", help="Text or CSV file with CA samples")
    p.add_argument("--page-samples", help="CSV file with columns: ca,label,url (url optional)")
    p.add_argument("--output-dir", default="research_output", help="Directory for CSV/JSONL outputs")
    p.add_argument("--profile-dir", default="data/browser_profile_research", help="Browser profile dir for GMGN research")
    p.add_argument("--navigate-gmgn", action="store_true", help="Open each page sample URL before B* experiments")
    p.add_argument("--navigate-settle-s", type=float, default=1.6, help="Sleep after navigation before gate/read")
    p.add_argument("--target-timeout-s", type=float, default=2.0, help="Timeout for B2 target-ready experiment")
    p.add_argument("--avatar-budget-ms", type=int, default=1000, help="Budget for A7 first-card avatar experiment")
    p.add_argument("--gmgn-mode", choices=["fast", "full"], default="full", help="Mode for B4/B5")
    p.add_argument("--include-birdeye-in-a6", action="store_true", help="Include BirdEye fallback in A6 URL->path experiment")
    return p.parse_args(argv)


async def amain(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    runner = ResearchRunner(args)
    try:
        await runner.run()
        print(f"[OK] results written to: {runner.recorder.output_csv}")
        print(f"[OK] jsonl written to: {runner.recorder.output_jsonl}")
        return 0
    finally:
        await runner.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
