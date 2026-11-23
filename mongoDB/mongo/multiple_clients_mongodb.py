"""
================================================================================
Simulação de Concorrência no MongoDB
================================================================================
Este script simula múltiplos clientes (threads) a aceder e a modificar dados em
simultâneo na base de dados 'studyspot' (coleção 'venues').

O objetivo é observar e medir, sob contenção no mesmo documento ('venue'):
  1. Tempos de resposta (tempo total, latência média e máxima por operação, e
     throughput em leituras).
  2. Conflitos de escrita (colisões entre clientes a atualizar o mesmo registo).
  3. Consistência final dos dados (detetando 'lost updates' e comprovando como
     o controlo otimista e os operadores atómicos garantem consistência).

No final de cada teste de escrita, o valor original de 'review_count' é sempre
reposto para preservar a integridade do dataset ingerido no Goal 2.
================================================================================
"""

import statistics
import threading
import time
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "studyspot"

N_CLIENTES = 10   # nº de clientes (threads) em simultâneo (igual ao MySQL)
OPS = 5           # nº de operações por cliente (igual ao MySQL)


# ------------------------------------------------------------------------------
# Representa um cliente individual (executado numa thread independente) que
# tenta incrementar o campo 'review_count' de um mesmo venue OPS vezes.
#
# Suporta três estratégias de controlo de concorrência:
#   - 'sem_controlo': lê o valor atual (find_one), simula processamento (10 ms)
#                     e grava o novo valor ($set). Sem coordenação, várias
#                     threads leem o mesmo valor e sobrescrevem-se (lost update).
#   - 'cas' (Compare-And-Swap / Controlo Otimista): lê o valor atual e só aplica
#                     o $set se o documento ainda tiver esse exato valor no
#                     filtro. Se outro cliente o alterou entretanto, regista
#                     1 conflito e repete a tentativa até conseguir escrever.
#   - 'atomico':      utiliza o operador nativo $inc do MongoDB, que aplica o
#                     incremento de forma atómica ao nível do documento no
#                     motor WiredTiger, evitando lost updates e retries.
#
# Mede a latência de cada operação (em ms) e agrega as métricas num dicionário
# partilhado protegido por um threading.Lock para evitar race conditions no Python.
# ------------------------------------------------------------------------------

def cliente_escrita(col, venue_id, modo, stats, lock):
    """
    Executa OPS incrementos em 'review_count' no mesmo venue.
      - 'sem_controlo': find_one + sleep + $set (gera lost updates)
      - 'cas':          controlo otimista (Compare-And-Swap com deteção de conflitos e retry)
      - 'atomico':      operador atómico $inc do MongoDB (bloqueio atómico ao nível do documento)
    """
    latencias_locais = []
    conflitos_locais = 0

    for _ in range(OPS):
        t0 = time.perf_counter()

        if modo == "sem_controlo":
            atual = col.find_one({"_id": venue_id}, {"review_count": 1})["review_count"]
            time.sleep(0.01)  # simula processamento (igual ao script MySQL)
            col.update_one({"_id": venue_id}, {"$set": {"review_count": atual + 1}})

        elif modo == "cas":
            tentativa = 0
            while True:
                atual = col.find_one({"_id": venue_id}, {"review_count": 1})["review_count"]
                if tentativa == 0:
                    time.sleep(0.01)  # simula processamento inicial
                res = col.update_one(
                    {"_id": venue_id, "review_count": atual},
                    {"$set": {"review_count": atual + 1}},
                )
                if res.modified_count == 1:
                    break
                tentativa += 1
                conflitos_locais += 1

        elif modo == "atomico":
            time.sleep(0.01)  # simula processamento antes da escrita atómica
            col.update_one({"_id": venue_id}, {"$inc": {"review_count": 1}})

        latencias_locais.append((time.perf_counter() - t0) * 1000)

    with lock:
        stats["latencias"].extend(latencias_locais)
        stats["conflitos"] += conflitos_locais


# ------------------------------------------------------------------------------
# Orquestra uma ronda completa de testes de escrita concorrente para um modo
# específico ('sem_controlo', 'cas' ou 'atomico'):
#   1. Regista o valor inicial de 'review_count' no venue de teste.
#   2. Lança N_CLIENTES threads em paralelo e aguarda a conclusão de todas.
#   3. Calcula o tempo total, latência média/máxima por operação e total de
#      conflitos ocorridos.
#   4. Valida a consistência comparando o valor final com (inicial + N_CLIENTES * OPS).
#   5. Garante no bloco 'finally' que o valor inicial é sempre restaurado na BD.
# ------------------------------------------------------------------------------

