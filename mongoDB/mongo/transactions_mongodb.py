"""
================================================================================
Transação Multi-Entidade (Commit e Rollback)
================================================================================
Este script testa transações ACID multi-documento no MongoDB envolvendo três
coleções relacionadas ('reviews', 'venues' e 'users'):
  1. Teste de sucesso (COMMIT): insere uma review, atualiza o venue (contagem,
     média de estrelas, menções a tomadas e array 'recent_reviews') e incrementa
     o 'review_count' do utilizador de forma atómica.
  2. Teste de falha (ROLLBACK): executa os passos 1 e 2 normalmente, mas provoca
     uma falha de validação ($jsonSchema) no passo 3 (review_count negativo em
     'users'), forçando o abort_transaction() e comprovando que os passos 1 e 2
     são integralmente revertidos.

No final (bloco finally), o estado original da base de dados é sempre reposto.
Nota: transações multi-documento no MongoDB requerem um Replica Set ativo (rs0).
================================================================================
"""

import datetime
import sys
import time
import uuid

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "studyspot"

# ------------------------------------------------------------------------------
# Executa uma transação ACID com isolamento 'snapshot' e write concern 'majority'
# sobre as três coleções do StudySpot:
#   - Passo 1 ('reviews'): insere o novo documento de avaliação.
#   - Passo 2 ('venues'):  recalcula 'stars', incrementa 'review_count' e
#                          'amenities.outlet_mentions', e coloca o resumo no
#                          topo de 'recent_reviews' ($position: 0, $slice: 10).
#   - Passo 3 ('users'):   incrementa 'review_count'. Se 'forcar_falha=True',
#                          tenta gravar review_count = -1 para violar o validator
#                          strict da coleção 'users' e disparar o rollback.
#
# Retorna um tuplo: (sucesso, review_id, tempo_ms, mensagem_erro).
# ------------------------------------------------------------------------------
def executar_transacao(client, db, venue_id, user_id, stars=5, forcar_falha=False):
    rev_id = f"rev_tx_{uuid.uuid4().hex[:8]}"
    agora = datetime.datetime.now(datetime.timezone.utc)
    t0 = time.perf_counter()

    with client.start_session() as session:
        session.start_transaction(
            read_concern=ReadConcern("snapshot"),
            write_concern=WriteConcern("majority"),
        )
        try:
            venue = db.venues.find_one({"_id": venue_id}, session=session)
            user = db.users.find_one({"_id": user_id}, session=session)

            # Recalcula a nova média de estrelas do venue
            novo_total = venue["review_count"] + 1
            novas_stars = round(((venue["stars"] * venue["review_count"]) + stars) / novo_total, 2)

            nova_review = {
                "_id": rev_id,
                "venue_id": venue_id,
                "user_id": user_id,
                "stars": int(stars),
                "useful": 0,
                "funny": 0,
                "cool": 0,
                "date": agora,
                "text": "Review transacional de teste com wifi e tomadas.",
                "mentions_wifi": True,
                "mentions_outlets": True,
                "mentions_pastry": False,
            }

            resumo_recente = {
                "review_id": rev_id,
                "user_id": user_id,
                "user_name": user.get("name", "Unknown"),
                "stars": int(stars),
                "date": agora,
                "text_snippet": nova_review["text"][:200],
            }

            # Passo 1: Inserir na coleção 'reviews'
            db.reviews.insert_one(nova_review, session=session)

            # Passo 2: Propagar alterações para 'venues'
            db.venues.update_one(
                {"_id": venue_id},
                {
                    "$set": {"stars": novas_stars},
                    "$inc": {"review_count": 1, "amenities.outlet_mentions": 1},
                    "$push": {
                        "recent_reviews": {
                            "$each": [resumo_recente],
                            "$position": 0,
                            "$slice": 10,
                        }
                    },
                },
                session=session,
            )

            # Passo 3: Propagar alteração para 'users' (ou forçar erro de schema)
            if forcar_falha:
                db.users.update_one(
                    {"_id": user_id},
                    {"$set": {"review_count": -1}},  # viola minimum: 0 no $jsonSchema
                    session=session,
                )
            else:
                db.users.update_one(
                    {"_id": user_id},
                    {"$inc": {"review_count": 1}},
                    session=session,
                )

            session.commit_transaction()
            return True, rev_id, (time.perf_counter() - t0) * 1000, None

        except PyMongoError as erro:
            if session.in_transaction:
                session.abort_transaction()
            return False, rev_id, (time.perf_counter() - t0) * 1000, str(erro)


