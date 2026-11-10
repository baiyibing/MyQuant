# Chip factor Qlib research example

`factor_expr.py` and `qlib_workflow.py` moved from BT `qlib_cost` under
Human 2026-11-09. MyQuant owns factor definitions, experiments, evaluation,
Qlib training and signal export. BT consumes signals and keeps execution,
fees, holdings and NAV rules; this example must not be imported back into
the BT execution path.

The two handler classes and six model configuration builders retain their
historical names and values. Dataset configs now resolve the actual native
handler module `my_scripts.chip_research.factor_expr`, replacing the broken
`scr.factor_expr` path. Workflow logging uses the standard library instead
of requiring Rich. Commented duplicate handler code was removed.

`run_model` is explicitly invoked; importing either module does not fit a
model, initialize a provider or generate a PortAna report. A real invocation
does train, save artifacts, generate signals and run Qlib's native PortAna.
It is not registered in existing training defaults or in any BT strategy.
Legacy label/model/fee settings are example settings, not current product
defaults or new performance evidence.

All numerical factor and plotting dependencies are owned by the same MyQuant
checkout in [myquant_factors](../../myquant_factors/README.md). No `scr.*`,
`qlib_cost` or BT-source imports are required.

The [Notebook](../../examples/chip_research/README.md) retains its historic
outputs with an explicit non-acceptance notice. The initial migration validation
resolved configs and used synthetic/mocked provider, model and recorder ports.
The native pipeline acceptance below separately exercises real Qlib components.

## Bounded native pipeline acceptance

`python -m my_scripts.chip_research.acceptance --help` exposes a separate
small-sample runner. It executes the native factor expressions, CPU LightGBM,
SignalRecord, SigAnaRecord, Qlib PortAna and the existing signal exporter.
It accepts 3–12 explicit instruments and at most 30 test sessions. Train and
validation exclude their final two provider sessions so the T+1/T+2 open
label stays inside each nominal segment.
The historical default `CSRankNorm` applies to all columns, including the learn
label: prepared labels are cross-sectional ranks, not raw open returns. The
acceptance preserves that setting and checks label dates against the raw
T+1/T+2 dependency; it does not adopt these processors as research defaults.

Run from the MyQuant source root with an existing, explicitly selected provider:

```text
python -m my_scripts.chip_research.acceptance --provider <absolute-stock-provider> --output <fresh-absolute-output> --input-kind market --instruments SH600000,SZ000001,SZ000002 --benchmark SH000300 --train 2024-05-06 2024-05-31 --valid 2024-06-03 2024-06-14 --test 2024-06-17 2024-06-28 --price-domain none
```

The provider must supply `open/close/high/low/vol/volume/turnover_rate/factor`
for selected instruments and benchmark close data. Confirm volume units,
turnover denominator and historical availability before a market run. A current
share-count snapshot cannot stand in for historical turnover. This runner does
not construct providers or refresh the market lake.

Outputs must be fresh and outside both the provider and source checkout.
MLflow records, prepared samples, predictions, backtest report and signal bundle
stay in that directory. The receipt distinguishes `synthetic` from `market`,
records parameters/source/input/artifact hashes and checks provider file inventory
and consumed bytes before/after. Signal availability remains `unproven`.
A pipeline PASS alone does not establish PIT quality or strategy profitability.

The native integration tests use deterministic synthetic data encoded by infra;
they fit a real LightGBM model and execute real Qlib PortAna without mocks.
Historical Notebook outputs are preserved. Current host and input readiness is
indexed from the repository README; a missing market provider remains an explicit
blocked result even when synthetic integration passes.
