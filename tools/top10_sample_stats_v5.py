import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional


def to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if s in {"", "None", "null"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def safe_mean(values: List[float]) -> Optional[float]:
    return round(mean(values), 4) if values else None


def safe_median(values: List[float]) -> Optional[float]:
    return round(median(values), 4) if values else None


def safe_min(values: List[float]) -> Optional[float]:
    return round(min(values), 4) if values else None


def safe_max(values: List[float]) -> Optional[float]:
    return round(max(values), 4) if values else None


def load_rows(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, list):
        return data
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="Input top10_samples_v4.json")
    ap.add_argument("--summary-json", required=True, help="Output summary json")
    ap.add_argument("--summary-csv", required=True, help="Output suspicious sample csv")
    args = ap.parse_args()

    rows = load_rows(Path(args.json))

    total = len(rows)

    gap_bq_vs_eff: List[float] = []
    gap_bq_vs_gmgn: List[float] = []
    gap_eff_vs_gmgn: List[float] = []

    suspicious_rows: List[Dict[str, Any]] = []

    bq_holders_eq_1 = 0
    raw_eq_owner_count = 0
    effective_present_count = 0
    gmgn_present_count = 0

    for row in rows:
        ca = str(row.get("ca") or "").strip()

        bq = to_float(row.get("bitquery_ratio"))
        raw_self = to_float(row.get("top10_raw_pct_self"))
        owner_self = to_float(row.get("top10_owner_pct_self"))
        eff_self = to_float(row.get("top10_effective_pct_self"))
        gmgn_new = to_float(row.get("late_gmgn_new_top10"))
        holders_count = row.get("bitquery_holders_count")
        excluded_n = row.get("top10_excluded_n_self")
        reasons = str(row.get("late_gmgn_reasons") or "")

        if str(holders_count).strip() == "1":
            bq_holders_eq_1 += 1

        if raw_self is not None and owner_self is not None and abs(raw_self - owner_self) < 1e-9:
            raw_eq_owner_count += 1

        if eff_self is not None:
            effective_present_count += 1

        if gmgn_new is not None:
            gmgn_present_count += 1

        if bq is not None and eff_self is not None:
            gap_bq_vs_eff.append(round(bq - eff_self, 4))

        if bq is not None and gmgn_new is not None:
            gap_bq_vs_gmgn.append(round(bq - gmgn_new, 4))

        if eff_self is not None and gmgn_new is not None:
            gap_eff_vs_gmgn.append(round(abs(eff_self - gmgn_new), 4))

        suspect = False
        suspect_reasons: List[str] = []

        if bq is not None and bq >= 80:
            suspect = True
            suspect_reasons.append("bitquery_ge_80")

        if str(holders_count).strip() == "1":
            suspect = True
            suspect_reasons.append("holders_count_eq_1")

        if bq is not None and eff_self is not None and (bq - eff_self) >= 20:
            suspect = True
            suspect_reasons.append("bitquery_minus_effective_ge_20")

        if eff_self is not None and gmgn_new is not None and abs(eff_self - gmgn_new) <= 5:
            suspect_reasons.append("effective_close_to_late_gmgn")

        if suspect:
            suspicious_rows.append(
                {
                    "ca": ca,
                    "bitquery_ratio": bq,
                    "top10_raw_pct_self": raw_self,
                    "top10_owner_pct_self": owner_self,
                    "top10_effective_pct_self": eff_self,
                    "late_gmgn_new_top10": gmgn_new,
                    "bitquery_holders_count": holders_count,
                    "top10_excluded_n_self": excluded_n,
                    "late_gmgn_reasons": reasons,
                    "suspect_reasons": ",".join(suspect_reasons),
                    "gap_bitquery_vs_effective": round(bq - eff_self, 4) if (bq is not None and eff_self is not None) else None,
                    "gap_bitquery_vs_late_gmgn": round(bq - gmgn_new, 4) if (bq is not None and gmgn_new is not None) else None,
                    "gap_effective_vs_late_gmgn_abs": round(abs(eff_self - gmgn_new), 4) if (eff_self is not None and gmgn_new is not None) else None,
                }
            )

    suspicious_rows.sort(
        key=lambda r: (
            -(r["gap_bitquery_vs_effective"] if r["gap_bitquery_vs_effective"] is not None else -9999),
            -(r["bitquery_ratio"] if r["bitquery_ratio"] is not None else -9999),
        )
    )

    summary = {
        "total_samples": total,
        "bitquery_holders_count_eq_1": bq_holders_eq_1,
        "raw_eq_owner_count": raw_eq_owner_count,
        "effective_present_count": effective_present_count,
        "late_gmgn_present_count": gmgn_present_count,
        "suspicious_sample_count": len(suspicious_rows),
        "gap_bitquery_vs_effective": {
            "count": len(gap_bq_vs_eff),
            "mean": safe_mean(gap_bq_vs_eff),
            "median": safe_median(gap_bq_vs_eff),
            "min": safe_min(gap_bq_vs_eff),
            "max": safe_max(gap_bq_vs_eff),
        },
        "gap_bitquery_vs_late_gmgn": {
            "count": len(gap_bq_vs_gmgn),
            "mean": safe_mean(gap_bq_vs_gmgn),
            "median": safe_median(gap_bq_vs_gmgn),
            "min": safe_min(gap_bq_vs_gmgn),
            "max": safe_max(gap_bq_vs_gmgn),
        },
        "gap_effective_vs_late_gmgn_abs": {
            "count": len(gap_eff_vs_gmgn),
            "mean": safe_mean(gap_eff_vs_gmgn),
            "median": safe_median(gap_eff_vs_gmgn),
            "min": safe_min(gap_eff_vs_gmgn),
            "max": safe_max(gap_eff_vs_gmgn),
        },
        "top_10_suspicious_samples": suspicious_rows[:10],
    }

    summary_json_path = Path(args.summary_json)
    summary_csv_path = Path(args.summary_csv)
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_csv_path.parent.mkdir(parents=True, exist_ok=True)

    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if suspicious_rows:
        with summary_csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(suspicious_rows[0].keys()))
            writer.writeheader()
            writer.writerows(suspicious_rows)
    else:
        summary_csv_path.write_text("", encoding="utf-8")

    print(f"[OK] total_samples={total}")
    print(f"[OK] suspicious_sample_count={len(suspicious_rows)}")
    print(f"[OK] summary_json -> {summary_json_path}")
    print(f"[OK] summary_csv  -> {summary_csv_path}")


if __name__ == "__main__":
    main()