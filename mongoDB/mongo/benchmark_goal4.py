"""

1. FASE BASELINE (SEM ÍNDICES SECUNDÁRIOS):
   - Remove todos os índices secundários criados (mantem apenas _id e geoespacial 2dsphere obrigatório para a Q1)
   - Mede o espaço inicial ocupado em disco pelos índices (totalIndexSize)
   - Extrai o plano de execução (.explain("executionStats")) para as queries chave
   - Executa 5 iterações de cada query (Q0 a Q6) e operações CRUD, calculando a média

2. FASE PÓS-OTIMIZAÇÃO (COM ÍNDICES SECUNDÁRIOS):
   - Cria os índices propostos:
        Q2: {"amenities.wifi": 1}
        Q3: {"city": 1, "stars": -1, "review_count": -1} (Equality, Sort, Range)
        Q4, Q6: {"venue_id": 1}, {"venue_id": 1, "date": 1}
        Q5: {"user_id": 1, "date": -1}
   - Mede o novo espaço em disco ocupado pelos índices
   - Extrai o novo plano de execução (.explain("executionStats")) q comprova a transição de COLLSCAN para IXSCAN
   - Executa 5 vezes cada query e operações CRUD, e calcula a média

3. RELATÓRIO FINAL:
   - Apresenta uma tabela comparativa com:
       * Tempos Baseline vs Otimizado (ms)
       * Variação percentual (%) - Ganho nas leituras vs Custo nas escritas
       * Comparação de Query Plans
       * Comparação de Armazenamento em Disco
   - Guarda em 'mongoDB/mongo/goal4_mongodb_results.txt'.

"""

import sys
import time
import pprint
from pymongo import MongoClient
from queries_mongo import (
    get_db,
    query_0_count_venues,
    query_1_spatial,
    query_2_free_wifi,
    query_3_top10_zone,
    query_4_outlets_pct,
    query_5_user_history,
    query_6_venue_trend,
    crud_insert_multi_entity,
    crud_update_venue_amenities,
    crud_delete_multi_entity
)

N_ITERACOES = 5

def drop_secondary_indexes(db):
    """Remove índices secundários, mantendo apenas _id_ e location_2dsphere (Q1)."""
    print("\n--- A remover índices secundários para teste BASELINE ---")
    
    # Em venues
    for idx in list(db.venues.list_indexes()):
        name = idx["name"]
        if name not in ("_id_", "location_2dsphere", "idx_venues_geo"):
            try:
                db.venues.drop_index(name)
                print(f"  [venues] Removido índice: {name}")
            except Exception as e:
                pass

    # Em reviews
    for idx in list(db.reviews.list_indexes()):
        name = idx["name"]
        if name != "_id_":
            try:
                db.reviews.drop_index(name)
                print(f"  [reviews] Removido índice: {name}")
            except Exception as e:
                pass
    print(" Índices secundários removidos com sucesso.")


def create_proposed_indexes(db):

    print("\n--- A criar índices secundários para teste PÓS-OTIMIZAÇÃO ---")
    
    # Q2: Amenities (Wi-Fi)
    db.venues.create_index([("amenities.wifi", 1)], name="idx_venues_wifi")
    print("  [venues] Criado índice simples: amenities.wifi")

    # Q3: Composto (Equality, Sort, Range) para cidade + rating + reviews
    db.venues.create_index(
        [("city", 1), ("stars", -1), ("review_count", -1)],
        name="idx_venues_city_rating"
    )
    print("  [venues] Criado índice composto: city + stars + review_count")

    # Q4 e Q6: Referência a venue_id em reviews
    db.reviews.create_index([("venue_id", 1)], name="idx_reviews_venue_id")
    print("  [reviews] Criado índice de referência: venue_id")

    # Q5: Histórico de utilizador por data
    db.reviews.create_index([("user_id", 1), ("date", -1)], name="idx_reviews_user_date")
    print("  [reviews] Criado índice composto: user_id + date")

    # Q6: Temporal por venue
    db.reviews.create_index([("venue_id", 1), ("date", 1)], name="idx_reviews_venue_date")
    print("  [reviews] Criado índice composto: venue_id + date")

    print(" Índices propostos criados com sucesso.")


def get_storage_stats(db):
    """Obtém métricas de espaço em disco (KB) das coleções e índices."""
    v_stats = db.command("collstats", "venues")
    r_stats = db.command("collstats", "reviews")

    venues_idx_kb = v_stats.get("totalIndexSize", 0) / 1024
    reviews_idx_kb = r_stats.get("totalIndexSize", 0) / 1024
    total_idx_kb = venues_idx_kb + reviews_idx_kb

    return {
        "venues_idx_kb": venues_idx_kb,
        "reviews_idx_kb": reviews_idx_kb,
        "total_idx_kb": total_idx_kb
    }


