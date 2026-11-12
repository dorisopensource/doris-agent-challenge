"""Catalog text search. Scores token overlap; never filters by price, size or color.

ponytail: token overlap with a trailing-"s" plural fold; swap for BM25/embeddings if the catalog grows.
"""
import re
import unicodedata

STOPWORDS = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "um", "uma", "para", "pra", "com",
             "em", "no", "na"}


def tokens(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    out: set[str] = set()
    for t in re.split(r"[^a-z0-9]+", plain):
        if not t or t in STOPWORDS:
            continue
        out.add(t)
        if len(t) > 3 and t.endswith("s"):
            out.add(t[:-1])
    return out


def search(catalog: dict[str, dict], query: str, limit: int) -> list[dict]:
    q = tokens(query)
    scored = []
    for item in catalog.values():
        score = (3 * len(q & tokens(item["name"])) + 2 * len(q & tokens(" ".join(item["tags"])))
                 + len(q & tokens(item["description"])))
        if score:
            scored.append((-score, item["id"], item))
    return [item for _, _, item in sorted(scored, key=lambda s: s[:2])[:limit]]
