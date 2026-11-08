# Historical SW-L1 research snapshot

This directory retains the original raw responses, industry maps and research
coverage/cross-check artifacts. The data-collection implementation now lives
in MyQuant-infra; `_merge.py` and `_merge_fin.py` are removed here.

For a new batch use infra's explicit `--merge-gildata smart` / `fin` commands,
with the actual raw inputs, universe, output directory and evidence metadata.
Instructions: [reference-data collection](../../my_docs/prompt-kimi-datasource-industry-harvest.md).
MyQuant consumes a selected map through `load_qlib_industry_map`; score
neutralization, research bypass and model policy remain in MyQuant.
