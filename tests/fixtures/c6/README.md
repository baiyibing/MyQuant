# Frozen C6 v1 outputs

`v1-golden.json` records outputs of the original MQ implementations at
`b0cdb421f49e109e892c4a192b4791695b383f37`. Bundle/config/stage outputs were
captured before editing the host modules. The three metadata-helper outputs
were captured by executing that same base commit's `run_manifest.py` source
from `git show`, with synthetic files in a temporary directory. No training
or external data was involved.

The fixture retains exact canonical signal-bundle strings, calendar and bundle
digests, canonical config strings and hashes, and exact pretty manifest strings.
It covers empty bundles, prediction policy, declared availability with unsorted
rows, identity policy, Unicode, numeric values, nested config fields, all four
manifest stages, and train/export/sweep metadata helpers.

Tests compare the host facade and pinned infra to these fixed outputs, validate
the persisted bundles, and round-trip manifest bytes and sidecars. Config hashes
exclude only the top-level `config_hash`; a nested field with that name remains
part of the hash. Signal canonical bytes include one LF; config hash inputs do
not. Do not regenerate these fixtures to accommodate a changed v1 hash.
