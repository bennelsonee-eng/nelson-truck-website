#!/bin/bash
# Bootstrap PACE catalog: bring Postgres up, apply migration, ingest BDKW as smoke test.
# Run from repo root: bash app/scripts/bootstrap_pace_smoke_test.sh

set -e

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$REPO/app/backend/.venv/Scripts/python.exe"
DC_DIR="$REPO/app"

echo "=== Step 1: Start Postgres + Typesense via docker-compose ==="
cd "$DC_DIR"
docker compose up -d postgres typesense
echo "  Waiting for postgres health..."
until docker compose exec -T postgres pg_isready -U postgres >/dev/null 2>&1; do sleep 2; done
echo "  Postgres ready"

echo ""
echo "=== Step 2: Apply Alembic migrations ==="
cd "$REPO/app/backend"
"$PY" -m alembic upgrade head

echo ""
echo "=== Step 3: Ingest BDKW (Bestop) as smoke test ==="
cd "$REPO"
"$PY" app/scripts/import_pace_brand.py BDKW

echo ""
echo "=== Step 4: Sanity counts ==="
PGPASSWORD=titan2026 psql -h localhost -p 5433 -U postgres -d titan_web -c "
SELECT 'pace_part' AS table, COUNT(*) FROM pace_part
UNION ALL SELECT 'pace_fitment', COUNT(*) FROM pace_fitment
UNION ALL SELECT 'product (PACE-derived)', COUNT(*) FROM product WHERE sku LIKE 'BDKW-%'
UNION ALL SELECT 'product_attribute', COUNT(*) FROM product_attribute
UNION ALL SELECT 'product_description', COUNT(*) FROM product_description
UNION ALL SELECT 'product_pricing', COUNT(*) FROM product_pricing
UNION ALL SELECT 'product_package', COUNT(*) FROM product_package
UNION ALL SELECT 'vcdb_base_vehicle', COUNT(*) FROM vcdb_base_vehicle
UNION ALL SELECT 'pcdb_part_type', COUNT(*) FROM pcdb_part_type
;
"
echo ""
echo "=== Done.  If counts look right, run all brands with --all-discovered ==="
