# -*- coding: utf-8 -*-
"""MQ call-site compatibility for shared ``myquant.run-manifest/1`` provenance.

Infra owns canonical JSON, hashes, fingerprints, validation and manifest IO.
MQ keeps recorder snapshots and train/export/sweep metadata assembly only;
these helpers never start training or select signals. Imports work without
infra; feature use requires the optional ``requirements-infra.txt`` pin.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_ID = "myquant.run-manifest/1"
ALLOWED_STAGES = frozenset({"train", "export", "refresh", "sweep_parent"})
_PACKAGE = "myquant_infra.artifacts.provenance"
_REPO_ROOT = Path(__file__).resolve().parents[1]


class ManifestError(ValueError):
    """Host-compatible error for shared manifest construction or validation."""


def _infra():
    try:
        return import_module(_PACKAGE)
    except ModuleNotFoundError as exc:
        if exc.name and (_PACKAGE == exc.name or _PACKAGE.startswith(exc.name + ".")):
            raise ModuleNotFoundError(
                "Run manifest operations require the optional myquant-infra pin; "
                "install it with python -m pip install -r requirements-infra.txt",
                name=exc.name,
            ) from exc
        raise


def _call(name: str, *args: Any, **kwargs: Any) -> Any:
    backend = _infra()
    try:
        return getattr(backend, name)(*args, **kwargs)
    except backend.ManifestError as exc:
        # Preserve callers' imported exception class without importing infra
        # on help/import surfaces. All validation still executes in infra.
        raise ManifestError(str(exc)) from exc


def _repo_root(repo_root: Path | str | None) -> Path | str:
    # Legacy omitted roots mean this MQ checkout, independent of process cwd.
    # Infra itself always receives an explicit source repository.
    return _REPO_ROOT if repo_root is None else repo_root


def canonical_json(obj: Any) -> str:
    """Shared v1 sorted compact UTF-8 JSON, with no trailing LF."""
    return _call("canonical_json", obj)


def config_hash(config: Mapping[str, Any]) -> str:
    """Shared v1 config digest, excluding only the top-level config_hash."""
    return _call("config_hash", config)


def md5_file(path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    return _call("md5_file", path, chunk_size=chunk_size)


def git_commit(repo_root: Path | str | None = None) -> str:
    """Capture explicit-source HEAD; default to the host checkout, never cwd."""
    return _call("git_commit", _repo_root(repo_root))


def capture_git_provenance(repo_root: Path | str | None = None) -> dict[str, Any]:
    """Snapshot source git metadata once; pass it to end-of-run helpers."""
    return _call("capture_git_provenance", _repo_root(repo_root))


def fingerprint_artifact(
    path: Path | str,
    *,
    rows: int | None = None,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    return _call("fingerprint_artifact", path, rows=rows, base_dir=base_dir)


def build_manifest(
    *,
    stage: str,
    config: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    artifacts: Sequence[Mapping[str, Any]] | None = None,
    timings: Mapping[str, Any] | None = None,
    git_commit_sha: str | None = None,
    git_branch: str | None = None,
    git_dirty: bool | None = None,
    created_utc: str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build shared v1 provenance with an explicit source repository."""
    return _call(
        "build_manifest",
        stage=stage, config=config, data=data, artifacts=artifacts, timings=timings,
        git_commit_sha=git_commit_sha, git_branch=git_branch, git_dirty=git_dirty,
        created_utc=created_utc, repo_root=_repo_root(repo_root),
    )


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    return _call("validate_manifest", manifest)


def manifest_to_json_bytes(manifest: Mapping[str, Any]) -> bytes:
    """Shared pretty UTF-8 MQ JSON, without BOM and with a trailing LF."""
    return _call("manifest_to_json_bytes", manifest)


def write_manifest(
    manifest: Mapping[str, Any],
    *,
    manifests_dir: Path | str,
    artifact_dirs: Iterable[Path | str] | None = None,
    filename: str | None = None,
) -> list[Path]:
    return _call(
        "write_manifest", manifest, manifests_dir=manifests_dir,
        artifact_dirs=artifact_dirs, filename=filename,
    )


def load_manifest(path: Path | str) -> dict[str, Any]:
    return _call("load_manifest", path)


def unknown_timings() -> dict[str, Any]:
    return _call("unknown_timings")


def timings_from_recorder(timer_recorder: Any) -> dict[str, Any]:
    """Snapshot TimerRecorder-like object into timings dict."""
    if timer_recorder is None:
        return {"total_seconds": 0, "nodes": []}
    nodes = list(getattr(timer_recorder, "nodes", []) or [])
    total = None
    # Prefer live total if recorder exposes _t0
    t0 = getattr(timer_recorder, "_t0", None)
    if t0 is not None:
        from timeit import default_timer as timer

        total = float(timer() - t0)
    if total is None:
        total = float(sum(float(n.get("seconds", 0)) for n in nodes if isinstance(n, Mapping)))
    payload = {"total_seconds": total, "nodes": nodes}
    rollup = getattr(timer_recorder, "rollup", None)
    if callable(rollup):
        try:
            payload["rollup"] = list(rollup())
        except Exception:
            pass
    counters = getattr(timer_recorder, "counters", None)
    if isinstance(counters, Mapping):
        payload["counters"] = dict(counters)
    return payload


