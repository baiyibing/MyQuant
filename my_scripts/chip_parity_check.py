# -*- coding: utf-8 -*-
"""M2-B: chip quantity parity checker (MyQuant vs MyQuant-backtrader).

Map-first: if docs/chip-parity-map.md concludes 不可比, live compare against
the real BT tree reports that clearly and exits 0 (does not fake equality).

Harness mode: inject a fake ``bt_chip`` module (or --bt-values-json) to prove
agree → exit 0 / disagree → exit 1 under relative tolerance.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Defaults (plan §3 M2-B; Linux BT path overrides host E:\...)
# ---------------------------------------------------------------------------

DEFAULT_BT_REPO = os.environ.get(
    "MYQUANT_BT_REPO", "/workspace/MyQuant-backtrader"
)
DEFAULT_WINDOW_START = "2026-03-02"
DEFAULT_WINDOW_END = "2026-03-23"
DEFAULT_SYMBOLS: Tuple[str, ...] = (
    "600000",
    "300190",
    "920014",  # BJ
    "000001",
    "000858",
    "601318",
    "688981",
    "301236",
)
DEFAULT_RTOL = 1e-4
MAP_MARKER = "MAPPING_CONCLUSION="
INCOMPARABLE_TOKENS = ("不可比", "incomparable", "not_comparable")

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP_PATH = _REPO_ROOT / "docs" / "chip-parity-map.md"


@dataclass
class QuantityPair:
    """One named quantity on both sides for a (symbol, date) cell."""

    name: str
    myquant: float
    bt: float


@dataclass
class CompareReport:
    comparable: bool
    mapping_conclusion: str
    rtol: float
    agreements: List[str] = field(default_factory=list)
    disagreements: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if not self.comparable:
            return True  # not-comparable is a legal soft pass
        return len(self.disagreements) == 0


def parse_mapping_conclusion(map_text: str) -> str:
    """Extract MAPPING_CONCLUSION value from chip-parity-map.md body."""
    for line in map_text.splitlines():
        if MAP_MARKER in line:
            raw = line.split(MAP_MARKER, 1)[1]
            # strip markdown wrappers then take first token-like run
            raw = raw.strip().strip("*").strip("`").strip()
            raw = re.split(r"[\s`*）)\]]", raw, maxsplit=1)[0]
            raw = raw.strip("`").strip("*").strip()
            return raw
    raise ValueError(
        f"chip-parity-map.md missing '{MAP_MARKER}<value>' marker"
    )


def is_incomparable(conclusion: str) -> bool:
    c = (conclusion or "").strip().lower()
    for tok in INCOMPARABLE_TOKENS:
        if tok.lower() in c:
            return True
    return False


def load_mapping_conclusion(map_path: Path | str) -> str:
    text = Path(map_path).read_text(encoding="utf-8")
    return parse_mapping_conclusion(text)


def relative_diff(a: float, b: float) -> float:
    """Relative |a-b| / max(|a|,|b|,eps). NaN/inf → +inf."""
    if not (math.isfinite(a) and math.isfinite(b)):
        return float("inf")
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom


def values_agree(a: float, b: float, rtol: float = DEFAULT_RTOL) -> bool:
    return relative_diff(a, b) <= rtol


def compare_quantity_maps(
    myquant: Mapping[str, float],
    bt: Mapping[str, float],
    rtol: float = DEFAULT_RTOL,
    *,
    comparable: bool = True,
    mapping_conclusion: str = "可比",
) -> CompareReport:
    """Compare flat name→value maps. Missing keys on either side are skipped."""
    report = CompareReport(
        comparable=comparable,
        mapping_conclusion=mapping_conclusion,
        rtol=rtol,
    )
    if not comparable:
        report.notes.append(
            "mapping concludes not comparable (不可比); "
            "skipping numerical equality against real BT"
        )
        return report

    keys = sorted(set(myquant) | set(bt))
    if not keys:
        report.notes.append("no quantities to compare")
        return report

    for k in keys:
        if k not in myquant:
            report.skipped.append(f"{k}: missing on MyQuant side")
            continue
        if k not in bt:
            report.skipped.append(f"{k}: missing on BT side")
            continue
        mq_v = float(myquant[k])
        bt_v = float(bt[k])
        diff = relative_diff(mq_v, bt_v)
        detail = f"{k}: mq={mq_v!r} bt={bt_v!r} rel_diff={diff:.6g} (rtol={rtol})"
        if diff <= rtol:
            report.agreements.append(detail)
        else:
            report.disagreements.append(detail)
    return report


def format_report(report: CompareReport) -> str:
    lines = [
        f"mapping_conclusion={report.mapping_conclusion}",
        f"comparable={report.comparable}",
        f"rtol={report.rtol}",
        f"agreements={len(report.agreements)}",
        f"disagreements={len(report.disagreements)}",
        f"skipped={len(report.skipped)}",
        f"ok={report.ok}",
    ]
    for n in report.notes:
        lines.append(f"note: {n}")
    for d in report.disagreements:
        lines.append(f"DISAGREE: {d}")
    for a in report.agreements:
        lines.append(f"AGREE: {a}")
    for s in report.skipped:
        lines.append(f"SKIP: {s}")
    return "\n".join(lines) + "\n"


def load_values_json(path: Path | str) -> Dict[str, float]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("values JSON must be an object of name→number")
    return {str(k): float(v) for k, v in data.items()}


def try_import_bt_chip(bt_repo: Path | str, inject: Any = None) -> Any:
    """Return a module exposing ``compute_chip_values(symbols, start, end) -> dict``.

    ``inject`` short-circuits import (unit tests). Real BT has no stable
    public chip export API aligned with MyQuant; live path should not fake it.
    """
    if inject is not None:
        return inject
    bt_repo = Path(bt_repo)
    # Placeholder discovery only — real mapping is 不可比; do not invent adapters.
    marker = bt_repo / "qlib_cost" / "cyq.py"
    if not marker.is_file():
        raise FileNotFoundError(f"BT chip module not found under {bt_repo}")
    return None  # signal: tree present but no comparable adapter


def compute_live_bt_values(
    bt_repo: Path | str,
    symbols: Sequence[str],
    start: str,
    end: str,
    inject: Any = None,
) -> Optional[Dict[str, float]]:
    """If inject provides compute_chip_values, call it; else return None (incomparable)."""
    mod = try_import_bt_chip(bt_repo, inject=inject)
    if mod is None:
        return None
    fn = getattr(mod, "compute_chip_values", None)
    if fn is None:
        return None
    return dict(fn(list(symbols), start, end))


def run_check(
    *,
    map_path: Path | str = DEFAULT_MAP_PATH,
    bt_repo: Path | str = DEFAULT_BT_REPO,
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    start: str = DEFAULT_WINDOW_START,
    end: str = DEFAULT_WINDOW_END,
    rtol: float = DEFAULT_RTOL,
    myquant_values: Optional[Mapping[str, float]] = None,
    bt_values: Optional[Mapping[str, float]] = None,
    bt_inject: Any = None,
    force_compare: bool = False,
) -> CompareReport:
    """Core entry used by CLI and unit tests."""
    conclusion = load_mapping_conclusion(map_path)
    incomparable = is_incomparable(conclusion)

    if incomparable and not force_compare and bt_values is None and bt_inject is None:
        return CompareReport(
            comparable=False,
            mapping_conclusion=conclusion,
            rtol=rtol,
            notes=[
                f"live golden window {start}..{end} symbols={list(symbols)}",
                f"bt_repo={bt_repo}",
                "not comparable — refusing to assert numerical equality vs real BT",
            ],
        )

    mq = dict(myquant_values or {})
    bt: Dict[str, float] = dict(bt_values or {})

    if not bt and bt_inject is not None:
        live = compute_live_bt_values(
            bt_repo, symbols, start, end, inject=bt_inject
        )
        if live is not None:
            bt = live

    # Harness: if force_compare / injected values present, treat as comparable for the run
    comparable = True
    if incomparable and bt_values is None and bt_inject is None and not force_compare:
        comparable = False

    # When only inject/fixture values are supplied, we are testing the harness
    if bt_values is not None or bt_inject is not None:
        comparable = True

    if not mq and not bt and incomparable:
        return CompareReport(
            comparable=False,
            mapping_conclusion=conclusion,
            rtol=rtol,
            notes=["not comparable; no fixture values supplied"],
        )

    return compare_quantity_maps(
        mq,
        bt,
        rtol=rtol,
        comparable=comparable,
        mapping_conclusion=conclusion,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="M2-B chip parity checker (map-first; 不可比 is a legal exit 0)"
    )
    p.add_argument(
        "--bt-repo",
        default=DEFAULT_BT_REPO,
        help=f"MyQuant-backtrader root (default: {DEFAULT_BT_REPO})",
    )
    p.add_argument(
        "--map",
        dest="map_path",
        default=str(DEFAULT_MAP_PATH),
        help="path to chip-parity-map.md",
    )
    p.add_argument("--start", default=DEFAULT_WINDOW_START)
    p.add_argument("--end", default=DEFAULT_WINDOW_END)
    p.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="comma-separated bare codes (default: fixed 8)",
    )
    p.add_argument(
        "--rtol",
        type=float,
        default=DEFAULT_RTOL,
        help=f"relative tolerance (default {DEFAULT_RTOL})",
    )
    p.add_argument(
        "--myquant-values-json",
        default=None,
        help="fixture JSON object name→float (MyQuant side)",
    )
    p.add_argument(
        "--bt-values-json",
        default=None,
        help="fixture JSON object name→float (BT side); enables harness compare",
    )
    p.add_argument(
        "--force-compare",
        action="store_true",
        help="attempt numerical compare even if map says 不可比 (needs fixtures)",
    )
    p.add_argument(
        "--report-out",
        default=None,
        help="optional path to write text report",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    mq_vals = (
        load_values_json(args.myquant_values_json)
        if args.myquant_values_json
        else None
    )
    bt_vals = (
        load_values_json(args.bt_values_json) if args.bt_values_json else None
    )

    report = run_check(
        map_path=args.map_path,
        bt_repo=args.bt_repo,
        symbols=symbols,
        start=args.start,
        end=args.end,
        rtol=args.rtol,
        myquant_values=mq_vals,
        bt_values=bt_vals,
        force_compare=args.force_compare,
    )
    text = format_report(report)
    sys.stdout.write(text)
    if args.report_out:
        Path(args.report_out).write_text(text, encoding="utf-8")

    if not report.comparable:
        # Legal soft pass for 不可比
        return 0
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