# ------------------------------------------------------------------------------
# Verifica se o servidor suporta transações (Replica Set ativo), seleciona um
# venue e um utilizador reais, executa o teste de COMMIT seguido do teste de
# ROLLBACK, valida a consistência das 3 coleções após cada teste e restaura os
# documentos originais no bloco 'finally'.
# ------------------------------------------------------------------------------
def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

    # Verifica se o MongoDB está a correr como Replica Set (obrigatório para ACID multi-doc)
    if not client.admin.command("hello").get("setName"):
        print("ERRO: MongoDB está em modo standalone (sem Replica Set).")
        print("Ativa 'replSetName: rs0' no mongod.cfg, reinicia o serviço e corre 'rs.initiate()' no mongosh.")
        client.close()
        sys.exit(1)

    db = client[DB_NAME]
    venue_orig = db.venues.find_one({"is_open": True})
    user_orig = db.users.find_one()
    vid, uid = venue_orig["_id"], user_orig["_id"]

    print(f"Venue de teste: {venue_orig.get('name')} ({vid})")
    print(f"User de teste : {user_orig.get('name')} ({uid})\n")

    try:
        # ── TESTE 1: Execução com sucesso (COMMIT) ─────────────────────────
        ok, rev_id, ms, _ = executar_transacao(client, db, vid, uid, stars=5, forcar_falha=False)
        v_pos = db.venues.find_one({"_id": vid})
        u_pos = db.users.find_one({"_id": uid})
        r_existe = db.reviews.find_one({"_id": rev_id}) is not None

        consistente_ok = (
            ok
            and r_existe
            and v_pos["review_count"] == venue_orig["review_count"] + 1
            and u_pos["review_count"] == user_orig["review_count"] + 1
            and v_pos["recent_reviews"][0]["review_id"] == rev_id
        )
        print(
            f"Teste 1 (COMMIT)  : review={'inserida' if r_existe else 'ausente'} | "
            f"venue_count: {venue_orig['review_count']} -> {v_pos['review_count']} | "
            f"user_count: {user_orig['review_count']} -> {u_pos['review_count']} | "
            f"tempo: {ms:.2f} ms | {'OK' if consistente_ok else 'FALHOU'}"
        )

        # ── TESTE 2: Falha no passo 3 (ROLLBACK) ───────────────────────────
        ok2, rev_id2, ms2, erro = executar_transacao(client, db, vid, uid, stars=1, forcar_falha=True)
        v_pos2 = db.venues.find_one({"_id": vid})
        u_pos2 = db.users.find_one({"_id": uid})
        r2_existe = db.reviews.find_one({"_id": rev_id2}) is not None

        consistente_rb = (
            (not ok2)
            and (not r2_existe)
            and v_pos2["review_count"] == v_pos["review_count"]
            and v_pos2["stars"] == v_pos["stars"]
            and u_pos2["review_count"] == u_pos["review_count"]
        )
        print(
            f"Teste 2 (ROLLBACK): review={'revertida' if not r2_existe else 'PERMANECEU!'} | "
            f"venue_count: {v_pos['review_count']} -> {v_pos2['review_count']} | "
            f"user_count: {u_pos['review_count']} -> {u_pos2['review_count']} | "
            f"tempo: {ms2:.2f} ms | {'OK' if consistente_rb else 'FALHOU'}"
        )
        print(f"  Motivo do abort : {erro.splitlines()[0][:100]}")

    finally:
        # Repõe exatamente o estado inicial para não afetar o dataset do Goal 2
        db.reviews.delete_many({"_id": {"$regex": "^rev_tx_"}})
        db.venues.replace_one({"_id": vid}, venue_orig)
        db.users.replace_one({"_id": uid}, user_orig)
        client.close()


if __name__ == "__main__":
    main()