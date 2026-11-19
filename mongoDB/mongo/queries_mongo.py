"""
Implementação das 6 Queries no MongoDB para o Goal 3.
Inclui:
  - Criação / Verificação de índices de suporte
  - Execução das 6 queries analíticas e de pesquisa
  - Medição de tempo de resposta (latência em ms)
  - Apresentação formatada dos resultados
"""

import time
import pprint
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "studyspot"


def get_db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return client, client[DB_NAME]


def ensure_indexes(db):
    """Garante a existência de todos os índices necessários para otimizar as queries."""
    print("--- [ÍNDICES] A verificar / criar índices ---")
    
    # Q1: Geoespacial em venues (não especificar 'name' para reutilizar 'location_2dsphere' já criado pelo init_mongo_schema)
    db.venues.create_index([("location", "2dsphere")])
    
    # Q2: Comodidades (Wi-Fi)
    db.venues.create_index([("amenities.wifi", 1)])
    
    # Q3: Cidade + Estrelas + Contagem de reviews (Composto)
    db.venues.create_index([("city", 1), ("stars", -1), ("review_count", -1)])
    
    # Q4: Lookup venue_id e flags
    db.reviews.create_index([("venue_id", 1)])
    db.reviews.create_index([("mentions_outlets", 1)])
    
    # Q5: Reviews por utilizador
    db.reviews.create_index([("user_id", 1), ("date", -1)])
    
    # Q6: Reviews por venue + data (Temporal)
    db.reviews.create_index([("venue_id", 1), ("date", 1)])
    
    print(" Índices verificados/criados com sucesso.\n")


# ----------------------------------------------------------------------
# 1. Proximidade Espacial (Sorting + Spatial)
# ----------------------------------------------------------------------
def query_1_spatial(db, coordinates=(-119.7000, 34.4200), max_distance_meters=1000):
    """
    Encontrar locais abertos num raio de 1km a partir de um ponto (ex: Santa Barbara Downtown).
    Ordenados nativamente por proximidade graças ao $near.
    """
    start = time.perf_counter()
    cursor = db.venues.find(
        {
            "is_open": True,
            "location": {
                "$near": {
                    "$geometry": {
                        "type": "Point",
                        "coordinates": list(coordinates)  # [long, lat]
                    },
                    "$maxDistance": max_distance_meters
                }
            }
        },
        {
            "name": 1,
            "address": 1,
            "city": 1,
            "location.coordinates": 1,
            "is_open": 1,
            "stars": 1
        }
    )
    results = list(cursor)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms


# ----------------------------------------------------------------------
# 2. Pesquisa de Locais com "Free Wifi" (Filtering + Projection)
# ----------------------------------------------------------------------
def query_2_free_wifi(db, city="Santa Barbara"):
    """
    Pesquisar locais específicos com "free wifi" projetando os campos essenciais.
    Graças aos subdocumentos embebidos (amenities), dispensa qualquer $lookup.
    """
    start = time.perf_counter()
    filter_criteria = {"amenities.wifi": "free"}
    if city:
        filter_criteria["city"] = city

    cursor = db.venues.find(
        filter_criteria,
        {
            "name": 1,
            "address": 1,
            "city": 1,
            "amenities.wifi": 1,
            "amenities.noise_level": 1,
            "stars": 1
        }
    )
    results = list(cursor)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms


# ----------------------------------------------------------------------
# 3. Top 10 Locais por Zona (Filtering + Sorting)
# ----------------------------------------------------------------------
def query_3_top10_zone(db, city="Santa Barbara"):
    """
    Listar o top 10 de locais com melhor rating (stars) numa zona/cidade específica,
    ordenado de forma decrescente por rating e depois por número de avaliações.
    """
    start = time.perf_counter()
    cursor = db.venues.find(
        {"city": city, "stars": {"$exists": True}},
        {
            "name": 1,
            "address": 1,
            "city": 1,
            "stars": 1,
            "review_count": 1,
            "categories": 1
        }
    ).sort([("stars", -1), ("review_count", -1)]).limit(10)
    
    results = list(cursor)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms


