# Local candidate evidence

- `cd cv/data_pipeline && uv run --extra test python -m pytest tests --cov=mgts_data_pipeline --cov-report=term-missing`: 61 passed; 84.56% focused coverage.
- Root entrypoint: `uv run --project cv/data_pipeline mgts-datasets --help` succeeds.
- Real final command: `uv run --project cv/data_pipeline mgts-datasets normalize --source broken_poles_v2 --output /tmp/mgts-normalized-final-broken-poles`; subsequent `validate` reports valid=true, 533 images, 745 annotations. 71 image records rejected whole, including 115 annotations; original files unchanged. Output remains train-only.
- Worker verified fresh-directory Broken Poles ZIP + manifest fetch, checksum mismatch rejection and token-free cache reuse; larger ZIP fresh fetch covered by tests, not repeated live download.
- Six adapters exercised by fixtures and real numeric inventories. This is not a claim that all six complete datasets normalize cleanly: Powerline quarantine opt-in reaches conflicting duplicate annotations and fails closed. No visual labeling audit or model training performed.
- Explicit relative YAML `path: .` removed: consumers should pass absolute YAML path to resolve images relative to that YAML, not a global Ultralytics datasets root. Regression test failed before fix, passes afterward.
- No push, PR, protected-branch change, or normalized-data upload requested/performed.

- Real PD-Defect run exposed float serialization regression: 10 significant digits moved boundary boxes fractionally outside image bounds. Minimal failing fixture reproduced it; switched to round-trip float representation without clipping, regression test now passes. Real rerun and standalone validate succeeded: 1,801 images, 2,182 annotations, valid=true at /tmp/mgts-normalized-final-pd.
