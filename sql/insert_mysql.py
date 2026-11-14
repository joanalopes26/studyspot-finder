
import json
import mysql.connector
import time
import re
import os

# ─────────────────────────── REGEX ───────────────────────────

RE_WIFI = re.compile(
    r"\b(wi[-\s]?fi|wifi|wireless\s+internet|internet)\b",
    re.IGNORECASE
)

RE_OUTLETS = re.compile(
    r"\b(outlets?|plugs?|charging\s+(?:station|port)|"
    r"power\s+(?:outlet|strip)|sockets?|electrical\s+outlet)\b",
    re.IGNORECASE
)

RE_PASTRY = re.compile(
    r"\b(cakes?|pastry|pastries|croissants?|muffins?|scones?|"
    r"doughnuts?|donuts?|cookies?|pies?|tarts?|biscuits?|"
    r"danish|brownies?|cupcakes?|macarons?)\b",
    re.IGNORECASE
)


start_insert = time.time()

cnx = mysql.connector.connect(
    host="localhost",
    user="root",
    password="BDA2627_68059",  #alterar para a password do MySQL
    database="studyspot"
)

cursor = cnx.cursor()


#tabela USER

start = time.time()

dados_users = []

with open("filtered/user_filtered.jsonl", "r", encoding="utf-8") as f:
    for linha in f:
        if not linha.strip():
            continue

        u = json.loads(linha)

        dados_users.append((
            u["user_id"],
            (u.get("name") or "Unknown")[:100],
            u.get("review_count", 0),
            u["yelping_since"],
            u.get("average_stars")
        ))

sql_user = """
    INSERT INTO User (user_id, name, review_count, yelping_since, average_stars)
    VALUES (%s, %s, %s, %s, %s)
"""

cursor.executemany(sql_user, dados_users)
cnx.commit()

end = time.time()
print(f"Users inseridos, tempo total: {end - start:.4f} segundos")


#tabela BUSINESS (recolher categorias/amenities)

start = time.time()

dados_business = []
amenities_temp = []
categorias_unicas = set()
ligacoes_categorias = set()

with open("filtered/business_filtered.jsonl", "r", encoding="utf-8") as f:
    for linha in f:
        if not linha.strip():
            continue

        b = json.loads(linha)

        bid = b["business_id"]
        ponto = f"POINT({b['latitude']} {b['longitude']})"

        dados_business.append((
            bid,
            b["name"][:255],
            (b.get("address") or "")[:255],
            (b.get("city") or "")[:100],
            (b.get("state") or "")[:3],
            (b.get("postal_code") or "")[:10],
            ponto,
            b["stars"],
            b.get("review_count", 0),
            b.get("is_open", 1)
        ))

        #limpar valores de wifi e noise ("u'free'" -> "free")
        attrs = b.get("attributes") or {}

        wifi = str(attrs.get("WiFi", "")).replace(
            "u'", ""
        ).replace("'", "").replace('"', "").lower()

        wifi = wifi if wifi in ("free", "paid", "no") else None

        noise = str(attrs.get("NoiseLevel", "")).replace(
            "u'", ""
        ).replace("'", "").replace('"', "").lower()

        noise = noise if noise in (
            "quiet", "average", "loud", "very_loud"
        ) else None

        amenities_temp.append((bid, wifi, noise))

        #guardar categorias para inserir
        for cat in (b.get("categories") or "").split(","):
            cat = cat.strip()[:100]

            if cat:
                categorias_unicas.add(cat)
                ligacoes_categorias.add((bid, cat))


sql_business = """
    INSERT INTO Business (
        business_id, name, address, city, state, postal_code,
        location, stars, review_count, is_open
    )
    VALUES (%s, %s, %s, %s, %s, %s, ST_GeomFromText(%s, 4326), %s, %s, %s)
"""

cursor.executemany(sql_business, dados_business)
cnx.commit()

end = time.time()
print(f"Businesses inseridos, tempo total: {end - start:.4f} segundos")


#tabelas CATEGORY e BUSINESSCATEGORY

start = time.time()

sql_cat = "INSERT INTO Category (name) VALUES (%s)"

cursor.executemany(sql_cat, [(c,) for c in categorias_unicas])
cnx.commit()

#procura os IDs gerados pelo AUTO_INCREMENT para preencher a tabela de ligação
cursor.execute("SELECT name, category_id FROM Category")
mapa_categorias = dict(cursor.fetchall())

dados_biz_cat = [
    (bid, mapa_categorias[cat])
    for bid, cat in ligacoes_categorias
]

sql_biz_cat = """
    INSERT INTO BusinessCategory (business_id, category_id)
    VALUES (%s, %s)
"""

cursor.executemany(sql_biz_cat, dados_biz_cat)
cnx.commit()

end = time.time()
print(f"Categorias associadas, tempo total: {end - start:.4f} segundos")


#ler REVIEWS, inserir BUSINESS_AMENITIES e inserir REVIEW

start = time.time()

dados_reviews = []
contagem_outlets = {}

with open("filtered/review_filtered.jsonl", "r", encoding="utf-8") as f:
    for linha in f:
        if not linha.strip():
            continue

        r = json.loads(linha)

        bid = r["business_id"]
        texto = r.get("text") or ""

        #pesquisa de palavras-chave no texto
        m_wifi = bool(RE_WIFI.search(texto))
        m_outlets = bool(RE_OUTLETS.search(texto))
        m_pastry = bool(RE_PASTRY.search(texto))

        if m_outlets:
            contagem_outlets[bid] = contagem_outlets.get(bid, 0) + 1

        dados_reviews.append((
            r["review_id"],
            bid,
            r["user_id"],
            r["stars"],
            r.get("useful", 0),
            r.get("funny", 0),
            r.get("cool", 0),
            r["date"],
            texto,
            m_wifi,
            m_outlets,
            m_pastry
        ))



#inserir dados de business amenities
dados_amenities = [
    (bid, wifi, noise, contagem_outlets.get(bid, 0))
    for bid, wifi, noise in amenities_temp
]

sql_amenities = """
    INSERT INTO Business_Amenities (
        business_id, wifi, noise_level, outlet_mentions
    )
    VALUES (%s, %s, %s, %s)
"""

cursor.executemany(sql_amenities, dados_amenities)
cnx.commit()


#tabela REVIEW
sql_review = """
    INSERT INTO Review (
        review_id, business_id, user_id, stars, useful, funny, cool,
        review_date, text, mentions_wifi, mentions_outlets, mentions_pastry
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

cursor.executemany(sql_review, dados_reviews)
cnx.commit()

end = time.time()
print(f"Amenities e Reviews inseridas, tempo total: {end - start:.4f} segundos")


cursor.close()
cnx.close()

end_insert = time.time()

print(" ")
print(f"Tempo total da execução: {end_insert - start_insert:.4f} segundos")
