# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from dataclasses import dataclass, field
from pathlib import Path

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host

_adapter = host.adapter("build_etf_qlib")


def default_qlib_dir():
    return Path.home() / ".qlib/qlib_data/my_data_etf"


def default_protected():
    base = Path.home() / ".qlib/qlib_data"
    return (base / "my_data", base / "my_data_1min")


@dataclass
class BuildConfig(_adapter.BuildConfig):
    lake_root: Path | None = None
    staging_dir: Path = Path(r"D:\qlib_data\_staging_etf_1d")
    qlib_dir: Path = field(default_factory=default_qlib_dir)
    protected: tuple[Path, ...] = ()

    def __post_init__(self):
        self.protected = self.protected or default_protected()

    def resolved_protected(self):
        return self.protected or default_protected()

    def resolved_lake(self):
        return host.etf_front_root(self.lake_root)


def build_parser():
    return host.parser_with_defaults(
        _adapter.build_parser(), lake_root=None,
        staging_dir=Path(r"D:\qlib_data\_staging_etf_1d"),
        qlib_dir=default_qlib_dir(), protected_dir=None,
    )


def config_from_args(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.lake_root = host.etf_front_root(args.lake_root)
    args.protected_dir = args.protected_dir or list(default_protected())
    return _adapter.config_from_args(host.arguments(parser, args))


def main(argv=None):
    try:
        return _adapter.execute(config_from_args(argv))
    except _adapter.BuildEtfError as exc:
        print("ERROR " + str(exc), file=host.sys.stderr)
        return 2


def __getattr__(name):
    return getattr(_adapter, name)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
