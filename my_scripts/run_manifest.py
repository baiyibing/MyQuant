# -*- coding: utf-8 -*-
"""Run manifest (M4)：myquant.run-manifest/1 构建 / 校验 / 写盘。

三仓同格式契约，供 train / export / refresh 结果可追溯。schema 见
docs/run-manifest-spec.md（M4-C）。硬约束：JSON UTF-8 无 BOM。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_ID = "myquant.run-manifest/1"
ALLOWED_STAGES = frozenset({"train", "export", "refresh"})
class ManifestError(ValueError):
    """manifest 构建或校验失败。"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_stamp_for_filename(created_utc: str | None = None) -> str:
    """Flatten created_utc to YYYYMMDDTHHMMSSZ for filenames."""
    if not created_utc:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    text = created_utc.strip()
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    # 2026-09-13T01:02:03.123Z or 2026-09-13T01:02:03Z
    text = text.replace("-", "").replace(":", "")
    if "." in text:
        text = text.split(".", 1)[0]
        if not text.endswith("Z"):
            text += "Z"
    if not text.endswith("Z"):
        text += "Z"
    return text


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no extra whitespace, UTF-8 safe."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_hash(config: Mapping[str, Any]) -> str:
    """sha256 of canonical JSON over config **without** nested config_hash."""
    payload = {k: v for k, v in config.items() if k != "config_hash"}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return digest


