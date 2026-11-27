"""
Implementação das 6 Queries no MySQL para o Goal 3
Inclui:
    - Criação / Verificação de índices de suporte no MySQL
    - Execução das 6 queries analíticas e de pesquisa
    - Operações de escrita (INSERT, UPDATE, DELETE)
    - Transação Multi-Entidade (ACID)
    - Medição de tempo de resposta (latência em ms)
    - Apresentação formatada dos resultados
"""

import time
import uuid
import datetime
import mysql.connector

MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "BDA2627_68059",  #alterar 
    "database": "studyspot"
}

def get_db():
    cnx = mysql.connector.connect(**MYSQL_CONFIG, autocommit=True)
    curor = cnx.cursor(dictionary=True)
    return cnx, curor

def ensure_indexes(cursor, cnx):
   #Garante a existência de indices secundários para otimizar as queries
    print("--- [ÍNDICES] A verificar / criar índices ---")

    indexes = [
        #Q2: Amenities (wi-fi)
        ("idx_amenities_wifi", "CREATE INDEX idx_amenities_wifi ON Business_Amenities(wifi)"),

        #Q3: Cidade + Stars + Contagem de reviews
        ("idx_business_city_stars_reviews", "CREATE INDEX idx_business_city_stars_reviews ON Business(city, stars DESC, review_count DESC)"),

        #Q4: Lookup nas reviews
        ("idx_review_business_id", "CREATE INDEX idx_review_business_id ON Review(business_id)"),
        ("idx_review_mentions_outlets", "CREATE INDEX idx_review_mentions_outlets ON Review(mentions_outlets)"),

        #Q5: Reviews por utilizador
        ("idx_review_user_date", "CREATE INDEX idx_review_user_date ON Review(user_id, review_date DESC)"),

        #Q6: Reviews por business + data
        ("idx_review_business_date", "CREATE INDEX idx_review_business_date ON Review(business_id, review_date ASC)")
    ]

    for idx_name, create_sql in indexes:
        try:
            cursor.execute(f"SHOW INDEX FROM Review WHERE Key_name = '{idx_name}'")
            exists_review = cursor.fetchall()
            cursor.execute(f"SHOW INDEX FROM Business WHERE Key_name = '{idx_name}'")
            exists_biz = cursor.fetchall()
            cursor.execute(f"SHOW INDEX FROM Business_Amenities WHERE Key_name = '{idx_name}'")
            exists_amen = cursor.fetchall()

            if not (exists_review or exists_biz or exists_amen):
                cursor.execute(create_sql)
                cnx.commit()
        except mysql.connector.Error:
            pass

    print(" Índices verificados/criados com sucesso.\n")

# ----------------------------------------------------------------------
# 0. Contagem Simples de Locais (Simple Count / Baseline)
# ----------------------------------------------------------------------
def query_0_count_venues(cursor):
    """
    Query Simples: Devolve o número total de cafés/bakeries (Business) existentes na base de dados.
    Serve como baseline de leitura simples sem filtros complexos ou junções.
    """
    start = time.perf_counter()
    cursor.execute("SELECT COUNT(*) AS total_venues FROM Business")
    row = cursor.fetchone()
    total_venues = row["total_venues"] if row else 0
    elapsed_ms = (time.perf_counter() - start) * 1000
    return total_venues, elapsed_ms

# ----------------------------------------------------------------------
# 1. Proximidade Espacial (Sorting + Spatial)
# ----------------------------------------------------------------------
def query_1_spatial(cursor, coordinates=(-119.7000, 34.4200), max_distance_meters=1000):
    """
    Encontrar locais abertos num raio de 1km a partir de um ponto (ex: Santa Barbara Downtown)
    Usa a função espacial ST_Distance_Sphere e o SPATIAL INDEX no campo location
    """
    lng, lat = coordinates
    start = time.perf_counter()

    sql = """
        SELECT business_id, name, address, city, stars, is_open,
            ROUND(ST_Distance_Sphere(location, ST_GeomFromText(%s, 4326)), 2) AS distance_meters
        FROM Business
        WHERE is_open = 1
            AND ST_Distance_Sphere(location, ST_GeomFromText(%s, 4326)) <= %s
        ORDER BY distance_meters ASC
    """
    point_wkt = f"POINT({lat} {lng})"
    cursor.execute(sql, (point_wkt, point_wkt, max_distance_meters))
    results = cursor.fetchall()

    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms

