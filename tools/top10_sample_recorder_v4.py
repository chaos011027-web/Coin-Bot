import argparse
import csv
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional


BITQUERY_RATIO_RE = re.compile(
    r"BitqueryTop10Trace \| mint=(?P<ca>[A-Za-z0-9]+) \| ratio=(?P<ratio>[0-9.]+).*?top10_sum=(?P<top10_sum>[0-9.]+)"
)
BITQUERY_TOP1_RE = re.compile(
    r"BitqueryTop10Trace \| mint=(?P<ca>[A-Za-z0-9]+) \| top1=(?P<top1>[0-9.]+) \| holders_count=(?P<count>\d+)"
)
SELFCALC_RE = re.compile(
    r"Top10SelfCalcTrace \| mint=(?P<ca>[A-Za-z0-9]+) \| raw=(?P<raw>[0-9.]+|None) \| owner=(?P<owner>[0-9.]+|None) \| effective=(?P<effective>[0-9.]+|None) \| raw_n=(?P<raw_n>\d+|None) \| owner_n=(?P<owner_n>\d+|None) \| effective_n=(?P<effective_n>\d+|None) \| excluded=(?P<excluded>\d+|None) \| insuff=(?P<insuff>.*)$"
)
LATE_GMGN_DECISION_RE = re.compile(
    r"LateGMGNDecision \| ca=(?P<ca>[A-Za-z0-9]+) \| rerun=(?P<rerun>true|false) \| old_top10=(?P<old>[0-9.]+|None) \| new_top10=(?P<new>[0-9.]+|None) \| old_action=(?P<old_action>[A-Z]+|None) \| new_action=(?P<new_action>[A-Z]+|None)"
)
LATE_GMGN_REASON_RE = re.compile(
    r"LateGMGNDecision \| ca=(?P<ca>[A-Za-z0-9]+) \| reason=(?P<reason>[A-Za-z0-9_]+)"
)
GROUP_HIT_RE = re.compile(
    r"群命中CA:\s*(?P<ca>[A-Za-z0-9]+)\s*\|.*?msg=(?P<msg>\d+)"
)
TOP10_TEXT_RE = re.compile(r"前十持仓[:：]\s*(?P<pct>[0-9.]+)%")
MESSAGE_RE = re.compile(r"^Message:\s*(?P<msg>.*)$")


