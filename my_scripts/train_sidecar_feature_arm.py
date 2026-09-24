# -*- coding: utf-8 -*-
"""T5-DSTR1 B-gate: clone 8a061ea4 LGB, left-join DOWNSTREAK5_RANK only, train, export preds."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import host_env  # noqa: F401

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
REPO_ROOT = SCRIPT_DIR.parent

FEATURE = "DOWNSTREAK5_RANK"
CLONE_RECORDER = "8a061ea428e04bb3a199a485ade49d0e"
EXPERIMENT = "alpha158_cost_kdj_lgb"
DEFAULT_HANDLER_PKL = Path(r"D:\qlib_handler_cache\handler_86d82e09280b20b8.pkl")
DEFAULT_PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"
EPS = 1e-12


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _key_digest(df) -> str:
    keys = (df["instrument"].astype(str) + "|" + df["datetime"].dt.strftime("%Y-%m-%d")).sort_values(
        kind="mergesort"
    )
    h = hashlib.sha256()
    for k in keys:
        h.update(k.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def fail(msg: str, code: int = 2) -> int:
    print(f"[FAIL] {msg}", flush=True)
    return code


def parse_seg(s: str) -> tuple[str, str]:
    a, b = s.split(":", 1)
    return a.strip(), b.strip()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True).strip()
    except Exception as exc:
        return f"unavailable:{exc}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Train sidecar feature arm (DOWNSTREAK5_RANK)")
    p.add_argument("--clone-recorder", default=CLONE_RECORDER)
    p.add_argument("--experiment", default=EXPERIMENT)
    p.add_argument("--sidecar", type=Path, required=True)
    p.add_argument("--sidecar-sha256", required=True)
    p.add_argument("--verify-key-digest", action="store_true")
    p.add_argument("--only-extra-feature", default=FEATURE)
    p.add_argument("--handler-pkl", type=Path, default=DEFAULT_HANDLER_PKL)
    p.add_argument("--provider-uri", default=DEFAULT_PROVIDER)
    p.add_argument("--train", default="2020-01-01:2024-12-31")
    p.add_argument("--valid", default="2025-01-01:2025-12-31")
    p.add_argument("--test", default="2026-01-01:2026-09-14")
    p.add_argument("--no-portana", action="store_true", default=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--fail-if-out-exists", action="store_true")
    p.add_argument("--num-threads", type=int, default=20)
    return p


def inject_feature(handler, feat_s, train_start: str, train_end: str, feature: str) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    qc: dict[str, Any] = {}
    for attr in ("_infer", "_learn"):
        df = getattr(handler, attr)
        if df is None:
            raise RuntimeError(f"handler.{attr} is None")
        aligned = feat_s.reindex(df.index)
        qc[f"{attr}_align_rate"] = float(aligned.notna().mean())
        dt = df.index.get_level_values("datetime")
        mask = (dt >= pd.Timestamp(train_start)) & (dt <= pd.Timestamp(train_end))
        train_vals = aligned.loc[mask].to_numpy(dtype=float)
        med = float(np.nanmedian(train_vals))
        mad = float(np.nanmedian(np.abs(train_vals - med)))
        std = (mad + EPS) * 1.4826
        z = (aligned.to_numpy(dtype=float) - med) / std
        z = np.clip(z, -3.0, 3.0)
        z = np.where(np.isfinite(z), z, 0.0)
        col = ("feature", feature)
        existing = []
        for c in df.columns:
            name = c[-1] if isinstance(c, tuple) else c
            existing.append(str(name))
        banned = {
            "downstreak5",
            "upstreak5",
            "upstreak",
            "cum_down",
            "missing_dstr",
            "CNTN5",
            "ROC5",
            "SUMN5",
            "neg_bitmap",
        }
        hit = [x for x in existing if x in banned or x == feature]
        if feature in existing:
            raise RuntimeError(f"{feature} already present in {attr}")
        if hit:
            raise RuntimeError(f"refusing extra columns already in {attr}: {hit}")
        df = df.copy()
        df[col] = z
        feat_cols = [c for c in df.columns if c[0] == "feature"]
        other = [c for c in df.columns if c[0] != "feature"]
        setattr(handler, attr, df[feat_cols + other])
        qc[f"{attr}_median"] = med
        qc[f"{attr}_mad"] = mad
        qc[f"{attr}_std"] = std
        qc[f"{attr}_n_feat"] = len(feat_cols)
    return qc


def pred_to_frame(pred):
    import pandas as pd

    if isinstance(pred, pd.Series):
        df = pred.rename("score").to_frame()
    else:
        df = pred.copy()
        if "score" not in df.columns:
            df = df.iloc[:, [0]].copy()
            df.columns = ["score"]
    df = df.reset_index()
    rename = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl in ("datetime", "date") and c != "datetime":
            rename[c] = "datetime"
        elif cl in ("instrument", "asset", "symbol") and c != "instrument":
            rename[c] = "instrument"
    df = df.rename(columns=rename)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df[["datetime", "instrument", "score"]]


def main(argv=None) -> int:
    import pandas as pd
    import qlib
    from qlib.constant import REG_CN
    from qlib.data.dataset import DatasetH
    from qlib.utils import init_instance_by_config
    from qlib.workflow import R

    from custom_handler import Alpha158CostKDJ
    from train_wiring import build_fit_kwargs, build_model_task

    args = build_parser().parse_args(argv)
    out: Path = args.out_dir.expanduser().resolve()
    if args.fail_if_out_exists and out.exists():
        return fail(f"out-dir exists (fail-closed): {out}")
    out.mkdir(parents=True, exist_ok=False)

    sidecar: Path = args.sidecar.expanduser().resolve()
    if not sidecar.is_file():
        return fail(f"sidecar missing: {sidecar}")
    got = sha256_file(sidecar)
    if got.lower() != args.sidecar_sha256.lower():
        return fail(f"sidecar sha256 mismatch: got={got} expected={args.sidecar_sha256}")
    if args.only_extra_feature != FEATURE:
        return fail(f"only_extra_feature must be {FEATURE}, got {args.only_extra_feature}")
    if args.clone_recorder != CLONE_RECORDER:
        return fail(f"clone-recorder must stay {CLONE_RECORDER}")

    # Training frame receives only DOWNSTREAK5_RANK; raw streak / bitmap stay in the sidecar file.
    side = pd.read_parquet(sidecar, columns=["datetime", "instrument", FEATURE])
    extra = pd.read_parquet(sidecar)
    banned_cols = {"downstreak5", "neg_bitmap"}
    missing_qc = [c for c in banned_cols if c not in extra.columns]
    if missing_qc:
        return fail(f"sidecar missing QC columns {missing_qc}")
    side = side.copy()
    side["datetime"] = pd.to_datetime(side["datetime"]).dt.normalize()
    side["instrument"] = side["instrument"].astype(str)
    if args.verify_key_digest:
        manifest_path = sidecar.parent / "manifest.json"
        if not manifest_path.is_file():
            return fail(f"manifest missing for key digest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = _key_digest(side)
        expected = str(manifest.get("key_digest") or "")
        if digest.lower() != expected.lower():
            return fail(f"key digest mismatch {digest} != {expected}")
        if str(manifest.get("sidecar_sha256") or "").lower() != got.lower():
            return fail("manifest sidecar sha256 != file sha256")
        if str(manifest.get("feature_name")) != FEATURE:
            return fail("manifest feature is not DOWNSTREAK5_RANK")
        if int(manifest.get("max_market_days", 0)) != 5:
            return fail("manifest max_market_days is not 5")
        if int(manifest.get("multiply_before_rank", 0)) != 1:
            return fail("manifest must rank downstreak5 itself (multiply_before_rank=+1)")

    feat_s = side.set_index(["datetime", "instrument"])[FEATURE].sort_index()
    feat_s = feat_s[~feat_s.index.duplicated(keep="last")]

    train_seg = parse_seg(args.train)
    valid_seg = parse_seg(args.valid)
    test_seg = parse_seg(args.test)

    print(f"[init] qlib provider={args.provider_uri}", flush=True)
    qlib.init(provider_uri=str(args.provider_uri), region=REG_CN, kernels=1)

    if not args.handler_pkl.is_file():
        return fail(f"handler pkl missing: {args.handler_pkl}")
    print(f"[handler] load {args.handler_pkl}", flush=True)
    handler = Alpha158CostKDJ.load(str(args.handler_pkl))
    qc = inject_feature(handler, feat_s, train_seg[0], train_seg[1], FEATURE)
    print(f"[inject] {json.dumps(qc)}", flush=True)
    if qc["_infer_align_rate"] <= 0.0 or qc["_learn_align_rate"] <= 0.0:
        return fail(f"sidecar failed to align any handler rows: {qc}")

    ns = argparse.Namespace(
        model="lgb",
        model_config=None,
        num_boost_round=1000,
        early_stopping_rounds=50,
        fit_kwargs=None,
    )
    model_conf = build_model_task(ns, int(args.num_threads), int(qc["_infer_n_feat"]))
    model = init_instance_by_config(model_conf)

    dataset = DatasetH(
        handler=handler,
        segments={"train": train_seg, "valid": valid_seg, "test": test_seg},
    )

    os.chdir(str(SCRIPT_DIR))
    exp_name = f"{args.experiment}__t5_dstr1"
    print(f"[train] experiment={exp_name} clone_of={args.clone_recorder}", flush=True)
    commit = _git_commit()

    with R.start(experiment_name=exp_name):
        R.log_params(
            clone_recorder=args.clone_recorder,
            only_extra_feature=FEATURE,
            sidecar_sha256=got,
            sidecar_path=str(sidecar),
            handler_pkl=str(args.handler_pkl),
            train=args.train,
            valid=args.valid,
            test=args.test,
            inject_qc=json.dumps(qc),
            git_commit=commit,
            no_portana=True,
            cmd=" ".join(sys.argv),
        )
        fit_kw = build_fit_kwargs(ns)
        print(f"[train] fit_kwargs={fit_kw}", flush=True)
        model.fit(dataset, **fit_kw)
        R.save_objects(**{"params.pkl": model})
        rid = str(R.get_recorder().id)
        print(f"[train] recorder_id={rid}", flush=True)

        print("[predict] valid+test", flush=True)
        pred_valid = pred_to_frame(model.predict(dataset, segment="valid"))
        pred_test = pred_to_frame(model.predict(dataset, segment="test"))

    p25 = out / "pred_2025.csv"
    p26 = out / "pred_2026.csv"
    pred_valid.to_csv(p25, index=False, encoding="utf-8", lineterminator="\n")
    pred_test.to_csv(p26, index=False, encoding="utf-8", lineterminator="\n")

    lineage = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "clone_recorder": args.clone_recorder,
        "candidate_recorder": rid,
        "experiment": exp_name,
        "sidecar_path": str(sidecar),
        "sidecar_sha256": got,
        "only_extra_feature": FEATURE,
        "handler_pkl": str(args.handler_pkl),
        "inject_qc": qc,
        "git_commit": commit,
        "segments": {
            "train": list(train_seg),
            "valid": list(valid_seg),
            "test": list(test_seg),
        },
        "pred_2025": str(p25),
        "pred_2026": str(p26),
        "n_pred_2025": int(len(pred_valid)),
        "n_pred_2026": int(len(pred_test)),
        "online_untouched": True,
        "no_portana": True,
        "config_diff_vs_8a061ea4": (
            "left-join DOWNSTREAK5_RANK only; RobustZScoreNorm+Fillna(0) on that column; "
            "else identical lgb.yaml; did not add raw downstreak5 / upstreak / cum_down / "
            "missing indicator / CNTN5 / ROC5 / SUMN5 / H52 / DSEM / BETA / MAXRET / CYQ / Amihud"
        ),
    }
    (out / "lineage.json").write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    print(f"[done] recorder={rid} pred_2025={len(pred_valid)} pred_2026={len(pred_test)}", flush=True)
    print(json.dumps({"recorder_id": rid, "out_dir": str(out)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
