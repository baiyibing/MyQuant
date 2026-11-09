# Chip research Notebook

The Notebook and its training/handler/compute dependencies move together from
BT into MyQuant. The two executable helpers live in
`my_scripts/chip_research`; the numerical/analysis code lives in
`myquant_factors`. MyQuant does not read or import the BT source tree.

All **57 original output objects** are retained unchanged. They are historic
example charts/logs, not results produced by this migration. Execution counts
are cleared and the opening notice states that training, PortAna and market
data processing have not been rerun. `migration-receipt.json` records the
original Notebook fingerprint and the unchanged historical-output digest.

Run Jupyter from the MyQuant root. Before explicitly executing cells, set:

- `MYQUANT_CHIP_QLIB_URI`: an existing absolute Qlib provider directory.
- `MYQUANT_CHIP_RUN_ROOT`: an absolute research-output directory that does not
  overlap the provider or overwrite source code.

The setup fails before provider initialization when required configuration is
missing. No drive search, default lake or sibling BT checkout is used. Data
preparation remains in infra. The retained environment pins are in
`requirements-legacy.txt`; use an explicitly selected research environment,
not an implicit system Python.

Migration call-site repairs: native module imports replace `scr.*`; cumulative
returns use the existing fincore API instead of standalone empyrical; cache
write paths now match their readers; each section uses its own newly returned
recorder rather than an unrelated section or hardcoded historic recorder ID.
No historical performance output was regenerated to match these repairs.

Synthetic validation covers handler resolution, model config construction,
workflow wiring with mocked model/recorders, missing-input rejection and
output preservation. No claim is made that the historical Notebook has been
rerun against current data or that its research settings are accepted defaults.
