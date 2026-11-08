"""Frozen C6 v1 byte/hash parity using the shared source APIs and MQ host metadata."""

from copy import deepcopy
import json
from pathlib import Path
import socket
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from myquant_infra.contracts import signal_bundle as signal  # noqa: E402
from myquant_infra.artifacts import provenance as manifest
from my_scripts import run_manifest as host_manifest  # noqa: E402

GOLDEN = json.loads((ROOT / "tests/fixtures/c6/v1-golden.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("C6 tests must not connect to the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def infra_signal():
    return signal


@pytest.fixture
def infra_manifest():
    return manifest


@pytest.mark.parametrize("case", GOLDEN["bundles"], ids=lambda case: case["name"])
def test_bundle_golden_bytes_hashes_and_fixture_validation(infra_signal, case):
    rows = deepcopy(case["rows"])
    host = signal.build_signal_bundle(rows, **case["kwargs"])
    shared = infra_signal.build_signal_bundle(rows, **case["kwargs"])
    assert host == shared == case["bundle"]
    expected = case["canonical"].encode("utf-8")
    assert signal.canonical_json_bytes(host) == infra_signal.canonical_json_bytes(shared) == expected
    assert expected.endswith(b"\n") and not expected.endswith(b"\n\n")
    assert not expected.startswith(b"\xef\xbb\xbf")
    fixture = json.loads(case["canonical"])
    before = deepcopy(fixture)
    signal.validate_signal_bundle(fixture)
    infra_signal.validate_signal_bundle(fixture)
    assert fixture == before
    assert rows == case["rows"]


@pytest.mark.parametrize("case", GOLDEN["configs"], ids=["empty", "segments", "unicode-numeric", "hash-field"])
def test_config_golden_canonical_json_and_hash(infra_manifest, case):
    config = case["config"]
    assert manifest.canonical_json(config) == infra_manifest.canonical_json(config) == case["canonical"]
    assert manifest.config_hash(config) == infra_manifest.config_hash(config) == case["config_hash"]
    reordered = dict(reversed(list(config.items())))
    assert manifest.config_hash(reordered) == case["config_hash"]
    assert manifest.config_hash({**config, "config_hash": "ignored again"}) == case["config_hash"]


@pytest.mark.parametrize("case", GOLDEN["manifests"], ids=lambda case: case["kwargs"]["stage"])
def test_manifest_golden_build_write_load(infra_manifest, tmp_path, case):
    host = manifest.build_manifest(**case["kwargs"])
    shared = infra_manifest.build_manifest(**case["kwargs"])
    assert host == shared == case["manifest"]
    expected = case["json"].encode("utf-8")
    assert manifest.manifest_to_json_bytes(host) == infra_manifest.manifest_to_json_bytes(shared) == expected
    primary, sidecar = manifest.write_manifest(
        host, manifests_dir=tmp_path / "host", artifact_dirs=[tmp_path / "sidecar"],
    )
    shared_path, = infra_manifest.write_manifest(shared, manifests_dir=tmp_path / "infra")
    assert primary.name == shared_path.name
    assert primary.read_bytes() == sidecar.read_bytes() == shared_path.read_bytes() == expected
    assert manifest.load_manifest(primary) == infra_manifest.load_manifest(primary) == case["manifest"]


@pytest.mark.parametrize("case", GOLDEN["helper_manifests"], ids=lambda case: case["helper"])
def test_host_metadata_helpers_preserve_baseline_manifests(infra_manifest, tmp_path, case):
    kwargs = deepcopy(case["kwargs"])
    if case["helper"] != "write_sweep_parent_manifest":
        pred = tmp_path / "预测.csv"
        pred.write_text("datetime,instrument,score\n2026-03-02,SZ000001,1\n", encoding="utf-8", newline="\n")
        kwargs["pred_path"] = pred
    written = getattr(host_manifest, case["helper"])(
        manifests_dir=tmp_path / "manifests", artifact_dirs=[tmp_path / "sidecar"], **kwargs,
    )
    assert written[0].name == case["filename"]
    assert all(path.read_bytes() == case["json"].encode("utf-8") for path in written)
    assert manifest.load_manifest(written[0]) == case["manifest"]
    assert infra_manifest.load_manifest(written[0]) == case["manifest"]
