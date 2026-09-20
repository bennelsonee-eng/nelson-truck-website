"""Tests for the YMM (Year/Make/Model) lookup service."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.routers.ymm import get_makes, get_models, get_years, resolve
from app.services import ymm_data


# =========================================================================
# Pure: ymm_data
# =========================================================================


class TestCurrentYearRange:
    def test_includes_next_year_first(self):
        years = ymm_data.current_year_range()
        assert years[0] == date.today().year + 1

    def test_descends(self):
        years = ymm_data.current_year_range()
        assert years == sorted(years, reverse=True)

    def test_floor_is_1990(self):
        assert min(ymm_data.current_year_range()) == 1990


class TestListMakes:
    def test_returns_all_makes(self):
        makes = ymm_data.list_makes()
        assert len(makes) > 15
        slugs = {m.slug for m in makes}
        for required in ("ford", "chevrolet", "ram", "toyota", "jeep"):
            assert required in slugs

    def test_featured_first_when_requested(self):
        makes = ymm_data.list_makes(featured_first=True)
        # First few should all be featured
        first5 = makes[:5]
        assert all(m.is_featured for m in first5)

    def test_alphabetical_when_not_featured_first(self):
        makes = ymm_data.list_makes(featured_first=False)
        names = [m.name for m in makes]
        assert names == sorted(names)


class TestListModels:
    def test_returns_models_for_known_make(self):
        models = ymm_data.list_models("ford")
        slugs = {m.slug for m in models}
        assert "f150" in slugs
        assert "transit" in slugs

    def test_unknown_make_returns_empty(self):
        assert ymm_data.list_models("doesnotexist") == []

    def test_year_filter_excludes_models_outside_production_window(self):
        # Ford Maverick started 2022 — querying 2010 should exclude it
        models_2010 = {m.slug for m in ymm_data.list_models("ford", year=2010)}
        models_2024 = {m.slug for m in ymm_data.list_models("ford", year=2024)}
        assert "maverick" not in models_2010
        assert "maverick" in models_2024

    def test_year_filter_respects_year_end(self):
        # Ford E-Series ended 2014
        models_2020 = {m.slug for m in ymm_data.list_models("ford", year=2020)}
        models_2010 = {m.slug for m in ymm_data.list_models("ford", year=2010)}
        assert "e-series" not in models_2020
        assert "e-series" in models_2010

    def test_models_alphabetical(self):
        models = ymm_data.list_models("ford")
        names = [m.name for m in models]
        assert names == sorted(names)


class TestFindMake:
    def test_finds_known_make(self):
        m = ymm_data.find_make("ford")
        assert m is not None and m.name == "Ford"

    def test_case_insensitive(self):
        assert ymm_data.find_make("FORD") is not None

    def test_unknown_returns_none(self):
        assert ymm_data.find_make("xyz123") is None


class TestFindModel:
    def test_finds_known_model(self):
        m = ymm_data.find_model("ford", "f150")
        assert m is not None and m.name == "F-150"

    def test_unknown_returns_none(self):
        assert ymm_data.find_model("ford", "doesnotexist") is None


# =========================================================================
# Router endpoints, against an EMPTY vcdb — the static-seed fallback
# =========================================================================
#
# These used to be introduced as "no DB needed — these are pure", and were
# called with no arguments at all. That stopped being true when the router moved
# onto the PACE-loaded vcdb_make / vcdb_model / vcdb_base_vehicle tables: every
# endpoint took `db: AsyncSession = Depends(get_db)`, and calling it directly
# with nothing passed the `Depends` SENTINEL as the session. All nine failed
# with `AttributeError: 'Depends' object has no attribute 'execute'` — a broken
# call, not a broken endpoint, so they said nothing about the router either way.
#
# The assertions below were always right, and they still are: the router falls
# back to the static seed in `services/ymm_data.py` when the vcdb tables are
# empty, which is the state of a fresh checkout before PACE ingest has run. So
# these now take `clean_db` — a real session against a truncated database — and
# what they actually pin is that fallback. The path is reachable in production
# on any box where the ingest has not run, and until now nothing covered it.
#
# A make/model that only exists in vcdb (not in the static seed) therefore does
# NOT belong in this class; that wants seeded vcdb rows and a test of its own.
#
# `year` and `vehicle_type` are passed explicitly everywhere below for the same
# reason `db` is: their defaults are `Query(None)`, and FastAPI only swaps a
# Query object for a real value while serving a request. A direct call gets the
# Query object itself, which reaches ymm_data and fails on `year <= ...` with
# `TypeError: '<=' not supported between instances of 'int' and 'Query'`. Any
# parameter a direct caller relies on must be named, never left to default.


class TestYmmRouterStaticFallback:
    @pytest.mark.asyncio
    async def test_get_years_returns_descending_list(self, clean_db):
        years = await get_years(clean_db)
        assert years[0] > years[-1]
        assert min(years) == 1990

    @pytest.mark.asyncio
    async def test_get_makes_returns_dicts_with_slug_and_name(self, clean_db):
        makes = await get_makes(year=None, vehicle_type=None, db=clean_db)
        assert all("slug" in m and "name" in m and "is_featured" in m for m in makes)

    @pytest.mark.asyncio
    async def test_get_models_for_known_make(self, clean_db):
        models = await get_models("ford", year=None, vehicle_type=None, db=clean_db)
        assert any(m["slug"] == "f150" for m in models)
        assert all("body_type" in m for m in models)

    @pytest.mark.asyncio
    async def test_get_models_unknown_make_returns_404(self, clean_db):
        with pytest.raises(HTTPException) as exc:
            await get_models("doesnotexist", year=None, vehicle_type=None, db=clean_db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_models_with_year_filter(self, clean_db):
        models_2024 = await get_models("ford", year=2024, vehicle_type=None, db=clean_db)
        assert any(m["slug"] == "maverick" for m in models_2024)
        models_2010 = await get_models("ford", year=2010, vehicle_type=None, db=clean_db)
        assert not any(m["slug"] == "maverick" for m in models_2010)

    @pytest.mark.asyncio
    async def test_resolve_valid_combo_returns_label(self, clean_db):
        out = await resolve(year=2020, make_slug="ford", model_slug="f150", db=clean_db)
        assert out["label"] == "2020 Ford F-150"
        assert out["make"]["slug"] == "ford"
        assert out["model"]["slug"] == "f150"

    @pytest.mark.asyncio
    async def test_resolve_unknown_make_404(self, clean_db):
        with pytest.raises(HTTPException) as exc:
            await resolve(year=2020, make_slug="xyz", model_slug="f150", db=clean_db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_resolve_unknown_model_404(self, clean_db):
        with pytest.raises(HTTPException) as exc:
            await resolve(year=2020, make_slug="ford", model_slug="xyz", db=clean_db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_resolve_year_outside_production_window_400(self, clean_db):
        # Maverick starts 2022 — 2010 should reject
        with pytest.raises(HTTPException) as exc:
            await resolve(year=2010, make_slug="ford", model_slug="maverick", db=clean_db)
        assert exc.value.status_code == 400
