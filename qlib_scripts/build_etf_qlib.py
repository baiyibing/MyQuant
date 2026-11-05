# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from dataclasses import dataclass, field
from pathlib import Path

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("build_etf_qlib")


def default_qlib_dir():
    return Path.home() / ".qlib/qlib_data/my_data_etf"


def default_protected():
    base = Path.home() / ".qlib/qlib_data"
    return (base / "my_data", base / "my_data_1min")


@dataclass
class BuildConfig:
    lake_root: Path | None = None
    staging_dir: Path = Path(r"D:\qlib_data\_staging_etf_1d")
    qlib_dir: Path = field(default_factory=default_qlib_dir)
    protected: tuple[Path, ...] = ()
    meta_dir: Path | None = None
    max_workers: int = 8
    dry_run: bool = False
    wipe_qlib_dir: bool = False
    verify: bool = False
    python: str = field(default_factory=lambda: host.sys.executable)

    def __post_init__(self):
        self.protected = self.protected or default_protected()

    def resolved_protected(self):
        return self.protected or default_protected()

    def resolved_lake(self):
        return host.etf_front_root(self.lake_root)

    def resolved_meta(self):
        if self.meta_dir is not None:
            return self.meta_dir
        return _load_backend().default_meta_dir(self.qlib_dir)


def build_parser():
    return host.parser_with_defaults(
        host.cli.build_etf_qlib_parser(), lake_root=None,
        staging_dir=Path(r"D:\qlib_data\_staging_etf_1d"),
        qlib_dir=default_qlib_dir(), protected_dir=None,
    )


def config_from_args(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    backend = _load_backend()
    args.lake_root = host.etf_front_root(args.lake_root)
    args.protected_dir = args.protected_dir or list(default_protected())
    return backend.config_from_args(host.arguments(parser, args))


def main(argv=None):
    cfg = config_from_args(argv)
    backend = _load_backend()
    try:
        return backend.execute(cfg)
    except backend.BuildEtfError as exc:
        print("ERROR " + str(exc), file=host.sys.stderr)
        return 2


def __getattr__(name):
    return host.adapter_attribute(_load_backend, name)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
