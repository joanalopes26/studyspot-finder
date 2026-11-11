"""
Verifica se o MongoDB 'studyspot' database contém dados corretos e consistentes após a ingestão
Compara contagens com os ficheiros JSONL filtrados de origem.

"""

import json
import random
import sys
import time
from pathlib import Path
from collections import Counter

from pymongo import MongoClient

# ─────────────────────────── CONFIG ───────────────────────────
MONGO_URI  = "mongodb://localhost:27017"
DB_NAME    = "studyspot"
SEED       = 42

DATA_DIR      = Path("filtered")
BUSINESS_FILE = DATA_DIR / "business_filtered.jsonl"
REVIEW_FILE   = DATA_DIR / "review_filtered.jsonl"
USER_FILE     = DATA_DIR / "user_filtered.jsonl"


def count_lines(path):
    """Conta linhas não vazias no arquivo JSONL."""
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def separator(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ──────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  StudySpot Finder — Consistency Verification")
    print("=" * 60)

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"ERROR: Cannot connect to MongoDB: {e}")
        sys.exit(1)

    db  = client[DB_NAME]
    rng = random.Random(SEED)
    ok  = True          # pass/fail

    # ── Conta de comparação ───────────────────────────────────
    separator("1. Count Comparison  (Source JSONL vs MongoDB)")

    checks = [
        ("venues",  BUSINESS_FILE),
        ("reviews", REVIEW_FILE),
        ("users",   USER_FILE),
    ]

    print(f"\n  {'Collection':<12} {'JSONL':>10} {'MongoDB':>10} {'Match':>8}")
    print(f"  {'─' * 44}")
    for coll_name, jsonl_path in checks:
        src_count  = count_lines(jsonl_path)
        mongo_count = db[coll_name].count_documents({})
        match = "✓" if src_count == mongo_count else "✗"
        if src_count != mongo_count:
            ok = False
        print(f"  {coll_name:<12} {src_count:>10,} {mongo_count:>10,} {match:>8}")

    # ── integridade referencial ──────────────────────────────
    separator("2. Referential Integrity")

    # 2a. Verifica se as review.venue_id must existem nas venues
    venue_ids  = set(db.venues.distinct("_id"))
    review_venue_ids = set(db.reviews.distinct("venue_id"))
    orphan_venues = review_venue_ids - venue_ids
    status = "✓" if not orphan_venues else "✗"
    print(f"\n  Reviews → Venues:")
    print(f"    Distinct venue_ids in reviews : {len(review_venue_ids):,}")
    print(f"    Distinct _id in venues        : {len(venue_ids):,}")
    print(f"    Orphan venue references        : {len(orphan_venues):,}  {status}")
    if orphan_venues:
        ok = False
        print(f"    (first 5: {list(orphan_venues)[:5]})")

    # 2b. Verifica se todas os review.user_id existem nos users
    user_ids  = set(db.users.distinct("_id"))
    review_user_ids = set(db.reviews.distinct("user_id"))
    orphan_users = review_user_ids - user_ids
    status = "✓" if not orphan_users else "✗"
    print(f"\n  Reviews → Users:")
    print(f"    Distinct user_ids in reviews  : {len(review_user_ids):,}")
    print(f"    Distinct _id in users         : {len(user_ids):,}")
    print(f"    Orphan user references         : {len(orphan_users):,}  {status}")
    if orphan_users:
        ok = False
        print(f"    (first 5: {list(orphan_users)[:5]})")

    # ── Distribuição estatística de avaliações ─────────────────────────────────

    # em reviews
    separator("3. Star Distribution  (reviews)")

    pipeline = [
        {"$group": {"_id": "$stars", "count": {"$sum": 1}}},
        {"$sort":  {"_id": 1}},
    ]
    star_dist = list(db.reviews.aggregate(pipeline))
    total_rev = sum(d["count"] for d in star_dist)

    print(f"\n  {'Stars':>6} {'Count':>10} {'%':>8}  Bar")
    print(f"  {'─' * 46}")
    for d in star_dist:
        pct = d["count"] / total_rev * 100 if total_rev else 0
        bar = "█" * int(pct / 2)
        print(f"  {d['_id']:>6} {d['count']:>10,} {pct:>7.1f}%  {bar}")

    # em venues
    separator("4. Star Distribution  (venues)")

    pipeline_v = [
        {"$group": {"_id": "$stars", "count": {"$sum": 1}}},
        {"$sort":  {"_id": 1}},
    ]
    vstar_dist = list(db.venues.aggregate(pipeline_v))
    total_ven  = sum(d["count"] for d in vstar_dist)

    print(f"\n  {'Stars':>6} {'Count':>10} {'%':>8}")
    print(f"  {'─' * 30}")
    for d in vstar_dist:
        pct = d["count"] / total_ven * 100 if total_ven else 0
        print(f"  {d['_id']:>6} {d['count']:>10,} {pct:>7.1f}%")

    # ── Contagem de amenities ──────────────────────────────────
    separator("5. Amenity Coverage  (venues)")

    total_venues = db.venues.count_documents({})
    with_wifi    = db.venues.count_documents({"amenities.wifi": {"$exists": True}})
    with_noise   = db.venues.count_documents({"amenities.noise_level": {"$exists": True}})
    with_outlets  = db.venues.count_documents({"amenities.outlet_mentions": {"$gt": 0}})

    print(f"\n  Total venues             : {total_venues:,}")
    print(f"  With wifi attribute      : {with_wifi:,}  "
          f"({with_wifi/total_venues*100:.1f}%)")
    print(f"  With noise_level         : {with_noise:,}  "
          f"({with_noise/total_venues*100:.1f}%)")
    print(f"  With outlet_mentions > 0 : {with_outlets:,}  "
          f"({with_outlets/total_venues*100:.1f}%)")

    # ── percentagem de reviews com os campos das amenities ─────────────────────────────
    separator("6. Boolean Flag Coverage  (reviews)")

    total_reviews = db.reviews.count_documents({})
    m_wifi   = db.reviews.count_documents({"mentions_wifi":    True})
    m_outlet = db.reviews.count_documents({"mentions_outlets": True})
    m_pastry = db.reviews.count_documents({"mentions_pastry":  True})

    print(f"\n  Total reviews        : {total_reviews:,}")
    print(f"  mentions_wifi   = T  : {m_wifi:,}  "
          f"({m_wifi/total_reviews*100:.1f}%)")
    print(f"  mentions_outlets= T  : {m_outlet:,}  "
          f"({m_outlet/total_reviews*100:.1f}%)")
    print(f"  mentions_pastry = T  : {m_pastry:,}  "
          f"({m_pastry/total_reviews*100:.1f}%)")

    # ── sample de exemplos ──────────────────────────────────
    separator("7. Sample Documents")

    print("\n  --- Sample Venue ---")
    sample_venue = db.venues.find_one({"amenities.wifi": {"$exists": True}})
    if sample_venue:
        for k in ("_id", "name", "city", "state", "stars",
                   "review_count", "is_open", "categories", "amenities"):
            print(f"    {k}: {sample_venue.get(k)}")
        rr = sample_venue.get("recent_reviews", [])
        print(f"    recent_reviews: [{len(rr)} embedded]")

    print("\n  --- Sample Review ---")
    sample_review = db.reviews.find_one({"mentions_wifi": True})
    if sample_review:
        for k, v in sample_review.items():
            val = v if k != "text" else v[:120] + "…"
            print(f"    {k}: {val}")

    print("\n  --- Sample User ---")
    sample_user = db.users.find_one()
    if sample_user:
        for k, v in sample_user.items():
            print(f"    {k}: {v}")

    # ── verificação de reviews recentes ──────────────────────────────
    separator("8. Recent Reviews Embedding Check")

    with_recent  = db.venues.count_documents({"recent_reviews": {"$exists": True, "$ne": []}})
    max_embedded = list(db.venues.aggregate([
        {"$project": {"n": {"$size": {"$ifNull": ["$recent_reviews", []]}}}},
        {"$sort": {"n": -1}},
        {"$limit": 1},
    ]))

    print(f"\n  Venues with recent_reviews : {with_recent:,} / {total_venues:,}")
    if max_embedded:
        print(f"  Max embedded reviews       : {max_embedded[0]['n']}")

    # ── verificação de dados geoespaciais ──────────────────────────────────
    separator("9. Geospatial Index & Data Check")

    geo_ok = db.venues.count_documents({
        "location.type": "Point",
        "location.coordinates": {"$exists": True},
    })
    print(f"\n  Venues with valid GeoJSON Point : {geo_ok:,} / {total_venues:,}")

    indexes = db.venues.index_information()
    geo_indexes = [k for k, v in indexes.items()
                   if any("2dsphere" in str(kv) for kv in v.get("key", []))]
    print(f"  2dsphere indexes on venues      : {geo_indexes or 'NONE'}")

    # ── veredicto final ────────────────────────────────────────
    separator("RESULT")
    if ok:
        print("\n  ✓  All consistency checks PASSED.\n")
    else:
        print("\n  ✗  Some checks FAILED — review the output above.\n")

    client.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
