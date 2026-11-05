"""MQ-only CLI/path compatibility for the optional qlib production adapters."""

import argparse
from importlib import import_module
from pathlib import Path
import sys

PACKAGE = "myquant_infra.adapters.qlib_data"


def adapter(name):
    try:
        return import_module(PACKAGE + "." + name)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing == "myquant_infra" or missing.startswith(PACKAGE):
            raise ModuleNotFoundError(
                "C1 qlib production requires the optional requirements-infra.txt pin; "
                "install it with python -m pip install -r requirements-infra.txt",
                name=exc.name,
            ) from exc
        raise


def data_roots():
    # Direct script invocation must also work outside the checkout directory.
    root = Path(__file__).resolve().parents[1]
    for path in (root, root / "my_scripts"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return import_module("data_root")


def parser_with_defaults(parser, **defaults):
    # Path/environment policy belongs to MQ; infra receives explicit paths.
    for action in parser._actions:
        if action.dest in defaults:
            action.required = False
    parser.set_defaults(**defaults)
    return parser


def arguments(parser, args):
    """Serialize the parsed legacy CLI using the adapter's declared options."""
    result = []
    for action in parser._actions:
        if action.dest == "help":
            continue
        value = getattr(args, action.dest)
        if value is None:
            continue
        if not action.option_strings:
            result.append(str(value))
        elif isinstance(action, argparse._StoreTrueAction):
            if value:
                result.append(action.option_strings[0])
        elif isinstance(action, argparse._StoreFalseAction):
            if not value:
                result.append(action.option_strings[0])
        elif isinstance(action, argparse._AppendAction):
            for item in value:
                result.extend([action.option_strings[0], str(item)])
        elif action.nargs in ("*", "+"):
            result.append(action.option_strings[0])
            result.extend(map(str, value))
        else:
            result.append(action.option_strings[0] + "=" + str(value))
    return result


def minute_paths(args):
    args.lake_root = args.lake_root or data_roots().resolve_stock_1min_none()
    if not args.skip_index:
        args.index_lake = args.index_lake or data_roots().resolve_index_1min_none()
    return args


def etf_front_root(explicit=None):
    if explicit:
        return Path(explicit)
    none = data_roots().resolve_etf_1d_none()
    if none.name != "dividend_type=none":
        raise ValueError("ETF none root must be dividend_type=none")
    return none.parent / "dividend_type=front"


def legacy_fire_arguments(argv, method):
    """Retain Fire's underscore options and trailing checker method names."""
    result = []
    option_value = False
    for arg in sys.argv[1:] if argv is None else argv:
        if option_value:
            result.append(arg)
            option_value = False
            continue
        if arg == method:
            continue
        if arg.startswith("--"):
            key, sep, value = arg.partition("=")
            arg = key.replace("_", "-") + sep + value
            option_value = not sep and key != "--help"
        result.append(arg)
    return result
