# -*- coding: utf-8 -*-
"""M3-B: ranking-only config sweep harness (topk / n_drop / hold_thresh).

VM-safe: unit/smoke tests inject ``train_predict_fn`` returning IC/IR.
``--limit N`` truncates the grid so orchestration can be exercised without
handler_init (~18min). Real multi-config trains belong on the host.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from run_manifest import write_train_manifest  # noqa: E402

TrainPredictFn = Callable[["SweepConfig"], Mapping[str, Any]]


@dataclass(frozen=True)
class SweepConfig:
    """One cell in the ranking sweep grid."""

    topk: int
    n_drop: int
    hold_thresh: int
    grid_id: str = ""

    def with_id(self) -> "SweepConfig":
        gid = self.grid_id or f"topk{self.topk}_ndrop{self.n_drop}_hold{self.hold_thresh}"
        return SweepConfig(
            topk=self.topk,
            n_drop=self.n_drop,
            hold_thresh=self.hold_thresh,
            grid_id=gid,
        )

    def as_manifest_config(self) -> dict[str, Any]:
        cfg = self.with_id()
        return {
            "stage_kind": "ranking_sweep",
            "grid_id": cfg.grid_id,
            "topk": cfg.topk,
            "n_drop": cfg.n_drop,
            "hold_thresh": cfg.hold_thresh,
        }


@dataclass
class SweepResult:
    config: SweepConfig
    ic: float
    ir: float
    manifest_path: Optional[str] = None
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def parse_int_list(text: str) -> list[int]:
    """Parse '5,10,20' or '5 10' into ints."""
    if text is None:
        return []
    parts = [p.strip() for p in str(text).replace(" ", ",").split(",") if p.strip()]
    return [int(p) for p in parts]


def iter_config_grid(
    topks: Sequence[int],
    n_drops: Sequence[int],
    hold_thresholds: Sequence[int],
    *,
    limit: Optional[int] = None,
) -> list[SweepConfig]:
    """Cartesian product of ranking knobs; optional ``limit`` keeps first N."""
    if not topks or not n_drops or not hold_thresholds:
        raise ValueError("topks, n_drops, and hold_thresholds must be non-empty")
    configs: list[SweepConfig] = []
    for t in topks:
        for n in n_drops:
            for h in hold_thresholds:
                configs.append(
                    SweepConfig(topk=int(t), n_drop=int(n), hold_thresh=int(h)).with_id()
                )
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        configs = configs[: int(limit)]
    return configs


def _require_metrics(payload: Mapping[str, Any]) -> tuple[float, float]:
    if "ic" not in payload or "ir" not in payload:
        raise ValueError("train_predict_fn must return mapping with 'ic' and 'ir'")
    return float(payload["ic"]), float(payload["ir"])


def run_one(
    config: SweepConfig,
    *,
    train_predict_fn: TrainPredictFn,
    manifests_dir: Path | str | None = None,
    repo_root: Path | str | None = None,
    write_manifests: bool = True,
) -> SweepResult:
    """Run one config via injectable train/predict; optionally write train manifest."""
    cfg = config.with_id()
    payload = dict(train_predict_fn(cfg))
    ic, ir = _require_metrics(payload)

    manifest_path: Optional[str] = None
    if write_manifests and manifests_dir is not None:
        man_cfg = cfg.as_manifest_config()
        # Allow caller to enrich config (segments, exp_name, …)
        extra_cfg = payload.get("config")
        if isinstance(extra_cfg, Mapping):
            man_cfg.update(dict(extra_cfg))
            man_cfg.setdefault("topk", cfg.topk)
            man_cfg.setdefault("n_drop", cfg.n_drop)
            man_cfg.setdefault("hold_thresh", cfg.hold_thresh)
            man_cfg.setdefault("grid_id", cfg.grid_id)

        data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
        timings = payload.get("timings") if isinstance(payload.get("timings"), Mapping) else None
        pred_path = payload.get("pred_path")
        pred_rows = payload.get("pred_rows")

        written = write_train_manifest(
            manifests_dir=manifests_dir,
            config=man_cfg,
            pred_path=pred_path if pred_path else None,
            timings=timings or {"total_seconds": 0, "nodes": []},
            data=data or {},
            repo_root=repo_root,
            git_commit_sha=payload.get("git_commit"),
            created_utc=payload.get("created_utc"),
            pred_rows=int(pred_rows) if pred_rows is not None else None,
        )
        # Also stamp a sweep-specific filename copy for easy indexing
        stamp_name = f"train_sweep_{cfg.grid_id}.json"
        primary = Path(written[0])
        alias = Path(manifests_dir) / stamp_name
        if primary.resolve() != alias.resolve():
            alias.write_bytes(primary.read_bytes())
            manifest_path = str(alias)
        else:
            manifest_path = str(primary)

    notes = str(payload.get("notes") or "")
    extra = {k: v for k, v in payload.items() if k not in {"ic", "ir", "config", "data", "timings", "pred_path", "pred_rows", "git_commit", "created_utc", "notes"}}
    return SweepResult(
        config=cfg,
        ic=ic,
        ir=ir,
        manifest_path=manifest_path,
        notes=notes,
        extra=extra,
    )


def run_sweep(
    configs: Sequence[SweepConfig],
    *,
    train_predict_fn: TrainPredictFn,
    manifests_dir: Path | str | None = None,
    repo_root: Path | str | None = None,
    write_manifests: bool = True,
) -> list[SweepResult]:
    """Execute sweep over configs with injectable train/predict."""
    results: list[SweepResult] = []
    for cfg in configs:
        results.append(
            run_one(
                cfg,
                train_predict_fn=train_predict_fn,
                manifests_dir=manifests_dir,
                repo_root=repo_root,
                write_manifests=write_manifests,
            )
        )
    return results


def summarize_ic_ir(results: Sequence[SweepResult]) -> pd.DataFrame:
    """Build IC/IR summary table (one row per config)."""
    rows = []
    for r in results:
        rows.append(
            {
                "grid_id": r.config.grid_id,
                "topk": r.config.topk,
                "n_drop": r.config.n_drop,
                "hold_thresh": r.config.hold_thresh,
                "ic": r.ic,
                "ir": r.ir,
                "manifest_path": r.manifest_path or "",
                "notes": r.notes,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["ic", "ir"], ascending=False).reset_index(drop=True)
    return df


def write_summary_table(
    df: pd.DataFrame,
    out_dir: Path | str,
    *,
    stem: str = "sweep_summary",
) -> dict[str, Path]:
    """Write CSV + markdown summary under out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / f"{stem}.csv"
    md_path = out / f"{stem}.md"
    df.to_csv(csv_path, index=False, lineterminator="\n")
    # Markdown table
    if df.empty:
        md_body = "_empty sweep_\n"
    else:
        headers = list(df.columns)
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for _, row in df.iterrows():
            cells = []
            for h in headers:
                val = row[h]
                if isinstance(val, float):
                    cells.append(f"{val:.6g}")
                else:
                    cells.append(str(val))
            lines.append("| " + " | ".join(cells) + " |")
        md_body = "\n".join(lines) + "\n"
    md_path.write_text(md_body, encoding="utf-8")
    return {"csv": csv_path, "md": md_path}


