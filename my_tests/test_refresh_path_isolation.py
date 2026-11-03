"""Daily refresh refuses aliases before wiping, rebuilding, or renaming inputs."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

import pytest

import refresh_mydata as refresh


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv('OSKH_SOURCE_PARQUET_ROOT', raising=False)
    cfg = refresh.RefreshConfig(
        qlib_dir=tmp_path/'live/provider', archive_dir=tmp_path/'inputs/archive',
        csv_dir=tmp_path/'inputs/csv', lake_index_root=tmp_path/'inputs/index',
        staging_dir=tmp_path/'outputs/staging', new_qlib_dir=tmp_path/'outputs/new',
        wipe_new_qlib_dir=True,
    )
    cfg.resolve_paths()
    for role in ['qlib_dir', 'archive_dir', 'csv_dir', 'lake_index_root']:
        root = getattr(cfg, role)
        root.mkdir(parents=True)
        (root/'keep.txt').write_text(role+'\n', encoding='utf-8')
    return cfg


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def related(root, relation):
    return {'same': root, 'child': root/'child', 'parent': root.parent}[relation]


@pytest.mark.parametrize('writer', ['staging_dir', 'new_qlib_dir'])
@pytest.mark.parametrize('protected', ['qlib_dir', 'archive_dir', 'csv_dir', 'lake_index_root'])
@pytest.mark.parametrize('relation', ['same', 'child', 'parent'])
def test_output_and_protected_roots_must_be_disjoint(config, tmp_path, writer, protected, relation):
    setattr(config, writer, related(getattr(config, protected), relation))
    before = snapshot(tmp_path)
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        refresh.require_valid(config)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('relation', ['same', 'child', 'parent'])
def test_staging_and_dump_roots_must_be_disjoint(config, relation):
    config.new_qlib_dir = related(config.staging_dir, relation)
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        refresh.require_valid(config)


@pytest.mark.parametrize('writer', ['staging_dir', 'new_qlib_dir'])
@pytest.mark.parametrize('relation', ['same', 'child', 'parent'])
def test_explicit_whole_lake_pin_is_read_only(config, tmp_path, monkeypatch, writer, relation):
    lake = tmp_path/'market/lake'
    index = lake/'index/period=1d/dividend_type=none'
    index.mkdir(parents=True)
    (index/'keep.txt').write_text('market input\n', encoding='utf-8')
    config.lake_index_root = index
    config.source_parquet_root = lake
    monkeypatch.setenv('OSKH_SOURCE_PARQUET_ROOT', str(lake))
    # A sibling stock subtree is outside index, but still inside the pinned lake.
    target = lake/'stock' if relation == 'child' else related(lake, relation)
    setattr(config, writer, target)
    before = snapshot(tmp_path)
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        refresh.require_valid(config)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('relation', ['same', 'normalized', 'child', 'parent'])
def test_wipe_helper_preserves_existing_provider(config, tmp_path, relation):
    root = config.qlib_dir
    target = root/'unused/..' if relation == 'normalized' else related(root, relation)
    target.mkdir(parents=True, exist_ok=True)
    (target/'calendars').mkdir(exist_ok=True)
    (target/'calendars/day.txt').write_text('2026-11-02\n', encoding='utf-8')
    config.new_qlib_dir = target
    assert target.resolve().is_relative_to(tmp_path.resolve())
    assert target.resolve() != tmp_path.resolve()
    before = snapshot(tmp_path)
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        refresh.ensure_dump_target_clean(config)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('protected', ['archive_dir', 'csv_dir', 'lake_index_root', 'staging_dir', 'source_pin'])
def test_wipe_helper_checks_every_protected_input(config, tmp_path, monkeypatch, protected):
    if protected == 'source_pin':
        target = tmp_path/'market/lake'
        monkeypatch.setenv('OSKH_SOURCE_PARQUET_ROOT', str(target))
        config.source_parquet_root = target
    else:
        target = getattr(config, protected)
    (target/'calendars').mkdir(parents=True, exist_ok=True)
    (target/'calendars/day.txt').write_text('2026-11-02\n', encoding='utf-8')
    config.new_qlib_dir = target
    before = snapshot(tmp_path)
    calls = []
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        refresh.ensure_dump_target_clean(config, remover=lambda path: calls.append(path))
    assert calls == []
    assert snapshot(tmp_path) == before


def cli_args(config):
    args = []
    for flag, attr in [('qlib-dir', 'qlib_dir'), ('archive-dir', 'archive_dir'),
                       ('csv-dir', 'csv_dir'), ('lake-index-root', 'lake_index_root'),
                       ('staging-dir', 'staging_dir'), ('new-qlib-dir', 'new_qlib_dir')]:
        args.extend(['--'+flag, str(getattr(config, attr))])
    return args+['--wipe-new-qlib-dir']


@pytest.mark.parametrize('flags', [[], ['--dry-run'], ['--skip-swap'], ['--skip-dump']])
def test_main_refuses_alias_before_preflight_or_steps(config, tmp_path, monkeypatch, flags):
    config.new_qlib_dir = config.qlib_dir
    before = snapshot(tmp_path)
    monkeypatch.setattr(refresh, 'run_preflight', lambda *_a: pytest.fail('preflight ran before refusal'))
    monkeypatch.setattr(refresh, 'run_step', lambda *_a: pytest.fail('child command ran before refusal'))
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        refresh.main(cli_args(config)+flags)
    assert snapshot(tmp_path) == before


def test_cli_returns_nonzero_for_alias(config, tmp_path):
    config.new_qlib_dir = config.qlib_dir
    before = snapshot(tmp_path)
    result = subprocess.run([sys.executable, refresh.__file__, *cli_args(config), '--dry-run'],
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 2
    assert 'path isolation' in result.stderr
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('relation', ['same', 'child', 'parent'])
def test_swap_rejects_overlap_before_any_rename(config, tmp_path, relation):
    new = related(config.qlib_dir, relation)
    new.mkdir(parents=True, exist_ok=True)
    calls = []
    before = snapshot(tmp_path)
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        refresh.atomic_swap(config.qlib_dir, new, renamer=lambda *args: calls.append(args))
    assert calls == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('sink', ['validate', 'wipe', 'swap'])
def test_resolved_directory_aliases_are_rejected_at_every_sink(config, tmp_path, sink):
    target = config.qlib_dir
    target.mkdir(parents=True, exist_ok=True)
    (target/'calendars').mkdir()
    (target/'calendars/day.txt').write_text('2026-11-02\n', encoding='utf-8')
    alias = tmp_path/'alias'
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('directory symlink creation unavailable on this host')
    config.new_qlib_dir = alias
    before = snapshot(tmp_path)
    calls = []
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        if sink == 'validate':
            refresh.require_valid(config)
        elif sink == 'wipe':
            refresh.ensure_dump_target_clean(config, remover=lambda *args: calls.append(args))
        else:
            refresh.atomic_swap(config.qlib_dir, alias, renamer=lambda *args: calls.append(args))
    assert calls == []
    assert snapshot(tmp_path) == before


def test_disjoint_default_style_layout_remains_valid(config):
    assert not config.new_qlib_dir.exists() and not config.staging_dir.exists()
    refresh.require_valid(config)


def test_shared_prefix_sibling_names_allow_real_wipe_and_swap(config, tmp_path):
    config.qlib_dir = tmp_path/'my_data'
    config.new_qlib_dir = tmp_path/'my_data_new_20261103'
    config.staging_dir = tmp_path/'my_data_staging_20261103'
    (config.qlib_dir/'calendars').mkdir(parents=True)
    (config.qlib_dir/'calendars/day.txt').write_text('old\n', encoding='utf-8')
    (config.new_qlib_dir/'calendars').mkdir(parents=True)
    (config.new_qlib_dir/'calendars/day.txt').write_text('partial\n', encoding='utf-8')
    refresh.require_valid(config)
    assert config.new_qlib_dir.resolve().is_relative_to(tmp_path.resolve())
    refresh.ensure_dump_target_clean(config)
    assert not config.new_qlib_dir.exists()
    assert (config.qlib_dir/'calendars/day.txt').read_text() == 'old\n'
    (config.new_qlib_dir/'calendars').mkdir(parents=True)
    (config.new_qlib_dir/'calendars/day.txt').write_text('new\n', encoding='utf-8')
    backup = refresh.atomic_swap(config.qlib_dir, config.new_qlib_dir)
    assert (backup/'calendars/day.txt').read_text() == 'old\n'
    assert (config.qlib_dir/'calendars/day.txt').read_text() == 'new\n'


@pytest.mark.parametrize('sink', ['validate', 'wipe', 'swap'])
@pytest.mark.skipif(os.name != 'nt', reason='Windows case aliases require Windows paths')
def test_windows_case_aliases_are_rejected_at_every_sink(config, tmp_path, sink):
    (config.qlib_dir/'calendars').mkdir()
    (config.qlib_dir/'calendars/day.txt').write_text('2026-11-02\n', encoding='utf-8')
    alias = Path(str(config.qlib_dir).swapcase())
    config.new_qlib_dir = alias
    before = snapshot(tmp_path)
    calls = []
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        if sink == 'validate':
            refresh.require_valid(config)
        elif sink == 'wipe':
            refresh.ensure_dump_target_clean(config, remover=lambda *args: calls.append(args))
        else:
            refresh.atomic_swap(config.qlib_dir, alias, renamer=lambda *args: calls.append(args))
    assert calls == [] and snapshot(tmp_path) == before


def test_source_pin_is_captured_once_and_allows_siblings(config, tmp_path, monkeypatch):
    lake = tmp_path/'market/lake'
    monkeypatch.setenv('OSKH_SOURCE_PARQUET_ROOT', str(lake))
    loaded = refresh.config_from_args(refresh.build_parser().parse_args(cli_args(config)))
    assert loaded.source_parquet_root == lake
    refresh.require_valid(loaded)  # all outputs outside the lake are valid
    monkeypatch.setenv('OSKH_SOURCE_PARQUET_ROOT', str(config.new_qlib_dir))
    refresh.require_valid(loaded)  # helper consumes the captured pin, not changed ambient env
    loaded.new_qlib_dir = lake/'stock'
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        refresh.require_valid(loaded)


def test_protected_alias_is_rejected_without_wipe_advice(config, tmp_path):
    config.new_qlib_dir = config.qlib_dir
    config.wipe_new_qlib_dir = False
    (config.qlib_dir/'calendars').mkdir()
    (config.qlib_dir/'calendars/day.txt').write_text('2026-11-02\n', encoding='utf-8')
    before = snapshot(tmp_path)
    with pytest.raises(refresh.RefreshError, match='path isolation') as failure:
        refresh.ensure_dump_target_clean(config)
    assert '--wipe-new-qlib-dir' not in str(failure.value)
    assert snapshot(tmp_path) == before


def test_unresolvable_identity_is_rejected_before_removal(config, monkeypatch):
    original = Path.resolve
    unresolved = config.new_qlib_dir

    def resolve(path, *args, **kwargs):
        if path == unresolved:
            raise OSError('simulated unavailable identity')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'resolve', resolve)
    with pytest.raises(refresh.RefreshError, match='path isolation'):
        refresh.require_valid(config)