# ----------------------------------------------------------------------
# 4. Percentagem de Reviews com "Outlets" por Cidade (Aggregation + Multi-entidade)
# ----------------------------------------------------------------------
def query_4_outlets_pct(db):
    """
    Calcula por cidade a percentagem de reviews que mencionam tomadas elétricas ("outlets").
    Usa $lookup entre reviews e venues, e agrega os resultados condicionalmente.
    Aproveita o campo booleano pré-calculado 'mentions_outlets' ou faz fallback para regex.
    """
    start = time.perf_counter()
    pipeline = [
        {
            "$lookup": {
                "from": "venues",
                "localField": "venue_id",
                "foreignField": "_id",
                "as": "venue"
            }
        },
        {"$unwind": "$venue"},
        {
            "$group": {
                "_id": "$venue.city",
                "total_reviews": {"$sum": 1},
                "outlet_reviews": {
                    "$sum": {
                        "$cond": [
                            {
                                "$or": [
                                    {"$eq": ["$mentions_outlets", True]},
                                    {"$regexMatch": {"input": "$text", "regex": "outlet", "options": "i"}}
                                ]
                            },
                            1,
                            0
                        ]
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "city": "$_id",
                "total_reviews": 1,
                "outlet_reviews": 1,
                "pct_outlets": {
                    "$round": [
                        {"$multiply": [{"$divide": ["$outlet_reviews", "$total_reviews"]}, 100]},
                        2
                    ]
                }
            }
        },
        {"$sort": {"total_reviews": -1}}
    ]
    cursor = db.reviews.aggregate(pipeline)
    results = list(cursor)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms


# ----------------------------------------------------------------------
# 5. Locais que um Utilizador Específico Frequentou (Multi-entidade / Lookup)
# ----------------------------------------------------------------------
def query_5_user_history(db, user_id=None):
    """
    Listar todos os locais onde um utilizador submeteu reviews.
    Filtra primeiro em reviews ($match precoce) e faz $lookup em venues.
    """
    # Se nenhum user_id for passado, obtemos um dinamicamente da coleção para demonstração
    if not user_id:
        sample_review = db.reviews.find_one({"user_id": {"$exists": True}})
        user_id = sample_review["user_id"] if sample_review else "demo_user"

    start = time.perf_counter()
    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$lookup": {
                "from": "venues",
                "localField": "venue_id",
                "foreignField": "_id",
                "as": "venue"
            }
        },
        {"$unwind": "$venue"},
        {
            "$project": {
                "_id": 0,
                "user_id": "$user_id",
                "venue_id": "$venue._id",
                "venue_name": "$venue.name",
                "city": "$venue.city",
                "user_stars": "$stars",
                "date": "$date"
            }
        },
        {"$sort": {"date": -1}}
    ]
    cursor = db.reviews.aggregate(pipeline)
    results = list(cursor)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms, user_id


# ----------------------------------------------------------------------
# 6. Tendência Temporal de um Estabelecimento (Aggregation + Temporal)
# ----------------------------------------------------------------------
def query_6_venue_trend(db, venue_id=None):
    """
    Analisa a evolução anual de um estabelecimento: número de reviews e rating médio por ano.
    Opera apenas sobre a coleção reviews.
    """
    if not venue_id:
        sample_review = db.reviews.find_one({"venue_id": {"$exists": True}})
        venue_id = sample_review["venue_id"] if sample_review else "demo_venue"

    start = time.perf_counter()
    pipeline = [
        {"$match": {"venue_id": venue_id}},
        {
            "$group": {
                "_id": {"$year": "$date"},
                "review_count": {"$sum": 1},
                "avg_stars": {"$avg": "$stars"}
            }
        },
        {"$sort": {"_id": 1}},
        {
            "$project": {
                "_id": 0,
                "year": "$_id",
                "review_count": 1,
                "avg_stars": {"$round": ["$avg_stars", 2]}
            }
        }
    ]
    cursor = db.reviews.aggregate(pipeline)
    results = list(cursor)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms, venue_id


