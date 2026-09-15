# -*- coding: utf-8 -*-
"""M3-B: ranking-only config sweep harness (topk / n_drop / hold_thresh).

VM-safe: unit/smoke tests inject ``train_predict_fn`` returning IC/IR.
``--limit N`` truncates the grid so orchestration can be exercised without
handler_init (~18min). Real multi-config trains belong on the host.

阶段机（eng-perf P1-5）：``predict_extended|train → pred 产物 → export /
sweep --pred-from``。``--pred-from`` / ``--label-from`` 离线续跑；
``--pred-out`` 在 adapter INIT_ONCE 落盘。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# 共享 mlflow 逃生口 / 静音（adapter 路径会触碰 qlib）
import host_env  # noqa: E402,F401
from run_manifest import (  # noqa: E402
    unknown_timings,
    write_sweep_parent_manifest,
    write_train_manifest,
)

# Shared batch nodes belong on the sweep parent manifest (eng-perf P0-5), not
# re-amortized onto every arm as "full train" wall time.
_SHARED_TIMING_NODE_NAMES = frozenset(
    {
        "init_once",
        "handler_init",
        "predict_once",
        "preflight",
        "model_fit",
        "fit",
        "predict",
        "pred_from",
    }
)

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
    parent_shared_nodes: list[dict[str, Any]] = field(default_factory=list)
    # INIT_ONCE payload wall clock (not sum of alias node labels).
    parent_shared_wall_seconds: float | None = None


def parse_int_list(text: str) -> list[int]:
    """Parse '5,10,20' or '5 10' into ints."""
    if text is None:
        return []
    parts = [p.strip() for p in str(text).replace(" ", ",").split(",") if p.strip()]
    return [int(p) for p in parts]


def parse_date_range(text: str) -> tuple[str, str]:
    """Parse ``START:END`` (ISO dates). Illegal format raises ValueError.

    Used as argparse ``type=`` so a bad token exits the CLI (argparse
    converts ValueError → usage error).
    """
    if text is None:
        raise ValueError("empty date range; expected START:END")
    raw = str(text).strip()
    if raw.count(":") != 1:
        raise ValueError(f"illegal segment format {text!r}; expected START:END")
    start, end = (part.strip() for part in raw.split(":", 1))
    if not start or not end:
        raise ValueError(f"illegal segment format {text!r}; expected START:END")
    try:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError(
            f"illegal segment dates {text!r}; expected YYYY-MM-DD:YYYY-MM-DD"
        ) from exc
    if d0 > d1:
        raise ValueError(f"segment start > end: {text!r}")
    return start, end


def maybe_segments_from_args(args: argparse.Namespace) -> dict[str, tuple[str, str]] | None:
    """Return provided --train/--valid/--test windows, or None if none given.

    Windows are a run-level dimension — never a SweepConfig / grid field.
    """
    out: dict[str, tuple[str, str]] = {}
    if getattr(args, "train", None) is not None:
        out["train"] = args.train
    if getattr(args, "valid", None) is not None:
        out["valid"] = args.valid
    if getattr(args, "test", None) is not None:
        out["test"] = args.test
    return out or None


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



def new_sweep_parent_id() -> str:
    """UTC stamp + short uuid — stable for filenames and arm parent_id refs."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def split_shared_and_exclusive_timings(
    timings: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Split payload timings into parent-owned shared nodes vs arm-exclusive.

    Unknown timings stay unknown on the arm (``total_seconds: null``); never
    rewrite missing timing as a fake zero-second full train.
    """
    if timings is None:
        return [], unknown_timings()
    payload = dict(timings)
    if payload.get("unknown"):
        out = dict(payload)
        out.setdefault("nodes", [])
        if out.get("total_seconds") == 0:
            out["total_seconds"] = None
        return [], out

    nodes = list(payload.get("nodes") or [])
    shared: list[dict[str, Any]] = []
    exclusive: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        entry = dict(node)
        name = entry.get("name")
        if name in _SHARED_TIMING_NODE_NAMES:
            shared.append(entry)
        else:
            exclusive.append(entry)

    if exclusive:
        total = float(sum(float(n.get("seconds") or 0) for n in exclusive))
        arm_timings: dict[str, Any] = {"total_seconds": total, "nodes": exclusive}
    elif shared:
        # Shared work lived on parent; arm exclusive is genuinely empty (not unknown).
        arm_timings = {
            "total_seconds": 0.0,
            "nodes": [{"name": "arm_only", "seconds": 0.0}],
        }
    else:
        # No named nodes — keep caller total if present, else unknown.
        if "total_seconds" in payload and payload["total_seconds"] is not None:
            arm_timings = {
                "total_seconds": float(payload["total_seconds"]),
                "nodes": [],
            }
        else:
            arm_timings = unknown_timings()
    return shared, arm_timings


def run_one(
    config: SweepConfig,
    *,
    train_predict_fn: TrainPredictFn,
    manifests_dir: Path | str | None = None,
    repo_root: Path | str | None = None,
    write_manifests: bool = True,
    parent_id: str | None = None,
) -> SweepResult:
    """Run one config via injectable train/predict; optionally write train manifest.

    When ``parent_id`` is set (batch sweep), shared timing nodes are peeled onto
    the parent and the arm manifest only keeps exclusive work + a parent ref.
    """
    cfg = config.with_id()
    payload = dict(train_predict_fn(cfg))
    ic, ir = _require_metrics(payload)

    data: dict[str, Any] = (
        dict(payload["data"]) if isinstance(payload.get("data"), Mapping) else {}
    )
    if parent_id:
        data["parent_id"] = parent_id

    raw_timings = payload.get("timings") if isinstance(payload.get("timings"), Mapping) else None
    parent_shared_nodes: list[dict[str, Any]] = []
    if parent_id:
        parent_shared_nodes, timings = split_shared_and_exclusive_timings(raw_timings)
    elif raw_timings is None:
        # 缺 timings 时禁止默写 total_seconds:0（假零秒）；标 unknown 待 adapter 必给
        timings = unknown_timings()
    else:
        timings = dict(raw_timings)

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

        pred_path = payload.get("pred_path")
        pred_rows = payload.get("pred_rows")

        written = write_train_manifest(
            manifests_dir=manifests_dir,
            config=man_cfg,
            pred_path=pred_path if pred_path else None,
            timings=timings,
            data=data or {},
            repo_root=repo_root,
            git_commit_sha=payload.get("git_commit"),
            git_branch=payload.get("git_branch"),
            git_dirty=payload.get("git_dirty"),
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
    extra = {
        k: v
        for k, v in payload.items()
        if k
        not in {
            "ic",
            "ir",
            "config",
            "data",
            "timings",
            "pred_path",
            "pred_md5",
            "pred_rows",
            "git_commit",
            "git_branch",
            "git_dirty",
            "created_utc",
            "notes",
        }
    }
    # Stash segments / cache key for parent aggregation (not written into arm extra dump).
    if isinstance(payload.get("config"), Mapping):
        segs = payload["config"].get("segments")
        if segs is not None:
            extra["_segments"] = segs
    if data.get("shared_handler_cache_key") is not None:
        extra["_shared_handler_cache_key"] = data.get("shared_handler_cache_key")
    if data.get("arm_mode") is not None:
        extra["_arm_mode"] = data.get("arm_mode")
    parent_wall: float | None = None
    if parent_shared_nodes and raw_timings is not None:
        raw_total = raw_timings.get("total_seconds")
        if raw_total is not None:
            parent_wall = float(raw_total)

    return SweepResult(
        config=cfg,
        ic=ic,
        ir=ir,
        manifest_path=manifest_path,
        notes=notes,
        extra=extra,
        parent_shared_nodes=parent_shared_nodes,
        parent_shared_wall_seconds=parent_wall,
    )


def run_sweep(
    configs: Sequence[SweepConfig],
    *,
    train_predict_fn: TrainPredictFn,
    manifests_dir: Path | str | None = None,
    repo_root: Path | str | None = None,
    write_manifests: bool = True,
) -> list[SweepResult]:
    """Execute sweep over configs; write parent shared-timings manifest (P0-5).

    Generates one ``parent_id`` per batch. Arms reference it; shared init/predict
    nodes land on ``manifests/sweep_parent_<id>.json``. Skipped when
    ``write_manifests=False``.
    """
    parent_id = new_sweep_parent_id()
    results: list[SweepResult] = []
    for cfg in configs:
        results.append(
            run_one(
                cfg,
                train_predict_fn=train_predict_fn,
                manifests_dir=manifests_dir,
                repo_root=repo_root,
                write_manifests=write_manifests,
                parent_id=parent_id if write_manifests else None,
            )
        )

    if write_manifests and manifests_dir is not None:
        shared_nodes: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        cache_key: str | None = None
        segments: Any = None
        arm_ids: list[dict[str, Any]] = []
        parent_wall: float | None = None
        git_commit = None
        git_branch = None
        git_dirty = None
        for r in results:
            for node in r.parent_shared_nodes:
                name = node.get("name")
                if name in seen_names:
                    continue
                seen_names.add(str(name))
                shared_nodes.append(dict(node))
            if parent_wall is None and r.parent_shared_wall_seconds is not None:
                # First arm with shared work supplies the batch wall clock
                # (INIT_ONCE payload total_seconds). Do not sum alias labels
                # like handler_init + init_once — they name the same elapsed.
                parent_wall = float(r.parent_shared_wall_seconds)
            if cache_key is None and r.extra.get("_shared_handler_cache_key") is not None:
                cache_key = r.extra.get("_shared_handler_cache_key")
            if segments is None and r.extra.get("_segments") is not None:
                segments = r.extra.get("_segments")
            arm_ids.append(
                {
                    "grid_id": r.config.grid_id,
                    "manifest_path": r.manifest_path or "",
                    "arm_mode": r.extra.get("_arm_mode"),
                }
            )

        if shared_nodes:
            if parent_wall is not None:
                total = float(parent_wall)
            else:
                # No payload total: take max, never sum (aliases share one clock).
                total = float(max(float(n.get("seconds") or 0) for n in shared_nodes))
            parent_timings: dict[str, Any] = {
                "total_seconds": total,
                "nodes": shared_nodes,
            }
        else:
            parent_timings = unknown_timings()

        write_sweep_parent_manifest(
            manifests_dir=manifests_dir,
            parent_id=parent_id,
            shared_handler_cache_key=cache_key,
            arm_ids=arm_ids,
            timings=parent_timings,
            segments=segments if isinstance(segments, Mapping) else None,
            repo_root=repo_root,
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
    p.add_argument(
        "--train",
        default=None,
        type=parse_date_range,
        metavar="START:END",
        help="Train window YYYY-MM-DD:YYYY-MM-DD (default: adapter March window)",
    )
    p.add_argument(
        "--valid",
        default=None,
        type=parse_date_range,
        metavar="START:END",
        help="Valid window YYYY-MM-DD:YYYY-MM-DD (default: adapter March window)",
    )
    p.add_argument(
        "--test",
        default=None,
        type=parse_date_range,
        metavar="START:END",
        help="Test window YYYY-MM-DD:YYYY-MM-DD (default: adapter March window)",
    )
    p.add_argument(
        "--pred-from",
        default=None,
        dest="pred_from",
        metavar="PATH",
        help=(
            "Offline continuation: load pred CSV/pkl (export_daily_pool contract) "
            "and skip adapter handler_init/fit/predict (eng-perf P1-5). "
            "Requires --label-from (or pred.label.csv sidecar) for IC/IR."
        ),
    )
    p.add_argument(
        "--label-from",
        default=None,
        dest="label_from",
        metavar="PATH",
        help="Label CSV/pkl aligned to --pred-from (required for offline IC/IR).",
    )
    p.add_argument(
        "--pred-out",
        default=None,
        dest="pred_out",
        metavar="PATH",
        help=(
            "On adapter INIT_ONCE, atomically write pred (+label sidecar + meta) "
            "for later --pred-from handoff (opt-in; default live path unchanged)."
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

    user_segs = maybe_segments_from_args(args)

    if args.pred_from and not args.adapter:
        # Offline pred handoff needs adapter simulate_list + configure_pred_handoff.
        args.adapter = "sweep_live_adapter"

    if args.adapter:
        import importlib

        module = importlib.import_module(args.adapter)
        train_fn: TrainPredictFn = getattr(module, "train_predict_fn")
        # 窗口是运行维度：仅用户给了任一段才调 adapter.set_segments；
        # 缺省不调用，adapter 用模块常量三月窗。--dry-run-fake 不走此分支。
        if user_segs is not None:
            defaults = dict(getattr(module, "SEGMENTS", {}) or {})
            full = {}
            for key in ("train", "valid", "test"):
                if key in user_segs:
                    full[key] = user_segs[key]
                elif key in defaults:
                    val = defaults[key]
                    full[key] = (str(val[0]), str(val[1]))
            getattr(module, "set_segments")(full)
        if args.pred_from or args.label_from or args.pred_out:
            configure = getattr(module, "configure_pred_handoff", None)
            if configure is None:
                raise SystemExit(
                    f"adapter {args.adapter!r} lacks configure_pred_handoff "
                    "(needed for --pred-from / --label-from / --pred-out)"
                )
            configure(
                pred_from=args.pred_from,
                label_from=args.label_from,
                pred_out=args.pred_out,
            )
    elif args.dry_run_fake or args.limit is not None:
        # --limit alone still needs a callable on VM: default to fake when limit set.
        # fake 不走 adapter，即使传了 --train/--valid/--test 也不调 set_segments。
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