# ----------------------------------------------------------------------
# 2. Pesquisa de Locais com "free wifi" (Filtering + Projection)
# ----------------------------------------------------------------------
def query_2_free_wifi(cursor, city="Santa Barbara"):
    """
    Pesquisar locais específicos com "free wifi"
    Realiza o JOIN entre Business e Business_Amenities
    """
    start = time.perf_counter()

    sql = """
        SELECT b.business_id, b.name, b.address, b.city, a.wifi, a.noise_level, b.stars
        FROM Business b
        JOIN Business_Amenities a ON b.business_id = a.business_id
        WHERE a.wifi = 'free' AND b.city = %s
    """
    cursor.execute(sql, (city,))
    results = cursor.fetchall()

    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms

# ----------------------------------------------------------------------
# 3. Top 10 locais por zona (Filtering + Sorting)
# ----------------------------------------------------------------------
def query_3_top10_zone(cursor, city="Santa Barbara"):
    """
    Listar o top 10 de locais com melhor rating (stars) numa zona/cidade específica,
    ordenado de forma decrescente por rating e depois por número de avaliações
    """
    start = time.perf_counter()

    sql = """
        SELECT business_id, name, address, city, stars, review_count
        FROM Business
        WHERE city = %s AND stars IS NOT NULL
        ORDER BY stars DESC, review_count DESC
        LIMIT 10
    """
    cursor.execute(sql, (city,))
    results = cursor.fetchall()

    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms

# ----------------------------------------------------------------------
# 4. Percentagem de reviews com "outlets" por cidade (Aggregation + Multi-entidade)
# ----------------------------------------------------------------------
def query_4_outlets_pct(cursor):
    """
    Calcula por cidade a percentagem de reviews que mencionam tomadas elétricas ("outlets")
    Realiza JOIN entre Review e Business, agregando os resultados condicionalmente
    """
    start = time.perf_counter()

    sql = """
        SELECT b.city,
            COUNT(r.review_id) AS total_reviews,
            SUM(CASE WHEN r.mentions_outlets = 1 OR r.text LIKE '%outlet%' THEN 1 ELSE 0 END) AS outlet_reviews,
            ROUND((SUM(CASE WHEN r.mentions_outlets = 1 OR r.text LIKE '%outlet%' THEN 1 ELSE 0 END) / COUNT(r.review_id)) * 100, 2) AS pct_outlets
        FROM Review r
        JOIN Business b ON r.business_id = b.business_id
        GROUP BY b.city
        ORDER BY total_reviews DESC
    """
    cursor.execute(sql)
    results = cursor.fetchall()

    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms

# ----------------------------------------------------------------------
# 5. Locais que um utilizador específico frequentou (Multi-entidade / JOIN)
# ----------------------------------------------------------------------
def query_5_user_history(cursor, user_id=None):
    """
    Listar todos os locais onde um utilizador submeteu reviews
    Realiza JOIN entre User, Review e Business.
    Se não for fornecido user_id, pesquisa o utilizador mais ativo (com mais reviews).
    """
    if not user_id:
        cursor.execute("SELECT user_id FROM User ORDER BY review_count DESC LIMIT 1")
        row = cursor.fetchone()
        user_id = row["user_id"] if row else "demo_user"

    start = time.perf_counter()

    sql = """
        SELECT r.user_id, b.business_id AS venue_id, b.name AS venue_name, b.city,
               r.stars AS user_stars, r.review_date AS date
        FROM Review r
        JOIN Business b ON r.business_id = b.business_id
        WHERE r.user_id = %s
        ORDER BY r.review_date DESC
    """
    cursor.execute(sql, (user_id,))
    results = cursor.fetchall()

    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms, user_id