def extract_query_plans(db):
    """Extrai planos de execução usando explain para Q2 e Q3."""
    plans = {}

    # Plan Q2: Free Wi-Fi em Santa Barbara (usando comando explain para compatibilidade com todas as versões do PyMongo)
    exp_q2 = db.command(
        "explain",
        {
            "find": "venues",
            "filter": {"amenities.wifi": "free", "city": "Santa Barbara"},
            "projection": {"name": 1, "address": 1, "city": 1, "amenities.wifi": 1}
        },
        verbosity="executionStats"
    )
    
    stats_q2 = exp_q2.get("executionStats", {})
    plans["q2"] = {
        "stage": stats_q2.get("executionStages", {}).get("stage", "UNKNOWN"),
        "totalDocsExamined": stats_q2.get("totalDocsExamined", 0),
        "totalKeysExamined": stats_q2.get("totalKeysExamined", 0),
        "nReturned": stats_q2.get("nReturned", 0),
        "executionTimeMillis": stats_q2.get("executionTimeMillis", 0)
    }

    # Plan Q3: Top 10 por Zona
    exp_q3 = db.command(
        "explain",
        {
            "find": "venues",
            "filter": {"city": "Santa Barbara", "stars": {"$exists": True}},
            "sort": {"stars": -1, "review_count": -1},
            "limit": 10,
            "projection": {"name": 1, "address": 1, "city": 1, "stars": 1, "review_count": 1}
        },
        verbosity="executionStats"
    )

    stats_q3 = exp_q3.get("executionStats", {})
    stage_q3 = stats_q3.get("executionStages", {}).get("stage", "UNKNOWN")
    has_sort_stage = "SORT" in str(stats_q3.get("executionStages", {}))
    
    plans["q3"] = {
        "stage": stage_q3,
        "has_in_memory_sort": has_sort_stage,
        "totalDocsExamined": stats_q3.get("totalDocsExamined", 0),
        "totalKeysExamined": stats_q3.get("totalKeysExamined", 0),
        "nReturned": stats_q3.get("nReturned", 0),
        "executionTimeMillis": stats_q3.get("executionTimeMillis", 0)
    }

    return plans


def run_benchmark_cycle(db, client):
    """Executa todas as operações N_ITERACOES vezes e calcula a média de latência (ms)."""
    tempos = {
        "Q0": [], "Q1": [], "Q2": [], "Q3": [], "Q4": [], "Q5": [], "Q6": [],
        "INSERT": [], "UPDATE": [], "DELETE": []
    }

    # Pre-identificar utilizador e local chave para consistência
    top_u = db.users.find_one(sort=[("review_count", -1)])
    uid = top_u["_id"] if top_u else None

    top_v = db.venues.find_one(sort=[("review_count", -1)])
    vid = top_v["_id"] if top_v else None

    print(f"  A executar {N_ITERACOES} iterações para cálculo de médias...")

    for i in range(N_ITERACOES):
        # Q0
        _, t0 = query_0_count_venues(db)
        tempos["Q0"].append(t0)

        # Q1
        _, t1 = query_1_spatial(db)
        tempos["Q1"].append(t1)

        # Q2
        _, t2 = query_2_free_wifi(db)
        tempos["Q2"].append(t2)

        # Q3
        _, t3 = query_3_top10_zone(db)
        tempos["Q3"].append(t3)

        # Q4
        _, t4 = query_4_outlets_pct(db)
        tempos["Q4"].append(t4)

        # Q5
        _, t5, _ = query_5_user_history(db, user_id=uid)
        tempos["Q5"].append(t5)

        # Q6
        _, t6, _, _ = query_6_venue_trend(db, venue_id=vid)
        tempos["Q6"].append(t6)

        # INSERT
        new_u, new_v, new_r, t_ins = crud_insert_multi_entity(db)
        tempos["INSERT"].append(t_ins)

        # UPDATE
        _, t_upd = crud_update_venue_amenities(db, new_v)
        tempos["UPDATE"].append(t_upd)

        # DELETE
        t_del = crud_delete_multi_entity(db, new_u, new_v, new_r)
        tempos["DELETE"].append(t_del)

    # Calcular médias
    medias = {k: sum(v) / len(v) for k, v in tempos.items()}
    return medias