def md5_file(path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def git_commit(repo_root: Path | str | None = None) -> str:
    """Best-effort HEAD sha; returns 'UNKNOWN' if git unavailable."""
    cwd = str(repo_root) if repo_root is not None else None
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "UNKNOWN"
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def capture_git_provenance(repo_root: Path | str | None = None) -> dict[str, Any]:
    """Capture HEAD / branch / dirty **once** at process start (before handler_init).

    Returns keys: ``git_commit`` (str | None), ``git_branch`` (str | None),
    ``git_dirty`` (bool). On git failure commit/branch are None and dirty is False.
    Callers must pass these into ``write_train_manifest`` so end-of-run no longer
    re-reads HEAD (mid-run branch switches would otherwise corrupt provenance).
    """
    cwd = str(repo_root) if repo_root is not None else None
    commit: str | None = None
    branch: str | None = None
    dirty = False
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        commit = out or None
    except (OSError, subprocess.CalledProcessError):
        commit = None
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        branch = out or None
    except (OSError, subprocess.CalledProcessError):
        branch = None
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        dirty = bool(out.strip())
    except (OSError, subprocess.CalledProcessError):
        dirty = False
    return {"git_commit": commit, "git_branch": branch, "git_dirty": dirty}


def fingerprint_artifact(
    path: Path | str,
    *,
    rows: int | None = None,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Build one artifacts[] entry: relative path, md5, optional rows."""
    p = Path(path)
    if not p.is_file():
        raise ManifestError(f"artifact not found: {p}")
    rel = p.name
    if base_dir is not None:
        try:
            rel = str(p.resolve().relative_to(Path(base_dir).resolve()))
        except ValueError:
            rel = str(p)
    entry: dict[str, Any] = {"path": rel.replace("\\", "/"), "md5": md5_file(p)}
    if rows is not None:
        entry["rows"] = int(rows)
    return entry


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
    """Build a myquant.run-manifest/1 dict (not yet validated beyond stage).

    Prefer passing ``git_commit_sha`` / ``git_branch`` / ``git_dirty`` from a
    startup ``capture_git_provenance`` call. When commit is omitted we still
    fall back to a live ``git rev-parse`` (legacy); new optional fields are
    only written when provided (no schema bump — additive).
    """
    if stage not in ALLOWED_STAGES:
        raise ManifestError(f"unsupported stage: {stage!r}; allow {sorted(ALLOWED_STAGES)}")

    cfg: dict[str, Any] = dict(config or {})
    cfg["config_hash"] = config_hash(cfg)

    manifest: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "stage": stage,
        "git_commit": git_commit_sha if git_commit_sha is not None else git_commit(repo_root),
        "created_utc": created_utc or _utc_now_iso(),
        "config": cfg,
        "data": dict(data or {}),
        "artifacts": [dict(a) for a in (artifacts or [])],
        "timings": dict(timings or {"total_seconds": 0, "nodes": []}),
    }
    if git_branch is not None:
        manifest["git_branch"] = git_branch
    if git_dirty is not None:
        manifest["git_dirty"] = bool(git_dirty)
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Reject bad schema / missing required fields / bad artifact entries."""
    if not isinstance(manifest, Mapping):
        raise ManifestError("manifest must be a mapping")
    schema = manifest.get("schema")
    if schema != SCHEMA_ID:
        raise ManifestError(f"bad schema: {schema!r}; expected {SCHEMA_ID!r}")
    stage = manifest.get("stage")
    if stage not in ALLOWED_STAGES:
        raise ManifestError(f"bad stage: {stage!r}")
    for key in ("git_commit", "created_utc", "config", "data", "artifacts", "timings"):
        if key not in manifest:
            raise ManifestError(f"missing field: {key}")
    cfg = manifest["config"]
    if not isinstance(cfg, Mapping):
        raise ManifestError("config must be a mapping")
    if "config_hash" not in cfg:
        raise ManifestError("config.config_hash required")
    expected = config_hash(cfg)
    if cfg["config_hash"] != expected:
        raise ManifestError(
            f"config_hash mismatch: got {cfg['config_hash']!r}, expected {expected!r}"
        )
    arts = manifest["artifacts"]
    if not isinstance(arts, list):
        raise ManifestError("artifacts must be a list")
    for i, art in enumerate(arts):
        if not isinstance(art, Mapping):
            raise ManifestError(f"artifacts[{i}] must be a mapping")
        if "path" not in art or "md5" not in art:
            raise ManifestError(f"artifacts[{i}] needs path and md5")
        md5 = art["md5"]
        if not isinstance(md5, str) or len(md5) != 32 or any(c not in "0123456789abcdef" for c in md5):
            raise ManifestError(f"artifacts[{i}].md5 must be 32-char lowercase hex")
        if "rows" in art and art["rows"] is not None:
            if not isinstance(art["rows"], int) or isinstance(art["rows"], bool):
                raise ManifestError(f"artifacts[{i}].rows must be int")
    timings = manifest["timings"]
    if not isinstance(timings, Mapping):
        raise ManifestError("timings must be a mapping")
    if "nodes" in timings and not isinstance(timings["nodes"], list):
        raise ManifestError("timings.nodes must be a list")


def manifest_to_json_bytes(manifest: Mapping[str, Any]) -> bytes:
    """UTF-8 JSON **without BOM**, pretty-printed for humans, trailing newline."""
    validate_manifest(manifest)
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    raw = text.encode("utf-8")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw


def write_manifest(
    manifest: Mapping[str, Any],
    *,
    manifests_dir: Path | str,
    artifact_dirs: Iterable[Path | str] | None = None,
    filename: str | None = None,
) -> list[Path]:
    """Write manifests/<stage>_<UTC>.json and optional copies beside artifacts.

    Returns list of paths written (primary first).
    """
    validate_manifest(manifest)
    stage = str(manifest["stage"])
    stamp = _utc_stamp_for_filename(str(manifest.get("created_utc") or ""))
    name = filename or f"{stage}_{stamp}.json"
    if not name.endswith(".json"):
        name = f"{name}.json"

    primary_dir = Path(manifests_dir)
    primary_dir.mkdir(parents=True, exist_ok=True)
    primary = primary_dir / name
    payload = manifest_to_json_bytes(manifest)
    primary.write_bytes(payload)

    written = [primary]
    for d in artifact_dirs or []:
        target_dir = Path(d)
        target_dir.mkdir(parents=True, exist_ok=True)
        copy_path = target_dir / name
        copy_path.write_bytes(payload)
        written.append(copy_path)
    return written


def load_manifest(path: Path | str) -> dict[str, Any]:
    """Load + validate a manifest JSON file."""
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ManifestError("manifest must be UTF-8 without BOM")
    data = json.loads(raw.decode("utf-8"))
    validate_manifest(data)
    return data


def timings_from_recorder(timer_recorder: Any) -> dict[str, Any]:
    """Snapshot TimerRecorder-like object into timings dict."""
    if timer_recorder is None:
        return {"total_seconds": 0, "nodes": []}
    nodes = list(getattr(timer_recorder, "nodes", []) or [])
    total = None
    dump_json = getattr(timer_recorder, "dump_json", None)
    # Prefer live total if recorder exposes _t0
    t0 = getattr(timer_recorder, "_t0", None)
    if t0 is not None:
        from timeit import default_timer as timer

        total = float(timer() - t0)
    if total is None:
        total = float(sum(float(n.get("seconds", 0)) for n in nodes if isinstance(n, Mapping)))
    return {"total_seconds": total, "nodes": nodes}


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