def write_train_manifest(
    *,
    manifests_dir: Path | str,
    config: Mapping[str, Any],
    pred_path: Path | str | None = None,
    timer_recorder: Any = None,
    timings: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    extra_artifacts: Sequence[Mapping[str, Any]] | None = None,
    artifact_dirs: Iterable[Path | str] | None = None,
    repo_root: Path | str | None = None,
    git_commit_sha: str | None = None,
    git_branch: str | None = None,
    git_dirty: bool | None = None,
    created_utc: str | None = None,
    pred_rows: int | None = None,
) -> list[Path]:
    """Train-stage helper: fingerprint pred (+extras), attach timings, write manifest.

    Callable from custom_train_backtest end-of-run and from unit tests without
    running handler_init / full train. Pass startup ``capture_git_provenance``
    fields so ``git_commit`` means process-start HEAD.
    """
    artifacts: list[dict[str, Any]] = []
    side_dirs: list[Path] = []
    if pred_path is not None:
        pred = Path(pred_path)
        if pred.is_file():
            base = pred.parent
            artifacts.append(fingerprint_artifact(pred, rows=pred_rows, base_dir=base))
            side_dirs.append(base)
    for art in extra_artifacts or []:
        artifacts.append(dict(art))
    for d in artifact_dirs or []:
        side_dirs.append(Path(d))

    timing_payload = dict(timings) if timings is not None else timings_from_recorder(timer_recorder)
    manifest = build_manifest(
        stage="train",
        config=config,
        data=data,
        artifacts=artifacts,
        timings=timing_payload,
        git_commit_sha=git_commit_sha,
        git_branch=git_branch,
        git_dirty=git_dirty,
        created_utc=created_utc,
        repo_root=repo_root,
    )
    return write_manifest(
        manifest,
        manifests_dir=manifests_dir,
        artifact_dirs=side_dirs,
    )


def write_export_manifest(
    *,
    manifests_dir: Path | str,
    config: Mapping[str, Any],
    pred_path: Path | str | None = None,
    out_dir: Path | str | None = None,
    output_file_count: int | None = None,
    timings: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    artifact_dirs: Iterable[Path | str] | None = None,
    repo_root: Path | str | None = None,
    git_commit_sha: str | None = None,
    created_utc: str | None = None,
    pred_rows: int | None = None,
) -> list[Path]:
    """Export-stage helper: pred md5, asof/topk in config, output file count."""
    artifacts: list[dict[str, Any]] = []
    side_dirs: list[Path] = []
    cfg = dict(config)
    if output_file_count is not None:
        cfg.setdefault("output_file_count", int(output_file_count))
    if pred_path is not None:
        pred = Path(pred_path)
        if pred.is_file():
            artifacts.append(fingerprint_artifact(pred, rows=pred_rows, base_dir=pred.parent))
            side_dirs.append(pred.parent)
    if out_dir is not None:
        side_dirs.append(Path(out_dir))
    for d in artifact_dirs or []:
        side_dirs.append(Path(d))

    manifest = build_manifest(
        stage="export",
        config=cfg,
        data=data,
        artifacts=artifacts,
        timings=timings or {"total_seconds": 0, "nodes": []},
        git_commit_sha=git_commit_sha,
        created_utc=created_utc,
        repo_root=repo_root,
    )
    return write_manifest(
        manifest,
        manifests_dir=manifests_dir,
        artifact_dirs=side_dirs,
    )


def write_sweep_parent_manifest(
    *,
    manifests_dir: Path | str,
    parent_id: str,
    shared_handler_cache_key: str | None = None,
    arm_ids: Sequence[Mapping[str, Any]] | None = None,
    timings: Mapping[str, Any] | None = None,
    segments: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    artifact_dirs: Iterable[Path | str] | None = None,
    repo_root: Path | str | None = None,
    git_commit_sha: str | None = None,
    git_branch: str | None = None,
    git_dirty: bool | None = None,
    created_utc: str | None = None,
) -> list[Path]:
    """Write manifests/sweep_parent_<parent_id>.json (eng-perf P0-5).

    Parent owns shared batch timings (init_once / predict_once / …). Arms only
    record exclusive work and reference ``parent_id``. Missing timings must use
    ``unknown_timings()`` — never ``total_seconds: 0`` as a stand-in for unknown.
    """
    if not parent_id or not str(parent_id).strip():
        raise ManifestError("parent_id required")
    pid = str(parent_id).strip()

    cfg: dict[str, Any] = dict(config or {})
    cfg.setdefault("stage_kind", "ranking_sweep_parent")
    cfg["parent_id"] = pid
    if segments is not None:
        cfg["segments"] = dict(segments)

    data_payload: dict[str, Any] = dict(data or {})
    data_payload["parent_id"] = pid
    if shared_handler_cache_key is not None:
        data_payload["shared_handler_cache_key"] = shared_handler_cache_key
    data_payload["arm_ids"] = [dict(a) for a in (arm_ids or [])]

    if timings is None:
        timing_payload: dict[str, Any] = unknown_timings()
    else:
        timing_payload = dict(timings)
        if timing_payload.get("unknown") and timing_payload.get("total_seconds") == 0:
            # harden: unknown must not look like a real zero-second run
            timing_payload["total_seconds"] = None

    manifest = build_manifest(
        stage="sweep_parent",
        config=cfg,
        data=data_payload,
        artifacts=[],
        timings=timing_payload,
        git_commit_sha=git_commit_sha,
        git_branch=git_branch,
        git_dirty=git_dirty,
        created_utc=created_utc,
        repo_root=repo_root,
    )
    filename = f"sweep_parent_{pid}.json"
    return write_manifest(
        manifest,
        manifests_dir=manifests_dir,
        artifact_dirs=artifact_dirs,
        filename=filename,
    )