def to_float(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    x = str(x).strip()
    if x in {"", "None", "none", "null"}:
        return None
    try:
        return float(x)
    except Exception:
        return None


def to_int(x: Optional[str]) -> Optional[int]:
    if x is None:
        return None
    x = str(x).strip()
    if x in {"", "None", "none", "null"}:
        return None
    try:
        return int(x)
    except Exception:
        return None


def read_text_auto(path: Path) -> str:
    data = path.read_bytes()

    # BOM detection
    if data.startswith(b"\xff\xfe"):
        text = data.decode("utf-16-le", errors="ignore")
    elif data.startswith(b"\xfe\xff"):
        text = data.decode("utf-16-be", errors="ignore")
    elif data.startswith(b"\xef\xbb\xbf"):
        text = data.decode("utf-8-sig", errors="ignore")
    else:
        # Heuristic for UTF-16 without BOM
        if len(data) >= 4 and data[1:2] == b"\x00":
            text = data.decode("utf-16-le", errors="ignore")
        else:
            text = data.decode("utf-8", errors="ignore")

    # Remove embedded NULs if any
    text = text.replace("\x00", "")
    return text


@dataclass
class Sample:
    ca: str
    bitquery_ratio: Optional[float] = None
    bitquery_top10_sum: Optional[float] = None
    bitquery_top1: Optional[float] = None
    bitquery_holders_count: Optional[int] = None

    top10_raw_pct_self: Optional[float] = None
    top10_owner_pct_self: Optional[float] = None
    top10_effective_pct_self: Optional[float] = None
    top10_raw_n_self: Optional[int] = None
    top10_owner_n_self: Optional[int] = None
    top10_effective_n_self: Optional[int] = None
    top10_excluded_n_self: Optional[int] = None
    top10_exclusion_summary_self: str = ""

    late_gmgn_old_top10: Optional[float] = None
    late_gmgn_new_top10: Optional[float] = None
    late_gmgn_old_action: str = ""
    late_gmgn_new_action: str = ""
    late_gmgn_reasons: str = ""

    source_group_top10_pct: Optional[float] = None

    def to_row(self):
        return asdict(self)


def get_sample(samples: Dict[str, Sample], ca: str) -> Sample:
    if ca not in samples:
        samples[ca] = Sample(ca=ca)
    return samples[ca]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--json", required=True)
    args = ap.parse_args()

    log_path = Path(args.log)
    csv_path = Path(args.csv)
    json_path = Path(args.json)

    text = read_text_auto(log_path)
    lines = text.splitlines()

    samples: Dict[str, Sample] = {}
    group_top10_map: Dict[str, float] = {}

    for line in lines:
        m = BITQUERY_RATIO_RE.search(line)
        if m:
            s = get_sample(samples, m.group("ca"))
            s.bitquery_ratio = to_float(m.group("ratio"))
            s.bitquery_top10_sum = to_float(m.group("top10_sum"))
            continue

        m = BITQUERY_TOP1_RE.search(line)
        if m:
            s = get_sample(samples, m.group("ca"))
            s.bitquery_top1 = to_float(m.group("top1"))
            s.bitquery_holders_count = to_int(m.group("count"))
            continue

        m = SELFCALC_RE.search(line)
        if m:
            s = get_sample(samples, m.group("ca"))
            s.top10_raw_pct_self = to_float(m.group("raw"))
            s.top10_owner_pct_self = to_float(m.group("owner"))
            s.top10_effective_pct_self = to_float(m.group("effective"))
            s.top10_raw_n_self = to_int(m.group("raw_n"))
            s.top10_owner_n_self = to_int(m.group("owner_n"))
            s.top10_effective_n_self = to_int(m.group("effective_n"))
            s.top10_excluded_n_self = to_int(m.group("excluded"))
            s.top10_exclusion_summary_self = (m.group("insuff") or "").strip()
            continue

        m = LATE_GMGN_DECISION_RE.search(line)
        if m:
            s = get_sample(samples, m.group("ca"))
            s.late_gmgn_old_top10 = to_float(m.group("old"))
            s.late_gmgn_new_top10 = to_float(m.group("new"))
            s.late_gmgn_old_action = m.group("old_action")
            s.late_gmgn_new_action = m.group("new_action")
            continue

        m = LATE_GMGN_REASON_RE.search(line)
        if m:
            s = get_sample(samples, m.group("ca"))
            reason = m.group("reason")
            if s.late_gmgn_reasons:
                old = set(filter(None, s.late_gmgn_reasons.split(",")))
                old.add(reason)
                s.late_gmgn_reasons = ",".join(sorted(old))
            else:
                s.late_gmgn_reasons = reason
            continue

        m = MESSAGE_RE.search(line)
        if m:
            msg_text = m.group("msg")

            hm = GROUP_HIT_RE.search(msg_text)
            if hm:
                ca = hm.group("ca")
                get_sample(samples, ca)
                tm = TOP10_TEXT_RE.search(msg_text)
                if tm:
                    group_top10_map[ca] = to_float(tm.group("pct"))
                continue

            tm = TOP10_TEXT_RE.search(msg_text)
            if tm:
                # only top10 text without CA: ignore for now
                continue

    for ca, pct in group_top10_map.items():
        s = get_sample(samples, ca)
        s.source_group_top10_pct = pct

    rows = [samples[k].to_row() for k in sorted(samples.keys())]

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        else:
            f.write("")

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print(f"[OK] parsed samples: {len(rows)}")
    print(f"[OK] csv  -> {csv_path}")
    print(f"[OK] json -> {json_path}")


if __name__ == "__main__":
    main()