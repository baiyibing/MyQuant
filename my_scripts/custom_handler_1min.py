# -*- coding: utf-8 -*-
"""1min handler. Windows are bar counts, not days.

Official qlib highfreq Alpha158 uses freq=1min and
``Ref($close,-2)/Ref($close,-1)-1`` (next 2 minutes). That is the default
label here. Pass label_horizon=30 for a half-hour return.
"""

from __future__ import annotations

from qlib.contrib.data.handler import Alpha158, check_transform_proc
from qlib.data.dataset.handler import DataHandlerLP


class Alpha1minSmall(DataHandlerLP):
    """Cheap smoke features: MA / STD / volume vs 20-bar mean."""

    def __init__(
        self,
        instruments="all",
        start_time=None,
        end_time=None,
        freq="1min",
        label_horizon: int = 2,
        infer_processors=None,
        learn_processors=None,
        fit_start_time=None,
        fit_end_time=None,
        **kwargs,
    ):
        horizon = int(label_horizon)
        fields = [
            "Mean($close, 5)/$close",
            "Mean($close, 10)/$close",
            "Mean($close, 20)/$close",
            "Mean($close, 60)/$close",
            "Std($close, 20)/$close",
            "Mean($volume, 5)/(Mean($volume, 20)+1e-12)",
            "($close-$open)/($open+1e-12)",
            "($high-$low)/($close+1e-12)",
        ]
        names = ["MA5", "MA10", "MA20", "MA60", "STD20", "V5V20", "RET1", "HL"]
        label = [f"Ref($close, -{horizon})/Ref($close, -1) - 1"]
        data_loader = {
            "class": "QlibDataLoader",
            "kwargs": {
                "config": {
                    "feature": (fields, names),
                    "label": (label, ["LABEL0"]),
                },
                "freq": freq,
            },
        }
        infer_processors = check_transform_proc(
            infer_processors
            or [
                {"class": "ProcessInf", "kwargs": {}},
                {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
                {"class": "Fillna", "kwargs": {}},
            ],
            fit_start_time,
            fit_end_time,
        )
        learn_processors = check_transform_proc(
            learn_processors
            or [
                {"class": "DropnaLabel"},
                {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
            ],
            fit_start_time,
            fit_end_time,
        )
        super().__init__(
            instruments=instruments,
            start_time=start_time,
            end_time=end_time,
            data_loader=data_loader,
            infer_processors=infer_processors,
            learn_processors=learn_processors,
            **kwargs,
        )


class Alpha158Min(Alpha158):
    """Official-style Alpha158 on 1min bars (windows are minutes)."""

    def __init__(self, *args, freq="1min", label_horizon: int = 2, **kwargs):
        kwargs.setdefault("freq", freq)
        self._label_horizon = int(label_horizon)
        super().__init__(*args, **kwargs)

    def get_label_config(self):
        h = getattr(self, "_label_horizon", 2)
        return ([f"Ref($close, -{h})/Ref($close, -1) - 1"], ["LABEL0"])
