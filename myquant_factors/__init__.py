"""Shared factor APIs, loaded on demand for the selected capability.

Importing a path/bridge or TR-band helper does not initialize the chip kernels,
Numba, Qlib, or plotting stack. Public names retain their original objects.
"""
from importlib import import_module as _import_module

_EXPORTS = {
    "ChipFactor": (".cyq", "ChipFactor"),
    "calc_curpdf": (".cyq", "calc_curpdf"),
    "calc_cumpdf": (".cyq", "calc_cumpdf"),
    "calc_dist_chips": (".cyq", "calc_dist_chips"),
    "calc_adj_turnover": (".distribution_of_chips", "calc_adj_turnover"),
    "calc_triang_pdf": (".distribution_of_chips", "calc_triang_pdf"),
    "calc_uniform_pdf": (".distribution_of_chips", "calc_uniform_pdf"),
    "calc_distribution_of_chips": (".turnover_coefficient_ops", "calc_distribution_of_chips"),
    "calc_rc": (".turnover_coefficient_ops", "calc_rc"),
    "calc_roll_cyq": (".turnover_coefficient_ops", "calc_roll_cyq"),
    "rolling_frame": (".utils", "rolling_frame"),
    "rolling_windows": (".utils", "rolling_windows"),
    "classify_tr_bb_signal": (".chip.bands", "classify_tr_bb_signal"),
    "compute_tr_bb_columns": (".chip.bands", "compute_tr_bb_columns"),
    "adapt_columns": (".chip.core", "adapt_columns"),
    "compute_crossday_turnover_resistance": (".chip.core", "compute_crossday_turnover_resistance"),
    "bb_position": (".price_bb", "bb_position"),
    "DivergenceSignal": (".weekly_macd_divergence", "DivergenceSignal"),
    "detect_weekly_macd_divergence": (".weekly_macd_divergence", "detect_weekly_macd_divergence"),
}
_MODULE_EXPORTS = {
    name: "." + name for name in (
        "cyq", "distribution_of_chips", "turnover_coefficient_ops", "utils",
        "chip", "price_bb", "weekly_macd_divergence", "_runtime",
    )
}
__all__ = list(_EXPORTS) + [name for name in _MODULE_EXPORTS if not name.startswith("_")]


def __getattr__(name):
    if name in _EXPORTS:
        module, member = _EXPORTS[name]
        value = getattr(_import_module(module, __name__), member)
    elif name in _MODULE_EXPORTS:
        value = _import_module(_MODULE_EXPORTS[name], __name__)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS) | set(_MODULE_EXPORTS))
