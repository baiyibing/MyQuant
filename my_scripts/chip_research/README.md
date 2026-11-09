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
outputs with an explicit non-acceptance notice. Validation only resolves
configs and uses synthetic/mocked provider, model and recorder ports.
