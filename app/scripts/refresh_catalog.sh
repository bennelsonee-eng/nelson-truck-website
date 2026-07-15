#!/usr/bin/env bash
# refresh_catalog.sh — run AFTER any PACE/catalog feed to keep the category
# taxonomy and the search index in sync. Idempotent; safe to re-run anytime.
#
# Why this exists: new feed products do not auto-file into the taxonomy, and
# search (Typesense) is not auto-maintained. This wraps the two follow-up
# steps so they can't be forgotten or run out of order:
#
#   1. Relink newly-imported products into the category tree
#      (relink_product_categories.py) — only touches products with NO
#      category yet, and honors the category_locked manual overrides
#      (issues #13/#14), so it never disturbs existing placements.
#   2. Reindex Typesense so search facets match browse.
#
# The feed import itself runs upstream, before this. The PACE category
# scrapers (scrape_pace_categories_python.py / map_part_types_to_categories.py)
# now skip category_locked part types, so re-scraping no longer clobbers the
# manual taxonomy.
#
# Run on the prod box:
#   bash app/scripts/refresh_catalog.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # .../app
cd "$APP_DIR"

# Derive a plain (non-asyncpg) DSN from the backend .env for the relinker.
# Scope it to ONLY the relinker command — reindex_typesense.py reads its own
# (asyncpg) URL from .env, and a stray plain DATABASE_URL in the environment
# makes SQLAlchemy reach for psycopg2 (not installed) and fail.
RAW_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)"
if [ -z "${RAW_URL:-}" ]; then
  echo "refresh_catalog: DATABASE_URL not found in $APP_DIR/.env" >&2
  exit 1
fi
PLAIN_URL="${RAW_URL/+asyncpg/}"

PY="backend/.venv/bin/python"

echo "[refresh] 1/2 relinking new products into the taxonomy..."
DATABASE_URL="$PLAIN_URL" "$PY" scripts/relink_product_categories.py

echo "[refresh] 2/2 reindexing Typesense..."
( cd backend && .venv/bin/python ../scripts/reindex_typesense.py )

echo "[refresh] done."
