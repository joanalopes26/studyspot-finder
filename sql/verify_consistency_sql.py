""" 
Verifica se a base de dados MySQL 'studyspot' contém dados corretos e consistentes após a ingestão. 
Compara contagens com os ficheiros JSONL filtrados de origem e valida a integridade.

"""

import sys
from pathlib import Path
import mysql.connector


# ─────────────────────────── CONFIG ───────────────────────────
MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "BDA2627_68059",  #alterar para a password do MySQL
    "database": "studyspot"
}

DATA_DIR = Path("filtered")

BUSINESS_FILE = DATA_DIR / "business_filtered.jsonl"
REVIEW_FILE = DATA_DIR / "review_filtered.jsonl"
USER_FILE = DATA_DIR / "user_filtered.jsonl"


def count_lines(path):
    """Conta linhas não vazias no ficheiro JSONL."""
    if not path.exists():
        # Fallback se os ficheiros estiverem na diretoria atual
        path = Path(path.name)

    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def separator(title):
    print(f"\n{'─' * 60}")
    print(f" {title}")
    print(f"{'─' * 60}")


# ──────────────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print(" StudySpot Finder — MySQL Consistency Verification")
    print("=" * 60)

    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor(dictionary=True)
    except Exception as e:
        print(f"ERROR: Cannot connect to MySQL: {e}")
        sys.exit(1)

    ok = True  # pass/fail status

    # ── 1. Count Comparison ────────────────────────────────────

    separator("1. Count Comparison (Source JSONL vs MySQL)")

    checks = [
        ("Business", BUSINESS_FILE),
        ("Review", REVIEW_FILE),
        ("User", USER_FILE),
    ]

    print(f"\n {'Table':<12} {'JSONL':>10} {'MySQL':>10} {'Match':>8}")
    print(f" {'─' * 44}")

    for table_name, jsonl_path in checks:
        src_count = count_lines(jsonl_path)

        cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}")
        mysql_count = cursor.fetchone()["cnt"]

        match = "✓" if src_count == mysql_count else "✗"

        if src_count != mysql_count:
            ok = False

        print(
            f" {table_name:<12} {src_count:>10,} "
            f"{mysql_count:>10,} {match:>8}"
        )

    # ── 2. Referential Integrity ──────────────────────────────

    separator("2. Referential Integrity")

    # 2a. Reviews -> Business

    cursor.execute(
        "SELECT COUNT(DISTINCT business_id) AS cnt FROM Review"
    )
    rev_biz_cnt = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(*) AS cnt FROM Business")
    biz_cnt = cursor.fetchone()["cnt"]

    cursor.execute("""
        SELECT COUNT(DISTINCT r.business_id) AS orphan_cnt
        FROM Review r
        LEFT JOIN Business b ON r.business_id = b.business_id
        WHERE b.business_id IS NULL
    """)
    orphan_venues = cursor.fetchone()["orphan_cnt"]

    status = "✓" if orphan_venues == 0 else "✗"

    print("\n Review → Business:")
    print(f"   Distinct business_id in Review : {rev_biz_cnt:,}")
    print(f"   Distinct business_id in Business: {biz_cnt:,}")
    print(f"   Orphan business references     : {orphan_venues:,} {status}")

    if orphan_venues > 0:
        ok = False

    # 2b. Reviews -> User

    cursor.execute(
        "SELECT COUNT(DISTINCT user_id) AS cnt FROM Review"
    )
    rev_usr_cnt = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(*) AS cnt FROM User")
    usr_cnt = cursor.fetchone()["cnt"]

    cursor.execute("""
        SELECT COUNT(DISTINCT r.user_id) AS orphan_cnt
        FROM Review r
        LEFT JOIN User u ON r.user_id = u.user_id
        WHERE u.user_id IS NULL
    """)
    orphan_users = cursor.fetchone()["orphan_cnt"]

    status = "✓" if orphan_users == 0 else "✗"

    print("\n Review → User:")
    print(f"   Distinct user_id in Review : {rev_usr_cnt:,}")
    print(f"   Distinct user_id in User   : {usr_cnt:,}")
    print(f"   Orphan user references     : {orphan_users:,} {status}")

    if orphan_users > 0:
        ok = False

    # ── 3. Star Distribution (Review) ─────────────────────────

    separator("3. Star Distribution (Review)")

    cursor.execute("""
        SELECT stars, COUNT(*) AS count
        FROM Review
        GROUP BY stars
        ORDER BY stars
    """)
    star_dist = cursor.fetchall()

    total_rev = sum(d["count"] for d in star_dist)

    print(f"\n {'Stars':>6} {'Count':>10} {'%':>8} Bar")
    print(f" {'─' * 46}")

    for d in star_dist:
        pct = (d["count"] / total_rev * 100) if total_rev else 0
        bar = "█" * int(pct / 2)

        print(
            f" {d['stars']:>6} {d['count']:>10,} "
            f"{pct:>7.1f}% {bar}"
        )

    # ── 4. Star Distribution (Business) ───────────────────────

    separator("4. Star Distribution (Business)")

    cursor.execute("""
        SELECT stars, COUNT(*) AS count
        FROM Business
        GROUP BY stars
        ORDER BY stars
    """)
    vstar_dist = cursor.fetchall()

    total_ven = sum(d["count"] for d in vstar_dist)

    print(f"\n {'Stars':>6} {'Count':>10} {'%':>8}")
    print(f" {'─' * 30}")

    for d in vstar_dist:
        pct = (d["count"] / total_ven * 100) if total_ven else 0

        print(
            f" {float(d['stars']):>6.1f} "
            f"{d['count']:>10,} {pct:>7.1f}%"
        )

    # ── 5. Amenity Coverage (Business_Amenities) ──────────────

    separator("5. Amenity Coverage (Business_Amenities)")

    cursor.execute("SELECT COUNT(*) AS total FROM Business")
    total_businesses = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM Business_Amenities
        WHERE wifi IS NOT NULL AND wifi != ''
    """)
    with_wifi = cursor.fetchone()["cnt"]

    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM Business_Amenities
        WHERE noise_level IS NOT NULL AND noise_level != ''
    """)
    with_noise = cursor.fetchone()["cnt"]

    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM Business_Amenities
        WHERE outlet_mentions > 0
    """)
    with_outlets = cursor.fetchone()["cnt"]

    print(f"\n Total businesses       : {total_businesses:,}")

    if total_businesses:
        print(
            f" With wifi attribute    : {with_wifi:,} "
            f"({with_wifi / total_businesses * 100:.1f}%)"
        )
        print(
            f" With noise_level       : {with_noise:,} "
            f"({with_noise / total_businesses * 100:.1f}%)"
        )
        print(
            f" With outlet_mentions > 0: {with_outlets:,} "
            f"({with_outlets / total_businesses * 100:.1f}%)"
        )

    # ── 6. Boolean Flag Coverage (Review) ─────────────────────

    separator("6. Boolean Flag Coverage (Review)")

    cursor.execute("SELECT COUNT(*) AS total FROM Review")
    total_reviews = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM Review
        WHERE mentions_wifi = 1
    """)
    m_wifi = cursor.fetchone()["cnt"]

    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM Review
        WHERE mentions_outlets = 1
    """)
    m_outlet = cursor.fetchone()["cnt"]

    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM Review
        WHERE mentions_pastry = 1
    """)
    m_pastry = cursor.fetchone()["cnt"]

    print(f"\n Total reviews          : {total_reviews:,}")

    if total_reviews:
        print(
            f" mentions_wifi = T      : {m_wifi:,} "
            f"({m_wifi / total_reviews * 100:.1f}%)"
        )
        print(
            f" mentions_outlets = T   : {m_outlet:,} "
            f"({m_outlet / total_reviews * 100:.1f}%)"
        )
        print(
            f" mentions_pastry = T    : {m_pastry:,} "
            f"({m_pastry / total_reviews * 100:.1f}%)"
        )

    # ── 7. Sample Records ──────────────────────────────────────

    separator("7. Sample Records")

    print("\n --- Sample Business + Amenities ---")

    cursor.execute("""
        SELECT
            b.business_id,
            b.name,
            b.city,
            b.state,
            b.stars,
            b.review_count,
            b.is_open,
            a.wifi,
            a.noise_level,
            a.outlet_mentions
        FROM Business b
        LEFT JOIN Business_Amenities a
            ON b.business_id = a.business_id
        LIMIT 1
    """)
    sample_biz = cursor.fetchone()

    if sample_biz:
        for k, v in sample_biz.items():
            print(f"   {k}: {v}")

    print("\n --- Sample Review ---")

    cursor.execute("""
        SELECT *
        FROM Review
        WHERE mentions_wifi = 1
        LIMIT 1
    """)
    sample_rev = cursor.fetchone()

    if sample_rev:
        for k, v in sample_rev.items():
            val = str(v) if k != "text" else str(v)[:120] + "…"
            print(f"   {k}: {val}")

    print("\n --- Sample User ---")

    cursor.execute("SELECT * FROM User LIMIT 1")
    sample_usr = cursor.fetchone()

    if sample_usr:
        for k, v in sample_usr.items():
            print(f"   {k}: {v}")

    # ── 8. Geospatial Data & Index Check ───────────────────────

    separator("8. Geospatial Data & Index Check")

    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM Business
        WHERE location IS NOT NULL
    """)
    geo_ok = cursor.fetchone()["cnt"]

    print(
        f"\n Businesses with valid location POINT: "
        f"{geo_ok:,} / {total_businesses:,}"
    )

    cursor.execute("""
        SELECT INDEX_NAME
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = 'studyspot'
          AND TABLE_NAME = 'Business'
          AND INDEX_TYPE = 'SPATIAL'
    """)
    spatial_indexes = [
        row["INDEX_NAME"] for row in cursor.fetchall()
    ]

    print(
        f" SPATIAL indexes on Business: "
        f"{spatial_indexes or 'NONE'}"
    )

    # ── Final Result ───────────────────────────────────────────

    separator("RESULT")

    if ok:
        print("\n ✓ All MySQL consistency checks PASSED.\n")
    else:
        print("\n ✗ Some checks FAILED — review the output above.\n")

    cursor.close()
    conn.close()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
