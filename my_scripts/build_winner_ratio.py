"""MQ entry point for the optional myquant-infra CYQ winner-ratio feeder.

Use explicit --provider-uri and --out (or --output-root). The old home
provider and implicit lake destination are no longer selected here. See
../docs/engineering/c3-cyq-winner-ratio-infra-switch-20261105.md.

The frozen computation and replace-via-temp publication live only in infra.
Importing this module or requesting --help requires only the standard library.
"""

from __future__ import annotations

import argparse
from importlib import import_module
import sys

_PACKAGE = "myquant_infra.derived_data.cyq"
_INSTALL_HINT = (
    "C3 CYQ requires the optional requirements-infra.txt pin; "
    "install it with python -m pip install -r requirements-infra.txt. "
    "Local provider reads also require MQ's separately installed source-pinned qlib."
)
_EXPORTS = {
    "FeederConfig": "",
    "compute_winner_ratio": ".feeder",
    "run": ".feeder",
    "NoOutputError": ".feeder",
    "_snap_test_window": ".feeder",
    "_triang_into": "._kernel",
    "_stock_winner_ratio_impl": "._kernel",
    "_make_jit": "._kernel",
    "_work_one": "._kernel",
    "_work_one_state": "._kernel",
    "_MAX_GRID": "._kernel",
}


class InstallError(ModuleNotFoundError):
    """The optional C3 feeder is unavailable in this environment."""


def _backend(suffix):
    try:
        return import_module(_PACKAGE + suffix)
    except ModuleNotFoundError as exc:
        if (exc.name or "").startswith("myquant_infra"):
            raise InstallError(_INSTALL_HINT, name=exc.name) from exc
        raise


def __getattr__(name):
    """Forward compatibility names on use, without retaining a host kernel."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(_backend(_EXPORTS[name]), name)


def build_parser():
    # Mirror the pinned infra CLI so public help does not need private infra.
    # Parity is checked against cyq.cli.build_parser when infra is available.
    parser = argparse.ArgumentParser(description="Build external daily CYQ winner-ratio parquet")
    parser.add_argument("--provider-uri", required=True, help="explicit local daily qlib provider")
    parser.add_argument("--test", required=True, help="inclusive capture window START:END")
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--output-root", help="parquet container; retain cyq_winner_ratio/2026 filename")
    output.add_argument("--out", help="explicit parquet filename, replacing the default name")
    parser.add_argument("--window", type=int, default=1000, help="trading days before first capture")
    parser.add_argument("--step", type=float, default=0.01)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--kernels", type=int, default=1, help="qlib feature workers; no environment override")
    parser.add_argument("--shares", choices=("free", "circ"), default="free")
    parser.add_argument("--codes", default="", help="comma-separated qlib codes; empty uses market=all")
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    build_parser().parse_args(argv)
    try:
        return _backend(".cli").main(argv)
    except InstallError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    raise SystemExit(main())