# ----------------------------------------------------------------------
# OPERAÇÕES DE ESCRITA: INSERT, UPDATE, DELETE
# ----------------------------------------------------------------------
def crud_insert_review(db, venue_id=None, user_id="usr_test_goal3"):
    """
    INSERT: Insere uma nova review e propaga a alteração ao documento do venue:
      1. Insere o documento completo na coleção 'reviews'
      2. Atualiza o documento em 'venues': incrementa 'review_count' ($inc)
         e insere no array embebido 'recent_reviews' ($push com $slice: -10)
    """
    import datetime
    import uuid

    if not venue_id:
        sample_v = db.venues.find_one()
        venue_id = sample_v["_id"] if sample_v else "demo_venue"

    review_id = f"rev_test_{uuid.uuid4().hex[:6]}"
    now = datetime.datetime.now(datetime.timezone.utc)
    
    new_review = {
        "_id": review_id,
        "venue_id": venue_id,
        "user_id": user_id,
        "stars": 5,
        "useful": 0,
        "funny": 0,
        "cool": 0,
        "date": now,
        "text": "Espaço excelente com bastantes tomadas e wifi rápido para estudar!",
        "mentions_wifi": True,
        "mentions_outlets": True,
        "mentions_pastry": False
    }

    start = time.perf_counter()
    # 1. Inserir em reviews
    db.reviews.insert_one(new_review)

    # 2. Atualizar venue (incremental + array embebido de reviews recentes)
    recent_entry = {
        "review_id": review_id,
        "user_id": user_id,
        "stars": 5,
        "date": now,
        "text_snippet": new_review["text"][:200]
    }
    db.venues.update_one(
        {"_id": venue_id},
        {
            "$inc": {"review_count": 1, "amenities.outlet_mentions": 1},
            "$push": {
                "recent_reviews": {
                    "$each": [recent_entry],
                    "$slice": -10  # Mantém apenas as últimas 10
                }
            }
        }
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return review_id, venue_id, elapsed_ms


def crud_update_venue_amenities(db, venue_id):
    """
    UPDATE: Atualiza as comodidades de um venue modificando campos
    aninhados no subdocumento 'amenities' sem sobrescrever o resto do documento.
    """
    start = time.perf_counter()
    result = db.venues.update_one(
        {"_id": venue_id},
        {
            "$set": {
                "amenities.wifi": "free",
                "amenities.noise_level": "quiet"
            }
        }
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return result.modified_count, elapsed_ms


def crud_delete_review(db, review_id, venue_id):
    """
    DELETE: Remove a review criada e reverte a contagem e array recente no venue:
      1. Remove o documento de 'reviews'
      2. Decrementa o review_count no venue ($inc: -1)
      3. Remove o snippet do array embebido 'recent_reviews' ($pull)
    """
    start = time.perf_counter()
    # 1. Remover de reviews
    db.reviews.delete_one({"_id": review_id})

    # 2. Reverter no venue
    db.venues.update_one(
        {"_id": venue_id},
        {
            "$inc": {"review_count": -1, "amenities.outlet_mentions": -1},
            "$pull": {"recent_reviews": {"review_id": review_id}}
        }
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms


# ----------------------------------------------------------------------
# Execução Principal e Relatório de Benchmark
# ----------------------------------------------------------------------
def main():
    try:
        client, db = get_db()
        client.admin.command("ping")
        print(" Ligado ao MongoDB com sucesso.\n")
    except Exception as e:
        print(f" Não foi possível ligar ao MongoDB ({e}).")
        print("Garante que o mongod está a correr.")
        return

    ensure_indexes(db)

    print("=" * 60)
    print(" EXECUÇÃO DAS 6 QUERIES (GOAL 3) - MONGODB BENCHMARK")
    print("=" * 60)

    # Q1
    res1, t1 = query_1_spatial(db)
    print(f"\n[Q1] Proximidade Espacial (< 1km de Downtown Santa Barbara)")
    print(f"     Tempo: {t1:.2f} ms | Resultados: {len(res1)}")
    if res1:
        print(f"     Exemplo: {res1[0].get('name')} em {res1[0].get('address')}")

    # Q2
    res2, t2 = query_2_free_wifi(db)
    print(f"\n[Q2] Pesquisa Free Wi-Fi (Filtering + Projection)")
    print(f"     Tempo: {t2:.2f} ms | Resultados: {len(res2)}")
    if res2:
        print(f"     Exemplo: {res2[0].get('name')} (WiFi: {res2[0].get('amenities', {}).get('wifi')})")

    # Q3
    res3, t3 = query_3_top10_zone(db)
    print(f"\n[Q3] Top 10 Locais por Zona (Filtering + Sorting)")
    print(f"     Tempo: {t3:.2f} ms | Resultados: {len(res3)}")
    for i, v in enumerate(res3[:3], 1):
        print(f"     #{i}: {v.get('name')} - {v.get('stars')}  ({v.get('review_count')} reviews)")

    # Q4
    res4, t4 = query_4_outlets_pct(db)
    print(f"\n[Q4] % Reviews com Tomadas/Outlets por Cidade (Aggregation Multi-entidade)")
    print(f"     Tempo: {t4:.2f} ms | Cidades analisadas: {len(res4)}")
    for row in res4[:3]:
        print(f"     {row.get('city')}: {row.get('pct_outlets')}% com tomadas ({row.get('total_reviews')} reviews)")

    # Q5
    res5, t5, uid = query_5_user_history(db)
    print(f"\n[Q5] Histórico de Locais do Utilizador '{uid}' (Multi-entidade / Lookup)")
    print(f"     Tempo: {t5:.2f} ms | Locais visitados: {len(res5)}")
    if res5:
        print(f"     Última visita: {res5[0].get('venue_name')} ({res5[0].get('city')}) - {res5[0].get('user_stars')} ")

    # Q6
    res6, t6, vid = query_6_venue_trend(db)
    print(f"\n[Q6] Tendência Temporal do Estabelecimento '{vid}' (Aggregation + Temporal)")
    print(f"     Tempo: {t6:.2f} ms | Anos de histórico: {len(res6)}")
    for yr in res6:
        print(f"     Ano {yr.get('year')}: {yr.get('review_count')} reviews | Rating Médio: {yr.get('avg_stars')} ")

    print("\n" + "=" * 60)
    print(" OPERAÇÕES DE ESCRITA (INSERT, UPDATE, DELETE)")
    print("=" * 60)

    # INSERT
    rev_id, target_vid, t_ins = crud_insert_review(db)
    print(f"\n[INSERT] Nova Review '{rev_id}' para o Venue '{target_vid}'")
    print(f"         Tempo: {t_ins:.2f} ms")
    print(f"         Ação: Inserido em 'reviews' + atualizado 'review_count' e 'recent_reviews' em 'venues'")

    # UPDATE
    mod_count, t_upd = crud_update_venue_amenities(db, target_vid)
    print(f"\n[UPDATE] Atualização de Comodidades do Venue '{target_vid}'")
    print(f"         Tempo: {t_upd:.2f} ms | Documentos modificados: {mod_count}")
    print(f"         Ação: $set em amenities.wifi = 'free' e noise_level = 'quiet'")

    # DELETE
    t_del = crud_delete_review(db, rev_id, target_vid)
    print(f"\n[DELETE] Remoção da Review '{rev_id}'")
    print(f"         Tempo: {t_del:.2f} ms")
    print(f"         Ação: Removido de 'reviews' + revertido 'review_count' e $pull em 'venues'")

    print("\n" + "=" * 60)
    print(" RESUMO DE LATÊNCIA (MONGODB):")
    print(" --- Consultas (Read) ---")
    print(f"  Q1 (Spatial):        {t1:8.2f} ms")
    print(f"  Q2 (Free WiFi):      {t2:8.2f} ms")
    print(f"  Q3 (Top 10):         {t3:8.2f} ms")
    print(f"  Q4 (Pct Outlets):    {t4:8.2f} ms")
    print(f"  Q5 (User History):   {t5:8.2f} ms")
    print(f"  Q6 (Temporal Trend): {t6:8.2f} ms")
    print(" --- Operações de Escrita (Write) ---")
    print(f"  INSERT (Review+Venue): {t_ins:6.2f} ms")
    print(f"  UPDATE (Amenities):    {t_upd:6.2f} ms")
    print(f"  DELETE (Review+Venue): {t_del:6.2f} ms")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