def default_live_train_predict(config: SweepConfig) -> Mapping[str, Any]:
    """Placeholder live hook — raises so VM never accidentally starts 18min trains.

    Host should inject a real callable that wraps custom_train_backtest knobs
    (or a subprocess) and returns ic/ir + optional pred_path.
    """
    raise RuntimeError(
        "live train_predict_fn is not wired on this VM (handler_init ~18min). "
        "Inject a mock for tests / --limit smoke, or pass --train-predict-module "
        "on the host. Config="
        f"{config.with_id().grid_id}"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="M3-B ranking sweep harness (topk/n_drop/hold_thresh → IC/IR)"
    )
    p.add_argument("--topk", default="10", help="Comma-separated topk grid, e.g. 5,10,20")
    p.add_argument("--n-drop", default="3", dest="n_drop", help="Comma-separated n_drop grid")
    p.add_argument(
        "--hold",
        default="1",
        dest="hold",
        help="Comma-separated hold_thresh (min hold days) grid",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Debug: only first N configs (smoke without full handler_init)",
    )
    p.add_argument(
        "--out-dir",
        default="sweep_out",
        help="Directory for summary table + per-config manifests",
    )
    p.add_argument(
        "--dry-run-fake",
        action="store_true",
        help="Use built-in deterministic fake train_predict (IC/IR from grid hash); VM smoke",
    )
    p.add_argument(
        "--no-manifests",
        action="store_true",
        help="Skip writing per-config train manifests",
    )
    p.add_argument(
        "--adapter",
        default=None,
        help=(
            "Host live adapter module (e.g. sweep_live_adapter): imports it and "
            "uses its train_predict_fn(config)->{ic,ir}. Real grids cost one "
            "handler_init (~18min) total; the adapter caches pred/label per process."
        ),
    )
    return p


def _fake_train_predict(config: SweepConfig) -> Mapping[str, Any]:
    """Deterministic fake metrics for --dry-run-fake / unit tests."""
    # Stable pseudo IC/IR from knobs (not a model claim).
    ic = 0.01 * config.topk - 0.002 * config.n_drop + 0.001 * config.hold_thresh
    ir = ic * 10.0 - 0.05 * config.n_drop
    return {
        "ic": float(ic),
        "ir": float(ir),
        "notes": "fake",
        "timings": {"total_seconds": 0, "nodes": [{"name": "fake", "seconds": 0}]},
        "data": {},
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    topks = parse_int_list(args.topk)
    n_drops = parse_int_list(args.n_drop)
    holds = parse_int_list(args.hold)
    configs = iter_config_grid(topks, n_drops, holds, limit=args.limit)

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir
    manifests_dir = out_dir / "manifests"

    if args.adapter:
        import importlib

        module = importlib.import_module(args.adapter)
        train_fn: TrainPredictFn = getattr(module, "train_predict_fn")
    elif args.dry_run_fake or args.limit is not None:
        # --limit alone still needs a callable on VM: default to fake when limit set.
        train_fn = _fake_train_predict
    else:
        train_fn = default_live_train_predict

    results = run_sweep(
        configs,
        train_predict_fn=train_fn,
        manifests_dir=None if args.no_manifests else manifests_dir,
        repo_root=repo_root,
        write_manifests=not args.no_manifests,
    )
    summary = summarize_ic_ir(results)
    paths = write_summary_table(summary, out_dir)
    print(f"configs={len(configs)} summary_csv={paths['csv']} summary_md={paths['md']}")
    if not summary.empty:
        print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
