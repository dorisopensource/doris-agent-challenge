from pathlib import Path

import pytest

from app.search import search, tokens
from app.seed import load_seed


@pytest.fixture(scope="module")
def catalog():
    return load_seed(Path(__file__).parents[1] / "seed", "https://x").catalog


def ids(results):
    return [p["id"] for p in results]


def test_tokens_strip_accents_stopwords_and_plural():
    t = tokens("Calças de Alfaiataria")
    assert {"calcas", "calca", "alfaiataria"} <= t
    assert "de" not in t


def test_search_finds_linen_shirts(catalog):
    found = ids(search(catalog, "camisa de linho branca", 12))
    assert {"p01", "p02"} <= set(found)  # p02 costs more than R$300: search never filters by price
    assert set(found[:2]) == {"p01", "p02"}


def test_search_normalizes(catalog):
    assert "p01" in ids(search(catalog, "CAMISAS de Línho", 12))


def test_search_no_match(catalog):
    assert search(catalog, "xyzabc", 12) == []
    assert search(catalog, "", 12) == []


def test_search_limit(catalog):
    assert len(search(catalog, "linho", 2)) == 2
