import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

# ------------------------------- CONFIG -------------------------------
DATA_DIR = Path(".")                 # where the yelp_academic_dataset_*.json files are
OUT_DIR = Path("filtered")

# Exact match against StudySpot categories
TARGET_CATEGORIES = {
    "Coffee & Tea",
    "Cafes",
    "Bakeries",
    "Coffee Roasteries",
    "Patisserie/Cake Shop"
}

CITIES = []                          
MIN_BUSINESS_REVIEWS = 30          
TARGET_REVIEWS = 100_000             
KEEP_ONLY_REVIEWED_BUSINESSES = True 
DROP_USER_FIELDS = {"friends"}       
SEED = 42                            
# -----------------------------------------------------------------------

BUSINESS_FILE = DATA_DIR / "yelp_academic_dataset_business.json"
REVIEW_FILE = DATA_DIR / "yelp_academic_dataset_review.json"
USER_FILE = DATA_DIR / "yelp_academic_dataset_user.json"

def read_lines(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield line

def is_target_business(b):
    cats = b.get("categories")
    if not cats:
        return False
    names = {c.strip() for c in cats.split(",")}
    if not names & TARGET_CATEGORIES:
        return False
    if b.get("latitude") is None or b.get("longitude") is None:
        return False
    return (b.get("review_count") or 0) >= MIN_BUSINESS_REVIEWS

def step1_businesses():
    print("[1/3] Reading businesses...")
    kept = {}
    for line in read_lines(BUSINESS_FILE):
        b = json.loads(line)
        if is_target_business(b):
            kept[b["business_id"]] = b
    print(f"      {len(kept):,} Study Spots found in the whole dataset")
    return kept

def show_city_ranking(businesses, top=20):
    stats = defaultdict(lambda: [0, 0])
    for b in businesses.values():
        key = (b["city"], b["state"])
        stats[key][0] += 1
        stats[key][1] += b.get("review_count") or 0
    ranking = sorted(stats.items(), key=lambda kv: kv[1][1], reverse=True)[:top]
    print(f"\n{'City':<28}{'State':<8}{'Businesses':>12}{'~Reviews':>12}")
    print("-" * 60)
    for (city, state), (n_biz, n_rev) in ranking:
        print(f"{city:<28}{state:<8}{n_biz:>12,}{n_rev:>12,}")
    print("\nPick one or more cities or type ALL to process everything:")
    print("    python filter_yelp.py Philadelphia")
    print("    python filter_yelp.py ALL\n")

def step2_reviews(business_ids):
    print("[2/3] Reading reviews (this is the slow part, ~5 GB file)...")
    rng = random.Random(SEED)
    sample = []
    seen = 0
    for line in read_lines(REVIEW_FILE):
        r = json.loads(line)
        if r["business_id"] not in business_ids:
            continue
        
        if len(sample) < TARGET_REVIEWS:
            sample.append(line)
        else:
            j = rng.randint(0, seen)
            if j < TARGET_REVIEWS:
                sample[j] = line
        seen += 1
        
    print(f"      {seen:,} reviews match the spots -> sampled {len(sample):,}")
    if seen < TARGET_REVIEWS:
        print(f"      WARNING: fewer than {TARGET_REVIEWS:,} reviews available. ")
        
    return sample

def step3_users(user_ids):
    print("[3/3] Reading users...")
    users = []
    remaining = set(user_ids)
    for line in read_lines(USER_FILE):
        u = json.loads(line)
        if u["user_id"] in remaining:
            for field in DROP_USER_FIELDS:
                u.pop(field, None)
            users.append(u)
            remaining.discard(u["user_id"])
            if not remaining:
                break
    print(f"      {len(users):,} users kept ({len(remaining):,} review authors not found)")
    return users

def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write((row if isinstance(row, str) else json.dumps(row, ensure_ascii=False)) + "\n")

def main():
    t0 = time.time()
    args = sys.argv[1:]
    
    process_all = False
    if args and args[0].lower() == "all":
        process_all = True
        cities = []
    else:
        cities = [c.lower() for c in (args or CITIES)]

    businesses = step1_businesses()
    
    if not cities and not process_all:
        show_city_ranking(businesses)
        return
        
    if not process_all:
        businesses = {k: b for k, b in businesses.items() if b["city"].lower() in cities}
        print(f"      {len(businesses):,} left after filtering by city: {args or CITIES}")
    else:
        print(f"      Keeping ALL {len(businesses):,} spots across all cities!")

    if not businesses:
        print("No business matches those criteria.")
        return

    # Passo 2: Extrair Reviews
    review_lines = step2_reviews(set(businesses))
    reviews = [json.loads(line) for line in review_lines]

    # Passo 3: Extrair Utilizadores
    users = step3_users({r["user_id"] for r in reviews})
    valid_user_ids = {u["user_id"] for u in users}

    # 1. Contar reviews órfãs ANTES de limpar (para o sumário)
    orphan_users_count = sum(1 for r in reviews if r["user_id"] not in valid_user_ids)

    # 2. Limpar as reviews órfãs
    if orphan_users_count > 0:
        reviews = [r for r in reviews if r["user_id"] in valid_user_ids]

    # 3. SÓ AGORA cruzar com negócios para garantir que nenhum fica sem reviews
    if KEEP_ONLY_REVIEWED_BUSINESSES:
        reviewed = {r["business_id"] for r in reviews}
        businesses = {k: b for k, b in businesses.items() if k in reviewed}
        print(f"      {len(businesses):,} businesses have at least one valid sampled review")

    OUT_DIR.mkdir(exist_ok=True)
    write_jsonl(OUT_DIR / "business_filtered.jsonl", businesses.values())
    write_jsonl(OUT_DIR / "review_filtered.jsonl", reviews)
    write_jsonl(OUT_DIR / "user_filtered.jsonl", users)

    # Verificações finais
    orphan_biz = sum(1 for r in reviews if r["business_id"] not in businesses)
    with_wifi = sum(1 for b in businesses.values() if (b.get("attributes") or {}).get("WiFi"))
    with_noise = sum(1 for b in businesses.values() if (b.get("attributes") or {}).get("NoiseLevel"))

    print("\n=== Summary ===")
    print(f"Businesses : {len(businesses):,}")
    print(f"  with WiFi attribute      : {with_wifi:,}")
    print(f"  with NoiseLevel attribute: {with_noise:,}")
    print(f"Reviews    : {len(reviews):,}")
    print(f"Users      : {len(users):,}")
    print(f"Files written to: {OUT_DIR.resolve()}  ({time.time() - t0:.0f}s)")

if __name__ == "__main__":
    main()