def main():
    print("=" * 75)
    print(" GOAL 4 - BENCHMARK & QUERY OPTIMISATION (MONGODB)")
    print("=" * 75)

    client, db = get_db()
    try:
        client.admin.command("ping")
        print(" Ligação ao MongoDB estabelecida com sucesso.")
    except Exception as e:
        print(f" Erro ao ligar ao MongoDB: {e}")
        return

    # =========================================================================
    # 1. BASELINE (SEM ÍNDICES)
    # =========================================================================
    drop_secondary_indexes(db)
    storage_before = get_storage_stats(db)
    plans_before = extract_query_plans(db)
    medias_before = run_benchmark_cycle(db, client)

    # =========================================================================
    # 2. PÓS-OTIMIZAÇÃO (COM ÍNDICES)
    # =========================================================================
    create_proposed_indexes(db)
    storage_after = get_storage_stats(db)
    plans_after = extract_query_plans(db)
    medias_after = run_benchmark_cycle(db, client)

    # =========================================================================
    # 3. RELATÓRIO E TABELA COMPARATIVA
    # =========================================================================
    output_lines = []
    output_lines.append("\n" + "=" * 75)
    output_lines.append(" TABELA COMPARATIVA DE DESEMPENHO (GOAL 4 - MONGODB)")
    output_lines.append("=" * 75)
    output_lines.append(f"{'Operação / Query':<25} | {'Baseline (ms)':<14} | {'Otimizado (ms)':<14} | {'Variação':<12}")
    output_lines.append("-" * 75)

    for op in ["Q0", "Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "INSERT", "UPDATE", "DELETE"]:
        t_b = medias_before[op]
        t_a = medias_after[op]
        
        if t_b > 0:
            diff = ((t_a - t_b) / t_b) * 100
            diff_str = f"{diff:+.1f}%"
        else:
            diff_str = "N/A"

        # Legenda amigável
        nomes = {
            "Q0": "Q0: Contagem Total",
            "Q1": "Q1: Espacial (<1km)",
            "Q2": "Q2: Free Wi-Fi",
            "Q3": "Q3: Top 10 Ranking",
            "Q4": "Q4: Outlets % (Aggr)",
            "Q5": "Q5: User History",
            "Q6": "Q6: Tendência Temporal",
            "INSERT": "CRUD: Insert Multi",
            "UPDATE": "CRUD: Update Amenities",
            "DELETE": "CRUD: Delete Multi"
        }
        output_lines.append(f"{nomes[op]:<25} | {t_b:>11.2f} ms | {t_a:>11.2f} ms | {diff_str:>12}")

    output_lines.append("-" * 75)
    output_lines.append("\n" + "=" * 75)
    output_lines.append(" ANÁLISE DOS QUERY PLANS (.explain('executionStats'))")
    output_lines.append("=" * 75)
    output_lines.append(f"Q2 (Free Wi-Fi):")
    output_lines.append(f"  - Baseline:  Estágio: {plans_before['q2']['stage']} | Docs Examinados: {plans_before['q2']['totalDocsExamined']} | Retornados: {plans_before['q2']['nReturned']}")
    output_lines.append(f"  - Otimizado: Estágio: {plans_after['q2']['stage']} | Chaves Examinadas: {plans_after['q2']['totalKeysExamined']} | Retornados: {plans_after['q2']['nReturned']}")
    output_lines.append(f"\nQ3 (Top 10 Ranking):")
    output_lines.append(f"  - Baseline:  Estágio: {plans_before['q3']['stage']} (In-memory Sort: {plans_before['q3']['has_in_memory_sort']}) | Docs Examinados: {plans_before['q3']['totalDocsExamined']}")
    output_lines.append(f"  - Otimizado: Estágio: {plans_after['q3']['stage']} (In-memory Sort: {plans_after['q3']['has_in_memory_sort']}) | Chaves Examinadas: {plans_after['q3']['totalKeysExamined']}")

    output_lines.append("\n" + "=" * 75)
    output_lines.append(" IMPACTO NO ARMAZENAMENTO EM DISCO (STORAGE OVERHEAD)")
    output_lines.append("=" * 75)
    output_lines.append(f"Tamanho dos Índices (Venues):  {storage_before['venues_idx_kb']:.1f} KB  -->  {storage_after['venues_idx_kb']:.1f} KB")
    output_lines.append(f"Tamanho dos Índices (Reviews): {storage_before['reviews_idx_kb']:.1f} KB  -->  {storage_after['reviews_idx_kb']:.1f} KB")
    output_lines.append(f"Tamanho Total de Índices:     {storage_before['total_idx_kb']:.1f} KB  -->  {storage_after['total_idx_kb']:.1f} KB")
    output_lines.append("=" * 75)

    # Imprimir no terminal
    relatorio_txt = "\n".join(output_lines)
    print(relatorio_txt)

    # Gravar em ficheiro para o relatório
    output_file = "mongoDB/mongo/goal4_mongodb_results.txt"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(relatorio_txt)
        print(f"\n Resultados gravados com sucesso em '{output_file}'.")
    except Exception as e:
        print(f" Não foi possível gravar o ficheiro: {e}")

    client.close()


if __name__ == "__main__":
    main()