def testar_escritas(col, nome, venue_id, modo):
    inicial = col.find_one({"_id": venue_id}, {"review_count": 1})["review_count"]
    stats = {"latencias": [], "conflitos": 0}
    lock = threading.Lock()

    try:
        threads = [
            threading.Thread(target=cliente_escrita, args=(col, venue_id, modo, stats, lock))
            for _ in range(N_CLIENTES)
        ]

        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        tempo_total = time.perf_counter() - t0

        final = col.find_one({"_id": venue_id}, {"review_count": 1})["review_count"]
        esperado = inicial + N_CLIENTES * OPS
        estado = "OK" if final == esperado else f"INCONSISTENTE ({esperado - final} updates perdidos)"
        avg_ms = statistics.mean(stats["latencias"])
        max_ms = max(stats["latencias"])

        print(
            f"{nome:<22}: {inicial} -> {final} (esperado {esperado}) | "
            f"total: {tempo_total:.3f} s | op avg/max: {avg_ms:.1f}/{max_ms:.1f} ms | "
            f"conflitos: {stats['conflitos']:>2} | {estado}"
        )
    finally:
        # Repõe sempre o valor original para manter a BD consistente
        col.update_one({"_id": venue_id}, {"$set": {"review_count": inicial}})


# ------------------------------------------------------------------------------
# Simula múltiplos clientes a aceder à base de dados em simultâneo apenas em
# leitura (sem bloqueios de escrita). Cada cliente executa 'ops' consultas
# filtrando locais com Wi-Fi gratuito em Santa Barbara e projetando apenas os
# campos essenciais. Mede o tempo total, o débito em queries por segundo (q/s)
# e a latência média/máxima de cada consulta.
# ------------------------------------------------------------------------------

def testar_leituras_concorrentes(col, n_clientes=N_CLIENTES, ops=20):
    """Simula vários clientes a consultar venues em simultâneo (ex.: Free Wi-Fi numa cidade)."""
    latencias = []
    lock = threading.Lock()

    def leitor():
        locais = []
        for _ in range(ops):
            t0 = time.perf_counter()
            list(col.find(
                {"city": "Santa Barbara", "amenities.wifi": "free"},
                {"name": 1, "stars": 1, "amenities.wifi": 1},
            ))
            locais.append((time.perf_counter() - t0) * 1000)
        with lock:
            latencias.extend(locais)

    threads = [threading.Thread(target=leitor) for _ in range(n_clientes)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    tempo_total = time.perf_counter() - t0

    total_ops = n_clientes * ops
    print(
        f"\nLeituras concorrentes : {total_ops} queries ({n_clientes} clientes) | "
        f"total: {tempo_total:.3f} s | throughput: {total_ops / tempo_total:.1f} q/s | "
        f"avg/max: {statistics.mean(latencias):.1f}/{max(latencias):.1f} ms"
    )

# ------------------------------------------------------------------------------
# Estabelece uma ligação única ao MongoDB (o MongoClient do PyMongo é
# thread-safe e gere internamente um connection pool partilhado pelas threads),
# seleciona um venue da coleção 'venues' como alvo e executa sequencialmente
# os três testes de escrita concorrente seguidos do teste de leituras concorrentes.
# ------------------------------------------------------------------------------
def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    col = db.venues

    # Seleciona um venue (para comparação exata com MySQL, podem fixar o mesmo business_id)
    venue = col.find_one({}, {"_id": 1, "name": 1})
    venue_id = venue["_id"]
    print(f"Venue de teste: {venue.get('name')} ({venue_id})")
    print(f"Configuração  : {N_CLIENTES} clientes x {OPS} incrementos = {N_CLIENTES * OPS} operações\n")

    testar_escritas(col, "Sem controlo", venue_id, modo="sem_controlo")
    testar_escritas(col, "Otimista (CAS+retry)", venue_id, modo="cas")
    testar_escritas(col, "Atómico ($inc)", venue_id, modo="atomico")
    testar_leituras_concorrentes(col)

    client.close()


if __name__ == "__main__":
    main()