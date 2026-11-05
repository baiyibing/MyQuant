"""C6: public imports, optional dependency boundary and frozen v1 byte parity."""

from copy import deepcopy
from importlib.resources import files
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from myquant_contract import signal_bundle as signal  # noqa: E402
from my_scripts import run_manifest as manifest  # noqa: E402

GOLDEN = json.loads((ROOT / "tests/fixtures/c6/v1-golden.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("C6 tests must not connect to the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def infra_signal():
    return pytest.importorskip("myquant_infra.contracts.signal_bundle", reason="optional C6 infra pin")


@pytest.fixture
def infra_manifest():
    return pytest.importorskip("myquant_infra.artifacts.provenance", reason="optional C6 infra pin")


def run_without_infra(code, tmp_path):
    prefix = f"import sys; sys.path[:0] = {[str(ROOT), str(ROOT / 'my_scripts')]!r}\n"
    result = subprocess.run(
        [sys.executable, "-S", "-c", prefix + code], cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1"),
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("module", [
    "myquant_contract", "myquant_contract.signal_bundle", "my_scripts.run_manifest", "run_manifest",
])
def test_imports_and_public_names_never_attempt_infra(module, tmp_path):
    run_without_infra(f'''
import importlib
import importlib.abc
class RefuseInfra(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("myquant_infra"):
            raise AssertionError("Import surfaces must not attempt infra: " + fullname)
sys.meta_path.insert(0, RefuseInfra())
host = importlib.import_module({module!r})
names = ({["SCHEMA_ID", "ALLOWED_STAGES", "ManifestError", "canonical_json", "config_hash", "md5_file", "git_commit", "capture_git_provenance", "fingerprint_artifact", "build_manifest", "validate_manifest", "manifest_to_json_bytes", "write_manifest", "load_manifest", "timings_from_recorder", "unknown_timings", "write_train_manifest", "write_export_manifest", "write_sweep_parent_manifest"]!r}
         if "run_manifest" in {module!r} else
         ["build_signal_bundle", "canonical_json_bytes", "validate_signal_bundle"])
for name in names:
    getattr(host, name)
assert not any(n.startswith("myquant_infra") for n in sys.modules)
''', tmp_path)


@pytest.mark.parametrize("module,operations", [
    ("myquant_contract.signal_bundle", [
        "host.canonical_json_bytes({})", "host.build_signal_bundle([])",
        "host.validate_signal_bundle({})",
    ]),
    ("run_manifest", [
        "host.canonical_json({})", "host.config_hash({})", "host.md5_file('missing')",
        "host.git_commit()", "host.capture_git_provenance()",
        "host.fingerprint_artifact('missing')", "host.build_manifest(stage='train')",
        "host.validate_manifest({})", "host.manifest_to_json_bytes({})",
        "host.write_manifest({}, manifests_dir='manifests')", "host.load_manifest('missing')",
        "host.unknown_timings()", "host.write_train_manifest(manifests_dir='manifests', config={})",
        "host.write_export_manifest(manifests_dir='manifests', config={})",
        "host.write_sweep_parent_manifest(manifests_dir='manifests', parent_id='unit')",
    ]),
])
def test_missing_infra_has_install_hint_and_writes_nothing(module, operations, tmp_path):
    run_without_infra(f'''
import importlib
host = importlib.import_module({module!r})
for operation in {operations!r}:
    try:
        eval(operation)
    except ModuleNotFoundError as exc:
        assert "python -m pip install -r requirements-infra.txt" in str(exc)
    else:
        raise AssertionError("Expected install hint: " + operation)
''', tmp_path)


@pytest.mark.parametrize("host", [signal, manifest])
def test_unrelated_import_errors_keep_their_identity(monkeypatch, host):
    missing = ModuleNotFoundError("unrelated backend dependency", name="other_backend")

    def fail(name):
        raise missing

    monkeypatch.setattr(host, "import_module", fail)
    with pytest.raises(ModuleNotFoundError) as caught:
        host._infra()
    assert caught.value is missing
    assert "requirements-infra.txt" not in str(caught.value)


@pytest.mark.parametrize("host,operation", [(signal, "canonical_json_bytes"), (manifest, "config_hash")])
def test_missing_import_does_not_cache_a_fallback(monkeypatch, host, operation):
    sentinel = object()
    backend = SimpleNamespace(**{operation: lambda value: sentinel})
    attempts = []

    def load(name):
        attempts.append(name)
        if len(attempts) == 1:
            raise ModuleNotFoundError("absent", name="myquant_infra")
        return backend

    monkeypatch.setattr(host, "import_module", load)
    with pytest.raises(ModuleNotFoundError, match="requirements-infra.txt"):
        getattr(host, operation)({})
    assert getattr(host, operation)({}) is sentinel
    assert len(attempts) == 2


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
        pred.write_text("datetime,instrument,score\n2026-03-02,SZ000001,1\n", encoding="utf-8")
        kwargs["pred_path"] = pred
    written = getattr(manifest, case["helper"])(
        manifests_dir=tmp_path / "manifests", artifact_dirs=[tmp_path / "sidecar"], **kwargs,
    )
    assert written[0].name == case["filename"]
    assert all(path.read_bytes() == case["json"].encode("utf-8") for path in written)
    assert manifest.load_manifest(written[0]) == case["manifest"]
    assert infra_manifest.load_manifest(written[0]) == case["manifest"]


def test_recorder_snapshot_stays_available_without_infra(tmp_path):
    run_without_infra('''
from types import SimpleNamespace
from run_manifest import timings_from_recorder
assert timings_from_recorder(None) == {"total_seconds": 0, "nodes": []}
recorder = SimpleNamespace(nodes=[{"name": "export", "seconds": 1.25}],
                           counters={"features": {"count": 2}}, rollup=lambda: [{"name": "export", "count": 1}])
assert timings_from_recorder(recorder) == {
    "total_seconds": 1.25, "nodes": recorder.nodes,
    "counters": recorder.counters, "rollup": recorder.rollup(),
}
''', tmp_path)


def test_schema_asset_and_identities_match_pin(infra_signal, infra_manifest):
    assert signal.SCHEMA == infra_signal.SCHEMA == "myquant.signal-bundle/1"
    assert manifest.SCHEMA_ID == infra_manifest.SCHEMA_ID == "myquant.run-manifest/1"
    assert manifest.ALLOWED_STAGES == infra_manifest.ALLOWED_STAGES
    host = ROOT / "myquant_contract/schema/signal-bundle-1.schema.json"
    shared = files(infra_signal).joinpath("schema/signal-bundle-1.schema.json")
    assert host.read_bytes() == shared.read_bytes()


@pytest.mark.parametrize("operation,args,kwargs", [
    ("canonical_json_bytes", ({"z": "信号"},), {}),
    ("build_signal_bundle", ([],), {}),
    ("validate_signal_bundle", ({},), {}),
])
def test_signal_operations_use_infra(monkeypatch, infra_signal, operation, args, kwargs):
    sentinel = object()
    calls = []

    def delegate(*supplied_args, **supplied_kwargs):
        calls.append((supplied_args, supplied_kwargs))
        return sentinel

    monkeypatch.setattr(infra_signal, operation, delegate)
    assert getattr(signal, operation)(*args, **kwargs) is sentinel
    assert len(calls) == 1
    assert calls[0][0] == args


@pytest.mark.parametrize("operation,args,kwargs", [
    ("canonical_json", ({"z": "信号"},), {}), ("config_hash", ({"topk": 5},), {}),
    ("md5_file", ("missing",), {"chunk_size": 3}),
    ("fingerprint_artifact", ("missing",), {"rows": 2, "base_dir": "base"}),
    ("validate_manifest", ({},), {}), ("manifest_to_json_bytes", ({},), {}),
    ("write_manifest", ({},), {"manifests_dir": "unused", "artifact_dirs": ["unused-copy"], "filename": "unit"}),
    ("load_manifest", ("missing",), {}), ("unknown_timings", (), {}),
])
def test_manifest_operations_use_infra(monkeypatch, infra_manifest, operation, args, kwargs):
    sentinel = object()
    calls = []

    def delegate(*supplied_args, **supplied_kwargs):
        calls.append((supplied_args, supplied_kwargs))
        return sentinel

    monkeypatch.setattr(infra_manifest, operation, delegate)
    assert getattr(manifest, operation)(*args, **kwargs) is sentinel
    assert len(calls) == 1
    assert calls[0][0] == args
    assert all(calls[0][1][key] == value for key, value in kwargs.items())


@pytest.mark.parametrize("operation", ["git_commit", "capture_git_provenance", "build_manifest"])
@pytest.mark.parametrize("explicit", [False, True], ids=["host-default", "caller-root"])
def test_git_source_root_is_explicit_and_independent_of_cwd(
    monkeypatch, infra_manifest, tmp_path, operation, explicit,
):
    monkeypatch.chdir(tmp_path)
    supplied_root = tmp_path / "source"
    supplied_root.mkdir()
    expected = supplied_root if explicit else ROOT
    calls = []

    def delegate(*args, **kwargs):
        calls.append(kwargs["repo_root"] if operation == "build_manifest" else args[0])
        return "sentinel"

    monkeypatch.setattr(infra_manifest, operation, delegate)
    kwargs = {"repo_root": supplied_root} if explicit else {}
    if operation == "build_manifest":
        kwargs["stage"] = "train"
    assert getattr(manifest, operation)(**kwargs) == "sentinel"
    assert calls == [expected]


def test_manifest_error_remains_catchable_by_legacy_callers(infra_manifest):
    with pytest.raises(manifest.ManifestError, match="unsupported stage") as caught:
        manifest.build_manifest(stage="invalid")
    assert isinstance(caught.value.__cause__, infra_manifest.ManifestError)


def test_fingerprint_missing_file_keeps_host_error(infra_manifest, tmp_path):
    with pytest.raises(manifest.ManifestError, match="artifact not found"):
        manifest.fingerprint_artifact(tmp_path / "missing.csv")
