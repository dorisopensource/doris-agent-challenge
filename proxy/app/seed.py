"""Seed data: users, catalog, wardrobe, looks and pre-rendered try-ons.

JSON image fields are paths relative to `seed-images/`; `load_seed` turns them into URLs.
"""
import json
from dataclasses import dataclass
from pathlib import Path

OVERRIDABLE = {"name", "description", "price", "tags"}
PRODUCT_FIELDS = ("id", "name", "store", "price", "currency_code", "currency_symbol", "url",
                  "image", "ghost_image", "type", "category", "description", "tags")


@dataclass(frozen=True)
class Seed:
    users: dict[str, dict]
    catalog: dict[str, dict]
    wardrobe: dict[str, list[dict]]
    looks: dict[str, list[dict]]
    renders: dict[str, dict[str, str]]


def persona_of(user_id: str) -> str:
    return user_id.split("__", 1)[0]


def _read(seed_dir: Path) -> dict:
    return {n: json.loads((seed_dir / f"{n}.json").read_text()) for n in
            ("users", "catalog", "wardrobe", "looks", "renders")}


def load_seed(seed_dir: Path, image_base_url: str, overrides_path: Path | None = None) -> Seed:
    raw = _read(seed_dir)
    url = lambda path: f"{image_base_url.rstrip('/')}/{path}"
    catalog = {p["id"]: dict(p) for p in raw["catalog"]}
    if overrides_path:
        for item_id, patch in json.loads(Path(overrides_path).read_text()).items():
            if item_id not in catalog:
                raise ValueError(f"override for unknown item {item_id}")
            bad = set(patch) - OVERRIDABLE
            if bad:
                raise ValueError(f"override of {item_id} touches non-overridable fields {sorted(bad)}")
            catalog[item_id].update(patch)
    for p in catalog.values():
        p["image_url"] = url(p.pop("image"))
        p["ghost_image_url"] = url(p.pop("ghost_image"))
    users = {}
    for u in raw["users"]:
        u = dict(u)
        u["avatar_url"] = url(u.pop("avatar_image"))
        users[u["user_id"]] = u
    wardrobe = {}
    for persona, garments in raw["wardrobe"].items():
        wardrobe[persona] = [{**{k: v for k, v in g.items() if k != "ghost_image"},
                              "ghost_image_url": url(g["ghost_image"])} for g in garments]
    looks = {persona: [{**{k: v for k, v in lk.items() if k != "tryon_image"},
                        "tryon_image_url": url(lk["tryon_image"])} for lk in items]
             for persona, items in raw["looks"].items()}
    renders = {persona: {k: url(v) for k, v in m.items()} for persona, m in raw["renders"].items()}
    return Seed(users, catalog, wardrobe, looks, renders)


def validate_seed(seed_dir: Path, images_dir: Path) -> list[str]:
    raw = _read(seed_dir)
    problems: list[str] = []
    ids = [p.get("id") for p in raw["catalog"]]
    if len(ids) != len(set(ids)):
        problems.append("duplicate catalog ids")
    images: list[str] = []
    for p in raw["catalog"]:
        missing = [f for f in PRODUCT_FIELDS if f not in p]
        if missing:
            problems.append(f"product {p.get('id')} missing fields {missing}")
            continue
        if not p["price"] > 0:
            problems.append(f"product {p['id']} has non-positive price")
        images += [p["image"], p["ghost_image"]]
    personas = [u["user_id"] for u in raw["users"]]
    images += [u["avatar_image"] for u in raw["users"]]
    for persona in personas:
        own = [g["garment_id"] for g in raw["wardrobe"].get(persona, [])]
        images += [g["ghost_image"] for g in raw["wardrobe"].get(persona, [])]
        renders = raw["renders"].get(persona, {})
        for gid in [i for i in ids if i] + own:
            if gid not in renders:
                problems.append(f"no try-on render for {persona} × {gid}")
        images += list(renders.values())
        for lk in raw["looks"].get(persona, []):
            images.append(lk["tryon_image"])
            for gid in lk["garment_ids"]:
                if gid not in own:
                    problems.append(f"look {lk['look_id']} of {persona} uses unknown garment {gid}")
    for path in sorted(set(images)):
        if not (images_dir / path).is_file():
            problems.append(f"missing image file {path}")
    return problems
