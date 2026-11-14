#!/usr/bin/env python3
"""
Transforma a databse Yelp filtrada no esquema MongoDB do StudySpot
e carrega-a na base de dados 'studyspot'.

IMPORTANTE!!!
    no terminal mongoDB Compass da database criada, correr o script mongoDB_schema/mongo_schema.js
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from pymongo import MongoClient
from pymongo.errors import BulkWriteError

MONGO_URI  = "mongodb://localhost:27017"
DB_NAME    = "studyspot"
BATCH_SIZE = 5000

DATA_DIR      = Path("filtered")
BUSINESS_FILE = DATA_DIR / "business_filtered.jsonl"
REVIEW_FILE   = DATA_DIR / "review_filtered.jsonl"
USER_FILE     = DATA_DIR / "user_filtered.jsonl"

# ─────────────────────────── amenities ────────────────────────────

RE_WIFI = re.compile(
    r"\b(wi[\-\s]?fi|wifi|wireless\s+internet|internet)\b",
    re.IGNORECASE,
)
RE_OUTLETS = re.compile(
    r"\b(outlets?|plugs?|charging\s+(?:station|port)|power\s+(?:outlet|strip)"
    r"|sockets?|electrical\s+outlet)\b",
    re.IGNORECASE,
)
RE_PASTRY = re.compile(
    r"\b(cakes?|pastr(?:y|ies)|croissants?|muffins?|scones?|do(?:ugh)?nuts?"
    r"|cookies?|pies?|tarts?|biscuits?|danish|brownies?|cupcakes?"
    r"|macarons?)\b",
    re.IGNORECASE,
)

# ─────────────────────────── HELPERS ──────────────────────────

def parse_yelp_attr(value):
    """Parse Yelp attribute values like  u'free'  →  'free'."""
    if value is None or value in ("None", "none", ""):
        return None
    m = re.match(r"u?['\"](.+?)['\"]", str(value))
    return m.group(1) if m else str(value)


def parse_wifi(attributes):
    """Extract wifi status from Yelp business attributes."""
    if not attributes:
        return None
    val = parse_yelp_attr(attributes.get("WiFi"))
    return val if val in ("free", "paid", "no") else None


def parse_noise_level(attributes):
    """Extract noise level from Yelp business attributes."""
    if not attributes:
        return None
    val = parse_yelp_attr(attributes.get("NoiseLevel"))
    return val if val in ("quiet", "average", "loud", "very_loud") else None


def parse_date(date_str):
    """Convert a Yelp date string to a Python datetime."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def read_jsonl(path):
    """Yield parsed JSON objects from a JSONL file."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


# ──────────────────── USERS ────────────────────

def load_users():
    """limpa os users e mapeia o user pelo ID (nome)"""
    print("[1/4] Loading users …")
    t0 = time.time()
    user_map  = {}          
    user_docs = []

    for u in read_jsonl(USER_FILE):
        doc = {
            "_id":           u["user_id"],
            "name":          u.get("name", "Unknown"),
            "review_count":  int(u.get("review_count", 0)),
            "yelping_since": parse_date(u.get("yelping_since")),
        }
        avg = u.get("average_stars")
        if avg is not None:
            doc["average_stars"] = round(float(avg), 2)

        user_map[u["user_id"]] = {"name": doc["name"]}
        user_docs.append(doc)

    print(f"      {len(user_docs):,} users loaded ({time.time() - t0:.1f}s)")
    return user_map, user_docs


# ────────────────────  REVIEWS ──────────────────

def load_reviews(user_map):
    """ prepara as reviews e extrai as amenities mencionadas."""

    print("[2/4] Loading reviews …")
    t0 = time.time()
    review_docs      = []
    reviews_by_venue  = defaultdict(list)

    for r in read_jsonl(REVIEW_FILE):
        text = r.get("text", "")
        date = parse_date(r.get("date"))

        m_wifi    = bool(RE_WIFI.search(text))
        m_outlets = bool(RE_OUTLETS.search(text))
        m_pastry  = bool(RE_PASTRY.search(text))

        doc = {
            "_id":              r["review_id"],
            "venue_id":         r["business_id"],
            "user_id":          r["user_id"],
            "stars":            int(float(r.get("stars", 1))),
            "useful":           int(r.get("useful", 0)),
            "funny":            int(r.get("funny", 0)),
            "cool":             int(r.get("cool", 0)),
            "date":             date,
            "text":             text,
            "mentions_wifi":    m_wifi,
            "mentions_outlets": m_outlets,
            "mentions_pastry":  m_pastry,
        }
        review_docs.append(doc)

        # guarda sumário da review para cada venue (incluindo o nome do user)
        user_name = user_map.get(r["user_id"], {}).get("name", "Unknown")
        reviews_by_venue[r["business_id"]].append({
            "review_id":        r["review_id"],
            "user_id":          r["user_id"],
            "user_name":        user_name,
            "stars":            doc["stars"],
            "date":             date,
            "text_snippet":     text[:200],
            "mentions_outlets": m_outlets,
        })

    print(f"      {len(review_docs):,} reviews loaded ({time.time() - t0:.1f}s)")
    return review_docs, reviews_by_venue


# ──────────────────── VENUES ───────────────────

def load_venues(reviews_by_venue):
    """ prepara as venues a partir das informações das businesses do yelp,
        incluindo as amenities e as reviews recentes (top 10)."""
    print("[3/4] Loading venues …")
    t0 = time.time()
    venue_docs = []

    for b in read_jsonl(BUSINESS_FILE):
        bid = b["business_id"]

        # Transforma categories:  "Coffee & Tea, Bakeries"  →  ["Coffee & Tea", "Bakeries"]
        cats_raw   = b.get("categories", "")
        categories = [c.strip() for c in cats_raw.split(",") if c.strip()] if cats_raw else []

        # cria GeoJSON Point
        lat, lng = b.get("latitude"), b.get("longitude")
        location = {
            "type":        "Point",
            "coordinates": [float(lng), float(lat)],
        } if lat is not None and lng is not None else None

        # Amenities (dos atributos do Yelp e das reviews)
        attrs = b.get("attributes") or {}
        wifi  = parse_wifi(attrs)
        noise = parse_noise_level(attrs)

        venue_reviews = reviews_by_venue.get(bid, [])
        outlet_count  = sum(1 for rv in venue_reviews if rv["mentions_outlets"])

        amenities = {}
        if wifi:
            amenities["wifi"] = wifi
        if noise:
            amenities["noise_level"] = noise
        amenities["outlet_mentions"] = outlet_count

        # top 10 reviews mais recentes (com texto)
        sorted_reviews = sorted(
            venue_reviews,
            key=lambda x: x["date"] or datetime.min,
            reverse=True,
        )[:10]
        recent = [
            {
                "review_id":    rv["review_id"],
                "user_id":      rv["user_id"],
                "user_name":    rv["user_name"],
                "stars":        rv["stars"],
                "date":         rv["date"],
                "text_snippet": rv["text_snippet"],
            }
            for rv in sorted_reviews
        ]

        doc = {
            "_id":          bid,
            "name":         b.get("name", ""),
            "city":         b.get("city", ""),
            "state":        b.get("state", ""),
            "location":     location,
            "stars":        float(b.get("stars", 0)),
            "review_count": int(b.get("review_count", 0)),
            "is_open":      bool(b.get("is_open")),
            "categories":   categories,
        }
        if amenities:
            doc["amenities"] = amenities
        if recent:
            doc["recent_reviews"] = recent

        venue_docs.append(doc)

    print(f"      {len(venue_docs):,} venues loaded ({time.time() - t0:.1f}s)")
    return venue_docs


# ──────────────────── INSERT ────────────────────────

def insert_batch(collection, docs, label):
    """Insere documentos em batches com ordered=False para ser mais rápido + medição de tempo e taxa de inserção/erros"""
    print(f"\n  Inserting {len(docs):,} documents into '{label}' …")
    t0       = time.time()
    inserted = 0
    errors   = 0

    for i in range(0, len(docs), BATCH_SIZE):
        batch = docs[i : i + BATCH_SIZE]
        try:
            result    = collection.insert_many(batch, ordered=False)
            inserted += len(result.inserted_ids)
        except BulkWriteError as e:
            inserted    += e.details.get("nInserted", 0)
            write_errors = e.details.get("writeErrors", [])
            errors      += len(write_errors)
            if write_errors:
                print(f"    ⚠ Batch {i // BATCH_SIZE + 1}: "
                      f"{len(write_errors)} validation error(s)")
                print(f"      First: {write_errors[0].get('errmsg', '')[:150]}")

    elapsed = time.time() - t0
    rate    = inserted / elapsed if elapsed > 0 else 0
    print(f"  ✓ {inserted:,} inserted, {errors:,} errors "
          f"({elapsed:.2f}s · {rate:,.0f} docs/s)")
    return inserted, errors, elapsed


# ──────────────────── MAIN ────────────────────────────────────

def main():
    print("=" * 60)
    print("  StudySpot Finder — MongoDB Data Ingestion")
    print("=" * 60)

    # Validação de ficheiros de entrada
    for f in (BUSINESS_FILE, REVIEW_FILE, USER_FILE):
        if not f.exists():
            print(f"ERROR: {f} not found.  Run filter_yelp.py first.")
            sys.exit(1)

    # Conecta a MongoDB 
    print(f"Connecting to MongoDB at {MONGO_URI} …")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"ERROR: Cannot connect to MongoDB at {MONGO_URI}")
        print(f"       {e}")
        sys.exit(1)

    db = client[DB_NAME]

    # Verifica se as coleções de facto existem
    existing = set(db.list_collection_names())
    for name in ("venues", "reviews", "users"):
        if name not in existing:
            print(f"WARNING: Collection '{name}' not found.")
            print("  Run:  mongosh mongoDB_schema/mongo_schema.js")
            sys.exit(1)

    # limpa dados existentes
    print("Clearing existing data …")
    for name in ("venues", "reviews", "users"):
        db[name].delete_many({})
    print("Existing data cleared.\n")

    # ── Transforma ──────────────────────────────────────────────
    user_map, user_docs               = load_users()
    review_docs, reviews_by_venue     = load_reviews(user_map)
    venue_docs                        = load_venues(reviews_by_venue)

    # ── Insere ─────────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("[4/4] Inserting into MongoDB …")

    total_t0 = time.time()
    results  = {}

    v_ins, v_err, v_t = insert_batch(db.venues,  venue_docs,  "venues")
    results["venues"]  = {"inserted": v_ins, "errors": v_err, "time": v_t}

    r_ins, r_err, r_t = insert_batch(db.reviews, review_docs, "reviews")
    results["reviews"] = {"inserted": r_ins, "errors": r_err, "time": r_t}

    u_ins, u_err, u_t = insert_batch(db.users,   user_docs,   "users")
    results["users"]   = {"inserted": u_ins, "errors": u_err, "time": u_t}

    total_time = time.time() - total_t0

    # ── Sumario ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  INGESTION SUMMARY")
    print("=" * 60)
    print(f"{'Collection':<12} {'Inserted':>10} {'Errors':>8} "
          f"{'Time (s)':>10} {'Docs/s':>10}")
    print("─" * 54)
    for name in ("venues", "reviews", "users"):
        r    = results[name]
        rate = r["inserted"] / r["time"] if r["time"] > 0 else 0
        print(f"{name:<12} {r['inserted']:>10,} {r['errors']:>8,} "
              f"{r['time']:>10.2f} {rate:>10,.0f}")
    print("─" * 54)
    total_ins = sum(r["inserted"] for r in results.values())
    total_err = sum(r["errors"]   for r in results.values())
    print(f"{'TOTAL':<12} {total_ins:>10,} {total_err:>8,} "
          f"{total_time:>10.2f}")

    # count check
    print("\nCollection counts in MongoDB:")
    for name in ("venues", "reviews", "users"):
        print(f"  {name}: {db[name].count_documents({}):,}")

    client.close()
    print("\nDone! ✓")


if __name__ == "__main__":
    main()
