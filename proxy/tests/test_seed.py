import json
import shutil
from pathlib import Path

import pytest

from app.seed import load_seed, persona_of, validate_seed

SEED_DIR = Path(__file__).parents[1] / "seed"
IMAGES_DIR = Path(__file__).parents[2] / "seed-images"


def test_persona_of():
    assert persona_of("u_ana") == "u_ana"
    assert persona_of("u_ana__r1s0") == "u_ana"


def test_shipped_seed_is_valid():
    assert validate_seed(SEED_DIR, IMAGES_DIR) == []


def test_load_resolves_urls_and_overrides(tmp_path):
    ov = tmp_path / "o.json"
    ov.write_text(json.dumps({"p01": {"price": 1.0, "description": "x"}}))
    s = load_seed(SEED_DIR, "https://img.test/base/", ov)
    assert s.catalog["p01"]["price"] == 1.0 and s.catalog["p01"]["description"] == "x"
    assert s.catalog["p01"]["image_url"].startswith("https://img.test/base/products/")
    assert s.renders["u_ana"]["p01"] == "https://img.test/base/tryons/u_ana/p01.jpg"
    assert s.users["u_ana"]["avatar_url"] == "https://img.test/base/avatars/u_ana.jpg"
    assert s.wardrobe["u_ana"][0]["ghost_image_url"].startswith("https://img.test/base/garments/")
    assert s.looks["u_carla"][0]["tryon_image_url"].startswith("https://img.test/base/tryons/")


@pytest.mark.parametrize("patch", [{"p99": {"price": 1}}, {"p01": {"image": "x.svg"}}])
def test_override_rejects_unknown_item_or_field(tmp_path, patch):
    ov = tmp_path / "o.json"
    ov.write_text(json.dumps(patch))
    with pytest.raises(ValueError):
        load_seed(SEED_DIR, "https://x", ov)


def test_validate_reports_missing_render(tmp_path):
    shutil.copytree(SEED_DIR, tmp_path / "seed")
    r = json.loads((tmp_path / "seed/renders.json").read_text())
    del r["u_ana"]["p01"]
    (tmp_path / "seed/renders.json").write_text(json.dumps(r))
    problems = validate_seed(tmp_path / "seed", IMAGES_DIR)
    assert any("u_ana" in p and "p01" in p for p in problems)


def test_validate_reports_missing_image_file(tmp_path):
    shutil.copytree(IMAGES_DIR, tmp_path / "img")
    (tmp_path / "img/products/p03.jpg").unlink()
    problems = validate_seed(SEED_DIR, tmp_path / "img")
    assert any("products/p03.jpg" in p for p in problems)