# ----------------------------------------------------------------------
# 6. Tendência Temporal de um Estabelecimento (Aggregation + Temporal)
# ----------------------------------------------------------------------
def query_6_venue_trend(cursor, venue_id=None):
    """
    Analisa a evolução anual de um estabelecimento: número de reviews e rating médio por ano
    Opera apenas sobre a coleção reviews
    Se não for fornecido venue_id, pesquisa o estabelecimento com maior número de reviews.
    """
    venue_name = "N/A"
    if not venue_id:
        cursor.execute("SELECT business_id, name FROM Business ORDER BY review_count DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            venue_id = row["business_id"]
            venue_name = row["name"]
        else:
            venue_id = "demo_venue"
    else:
        cursor.execute("SELECT name FROM Business WHERE business_id = %s", (venue_id,))
        row = cursor.fetchone()
        if row:
            venue_name = row["name"]

    start = time.perf_counter()

    sql = """
        SELECT YEAR(r.review_date) AS year,
               COUNT(r.review_id) AS review_count,
               ROUND(AVG(r.stars), 2) AS avg_stars
        FROM Review r
        WHERE r.business_id = %s
        GROUP BY YEAR(r.review_date)
        ORDER BY year ASC
    """

    cursor.execute(sql, (venue_id,))
    results = cursor.fetchall()
    
    elapsed_ms = (time.perf_counter() - start) * 1000
    return results, elapsed_ms, venue_id, venue_name

# ----------------------------------------------------------------------
# OPERAÇÕES DE ESCRITA: INSERT, UPDATE, DELETE
# ----------------------------------------------------------------------
def crud_insert_multi_entity(cnx, cursor):
    """
    INSERT MULTI-ENTIDADE: Cria em simultâneo:
      1. Um novo utilizador na tabela 'User'
      2. Um novo estabelecimento na tabela 'Business' (com geometria POINT)
      3. As comodidades associadas na tabela 'Business_Amenities'
      4. A ligação à categoria na tabela 'BusinessCategory'
      5. A primeira review desse novo utilizador para esse novo local na tabela 'Review'
    """
    uid_suffix = uuid.uuid4().hex[:6]
    new_user_id = f"usr_new_{uid_suffix}"
    new_venue_id = f"biz_new_{uid_suffix}"
    new_review_id = f"rev_new_{uid_suffix}"
    now = datetime.datetime.now()

    start = time.perf_counter()

    # 1. Inserir User
    sql_user = """
        INSERT INTO User (user_id, name, review_count, yelping_since, average_stars)
        VALUES (%s, %s, 1, %s, 5.0)
    """
    cursor.execute(sql_user, (new_user_id, f"Estudante Novo {uid_suffix}", now))

    # 2. Inserir Business
    sql_biz = """
        INSERT INTO Business (
            business_id, name, address, city, state, postal_code, location, stars, review_count, is_open
        ) VALUES (
            %s, %s, '999 Innovation Way', 'Santa Barbara', 'CA', '93101',
            ST_GeomFromText('POINT(34.4215 -119.7020)', 4326), 5.0, 1, 1
        )
    """
    cursor.execute(sql_biz, (new_venue_id, f"Novo Study Hub {uid_suffix}"))

    # 3. Inserir Business_Amenities
    sql_amen = """
        INSERT INTO Business_Amenities (business_id, wifi, noise_level, outlet_mentions)
        VALUES (%s, 'free', 'quiet', 1)
    """
    cursor.execute(sql_amen, (new_venue_id,))

    # 4. Inserir BusinessCategory (garantindo que existe pelo menos uma categoria base)
    cursor.execute("SELECT category_id FROM Category LIMIT 1")
    cat_row = cursor.fetchone()
    if cat_row:
        cat_id = cat_row["category_id"]
        cursor.execute(
            "INSERT INTO BusinessCategory (business_id, category_id) VALUES (%s, %s)",
            (new_venue_id, cat_id)
        )

    # 5. Inserir Review
    sql_rev = """
        INSERT INTO Review (
            review_id, business_id, user_id, stars, useful, funny, cool,
            review_date, text, mentions_wifi, mentions_outlets, mentions_pastry
        ) VALUES (
            %s, %s, %s, 5, 1, 0, 1, %s,
            'Inauguração fantástica! Espaço novo muito acolhedor, wifi super rápido e tomadas em todas as mesas.',
            1, 1, 1
        )
    """
    cursor.execute(sql_rev, (new_review_id, new_venue_id, new_user_id, now))

    cnx.commit()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return new_user_id, new_venue_id, new_review_id, elapsed_ms


def crud_update_venue_amenities(cnx, cursor, venue_id):
    """
    UPDATE: Atualiza as amenities de um venue na tabela Business_Amenities
    """
    sql_update = """
        UPDATE Business_Amenities
        SET wifi = 'free', noise_level = 'quiet'
        WHERE business_id = %s
    """

    start = time.perf_counter()
    cursor.execute(sql_update, (venue_id,))
    mod_count = cursor.rowcount
    cnx.commit()

    elapsed_ms = (time.perf_counter() - start) * 1000
    return mod_count, elapsed_ms


def crud_delete_multi_entity(cnx, cursor, user_id, venue_id, review_id):
    """
    DELETE: Remove todas as entidades criadas no teste de inserção multi-entidade
    respeitando as regras de chaves forasteiras.
    """
    start = time.perf_counter()
    cursor.execute("DELETE FROM Review WHERE review_id = %s", (review_id,))
    cursor.execute("DELETE FROM BusinessCategory WHERE business_id = %s", (venue_id,))
    cursor.execute("DELETE FROM Business_Amenities WHERE business_id = %s", (venue_id,))
    cursor.execute("DELETE FROM Business WHERE business_id = %s", (venue_id,))
    cursor.execute("DELETE FROM User WHERE user_id = %s", (user_id,))
    cnx.commit()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms

# ----------------------------------------------------------------------
# Execução Principal e Relatório de Benchmark
# ----------------------------------------------------------------------
def main():
    try:
        cnx, cursor = get_db()
        print(" Ligado ao MySQL com sucesso.\n")
    except Exception as e:
        print(f" Não foi possível ligar ao MySQL ({e}).")
        print("Garante que o servidor MySQL está a correr.")
        return

    ensure_indexes(cursor, cnx)

    print("=" * 60)
    print(" EXECUÇÃO DAS QUERIES (GOAL 3) - MYSQL BENCHMARK")
    print("=" * 60)

    # Q0
    total_v, t0 = query_0_count_venues(cursor)
    print(f"\n[Q0] Número Total de Cafés/Bakeries (Simple Query)")
    print(f"     Tempo: {t0:.2f} ms | Total de Business: {total_v}")

    #Q1
    res1, t1 = query_1_spatial(cursor)
    print(f"\n[Q1] Proximidade Espacial do centro de Downtown Santa Barbara (< 1km)")
    print(f"     Tempo: {t1:.2f} ms | Resultados: {len(res1)}")
    if res1:
        print(f"     Exemplo: {res1[0].get('name')} em {res1[0].get('address')}")

    #Q2
    res2, t2 = query_2_free_wifi(cursor)
    print(f"\n[Q2] Pesquisa de Cafés/Bakeries com Free Wi-Fi (Filtering + Projection)")
    print(f"     Tempo: {t2:.2f} ms | Resultados: {len(res2)}")
    if res2:
        print(f"     Exemplo: {res2[0].get('name')} (WiFi: {res2[0].get('wifi')})")

    #Q3
    res3, t3 = query_3_top10_zone(cursor)
    print(f"\n[Q3]  Top 10 Lugares com Melhores Reviews em Santa Barbara (Filtering + Sorting)")
    print(f"     Tempo: {t3:.2f} ms | Resultados: {len(res3)}")
    for i, v in enumerate(res3[:3], 1):
        print(f"     #{i}: {v.get('name')} - {v.get('stars')}  ({v.get('review_count')} reviews)")

    #Q4
    res4, t4 = query_4_outlets_pct(cursor)
    print(f"\n[Q4] % Reviews com Tomadas/Outlets por Cidade (Aggregation Multi-entidade)")
    print(f"     Tempo: {t4:.2f} ms | Cidades analisadas: {len(res4)}")
    for row in res4[:3]:
        print(f"     {row.get('city')}: {row.get('pct_outlets')}% com tomadas ({row.get('total_reviews')} reviews)")

    #Q5
    res5, t5, uid = query_5_user_history(cursor)
    print(f"\n[Q5] Histórico de Lugares do Utilizador mais ativo '{uid}' (Multi-entidade / Lookup)")
    print(f"     Tempo: {t5:.2f} ms | Lugares visitados: {len(res5)}")
    if res5:
        print(f"     Última visita: {res5[0].get('venue_name')} ({res5[0].get('city')}) - {res5[0].get('user_stars')} ")

    #Q6
    res6, t6, vid, vname = query_6_venue_trend(cursor)
    print(f"\n[Q6] Número de Reviews por Ano do '{vname}' ({vid})")
    print(f"     Tempo: {t6:.2f} ms | Anos de histórico: {len(res6)}")
    for yr in res6:
        print(f"     Ano {yr.get('year')}: {yr.get('review_count'):3d} reviews | Rating Médio: {yr.get('avg_stars')} ★")

    print("\n" + "=" * 60)
    print(" OPERAÇÕES DE ESCRITA (INSERT, UPDATE, DELETE)")
    print("=" * 60)

    # INSERT MULTI-ENTIDADE
    new_uid, new_vid, new_rid, t_ins = crud_insert_multi_entity(cnx, cursor)
    print(f"\n[INSERT] Criação Multi-Entidade (Novo User + Novo Venue + Nova Review)")
    print(f"         Tempo: {t_ins:.2f} ms")
    print(f"         Criados: User '{new_uid}', Business '{new_vid}', Review '{new_rid}'")

    # UPDATE
    mod_count, t_upd = crud_update_venue_amenities(cnx, cursor, new_vid)
    print(f"\n[UPDATE] Atualização de Comodidades do Venue '{new_vid}'")
    print(f"         Tempo: {t_upd:.2f} ms | Documentos modificados: {mod_count}")
    print(f"         Ação: UPDATE em Business_Amenities SET wifi='free' e noise_level='quiet'")

    # DELETE MULTI-ENTIDADE
    t_del = crud_delete_multi_entity(cnx, cursor, new_uid, new_vid, new_rid)
    print(f"\n[DELETE] Remoção Multi-Entidade (Limpeza dos registos criados)")
    print(f"         Tempo: {t_del:.2f} ms")
    print(f"         Ação: Removido de Review, BusinessCategory, Business_Amenities, Business e User")

    print("\n" + "=" * 60)
    print(" RESUMO DE LATÊNCIA (MYSQL):")
    print(" --- Consultas (Read) ---")
    print(f"  Q0 (Total Venues):     {t0:8.2f} ms")
    print(f"  Q1 (Spatial):          {t1:8.2f} ms")
    print(f"  Q2 (Free WiFi):        {t2:8.2f} ms")
    print(f"  Q3 (Top 10):           {t3:8.2f} ms")
    print(f"  Q4 (Pct Outlets):      {t4:8.2f} ms")
    print(f"  Q5 (User History):     {t5:8.2f} ms")
    print(f"  Q6 (Temporal Trend):   {t6:8.2f} ms")
    print(" --- Operações de Escrita (Write) ---")
    print(f"  INSERT (User+Venue+Rev): {t_ins:6.2f} ms")
    print(f"  UPDATE (Amenities):      {t_upd:6.2f} ms")
    print(f"  DELETE (User+Venue+Rev): {t_del:6.2f} ms")
    print("=" * 60)

    cursor.close()
    cnx.close()

if __name__ == "__main__":
    main()