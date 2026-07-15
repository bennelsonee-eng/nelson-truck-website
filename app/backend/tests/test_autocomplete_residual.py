"""Tests for autocomplete Year/Make/Model token stripping.

`_residual_keyword_tokens` is what makes the dropdown's Categories/Brands columns
populate for a "<vehicle> <keyword>" query like "2021 Ford F-150 tonneau". Those
columns count products whose sku/name/brand text matches EVERY token (AND), and
fitment tokens ("2021", "Ford", "F-150") never appear in part text — so without
stripping them the columns came back empty. We bypass the DB by seeding the
module-level VCDB name cache directly, so these stay pure/fast.
"""

from __future__ import annotations

import pytest

from app.routers import catalog


# Representative slice of the real vcdb_make / vcdb_model names (lowercased),
# enough to exercise single-word makes/models, multi-word models, and a
# model token that doubles as a brand-ish word.
_MAKES = {"ford", "chevrolet", "gmc", "ram", "toyota", "nissan", "jeep"}
_MODELS = {
    "f-150", "f-250 super duty", "silverado 1500", "sierra 1500",
    "tacoma", "tundra", "1500", "2500", "transit-250", "titan", "ranger",
}


@pytest.fixture(autouse=True)
def _seed_ymm_cache():
    """Seed (and restore) the process-lifetime VCDB name cache so
    `_residual_keyword_tokens` never touches the database."""
    saved = catalog._YMM_NAME_SETS
    catalog._YMM_NAME_SETS = (_MAKES, _MODELS)
    try:
        yield
    finally:
        catalog._YMM_NAME_SETS = saved


async def _resid(q: str) -> list[str]:
    # db is unused once the cache is seeded.
    return await catalog._residual_keyword_tokens(db=None, q=q)


class TestResidualKeywordTokens:
    @pytest.mark.asyncio
    async def test_reported_case_strips_ymm_keeps_keyword(self):
        # The exact query from the bug report.
        assert await _resid("2021 Ford F-150 tonneau") == ["tonneau"]

    @pytest.mark.asyncio
    async def test_multiword_model_consumed_whole(self):
        # "F-250 Super Duty" must be stripped as a unit, not leave "Super"/"Duty".
        assert await _resid("2021 Ford F-250 Super Duty bedliner") == ["bedliner"]

    @pytest.mark.asyncio
    async def test_multiword_model_without_year_or_make(self):
        assert await _resid("Silverado 1500 floor mats") == ["floor", "mats"]

    @pytest.mark.asyncio
    async def test_multiple_keywords_preserved(self):
        assert await _resid("ram 2500 tonneau cover") == ["tonneau", "cover"]

    @pytest.mark.asyncio
    async def test_plain_keyword_unchanged(self):
        # No YMM tokens — nothing is stripped (brand words are keywords, kept).
        assert await _resid("weathertech floorliner") == ["weathertech", "floorliner"]

    @pytest.mark.asyncio
    async def test_single_keyword_unchanged(self):
        assert await _resid("tonneau") == ["tonneau"]

    @pytest.mark.asyncio
    async def test_pure_ymm_falls_back_to_raw(self):
        # No part keyword left — return the original tokens so behavior is
        # unchanged from before the fix (no regression for vehicle-only queries).
        assert await _resid("2021 Ford F-150") == ["2021", "Ford", "F-150"]

    @pytest.mark.asyncio
    async def test_model_word_that_is_also_a_keyword(self):
        # "titan" is a Nissan model; stripping it still leaves the real keyword.
        assert await _resid("titan toolbox") == ["toolbox"]

    @pytest.mark.asyncio
    async def test_year_only_token_dropped_but_keyword_kept(self):
        assert await _resid("2024 liner") == ["liner"]

    @pytest.mark.asyncio
    async def test_non_year_number_is_not_treated_as_year(self):
        # A 3-digit number isn't a model year; it stays as a keyword token.
        assert await _resid("450 light bar") == ["450", "light", "bar"]
