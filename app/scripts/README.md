# Scripts

One-off utilities and migration scripts. Each script is self-contained and runnable as `python -m scripts.<name>` from the `app/backend/` directory (so imports of `app.*` resolve).

## Coming in Phase 1

- `pace_import.py` — bulk catalog migration from PACE/AAM Group export → local catalog
- `wsm_migration.py` — one-shot extraction from old WSM database (customers, orders, equipment SKUs)
- `seed_warehouses.py` — seed warehouses, shipping routes, contract pricing scaffolds
- `test_facs_push.py` — write a test order CSV to FTP and verify pickup
- `seed_dev_data.py` — local-only fixture data for development
- `validate_pricing.py` — sample 50 customer-product-qty tuples from old DB and check new engine returns same prices

## Conventions

- Scripts NEVER write to production without an explicit `--apply` flag
- Default behavior is dry-run + report
- All scripts log to stdout AND to `scripts/logs/{name}.{timestamp}.log`
- Heavy migrations process in chunks with progress bars (`tqdm`)
