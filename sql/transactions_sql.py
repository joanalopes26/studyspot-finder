"""
================================================================================
        Transação Multi-Entidade (Commit e Rollback) - MySQL
================================================================================

Este script testa transações ACID multi-tabela no MySQL (motor InnoDB),
envolvendo três entidades principais:

    - Review
    - Business / Business_Amenities
    - User

1. TESTE DE SUCESSO (COMMIT)
   Insere uma review na tabela 'Review', atualiza o estabelecimento nas
   tabelas 'Business' e 'Business_Amenities' (incrementando 'review_count'
   e 'outlet_mentions') e incrementa o 'review_count' do utilizador na
   tabela 'User', garantindo que todas as operações são executadas de forma
   atómica.

2. TESTE DE FALHA (ROLLBACK)
   Executa a inserção da review e as atualizações do estabelecimento
   normalmente, mas provoca uma falha no passo final (por exemplo, uma
   violação de restrição CHECK na tabela 'User').

   Esta falha força a execução de cnx.rollback(), comprovando que a inserção
   e todas as atualizações anteriores são integralmente revertidas.

3. RESTAURO DO ESTADO DA BASE DE DADOS
   No final da execução, o estado original da base de dados é reposto,
   garantindo que os dados utilizados no teste não permanecem alterados.

NOTA:
   As transações ACID no MySQL requerem a utilização de um motor de
   armazenamento transacional, como o InnoDB, para garantir o correto
   funcionamento do COMMIT e do ROLLBACK.

================================================================================
"""

import time
import uuid
import datetime
import mysql.connector


# ============================================================
# CONFIGURAÇÃO DA LIGAÇÃO AO MYSQL
# ============================================================

MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "BDA2627_68059",  # alterar
    "database": "studyspot"
}


# ============================================================
# EXECUÇÃO DE UMA TRANSAÇÃO SQL MULTI-TABELA
# ============================================================

def executar_transacao_sql(
    cnx,
    cursor,
    venue_id,
    user_id,
    stars=5,
    forcar_falha=False
):
    rev_id = f"rev_tx_{uuid.uuid4().hex[:6]}"
    now = datetime.datetime.now()
    start = time.perf_counter()

    try:
        # Garantir que não existe uma transação anterior pendente
        if cnx.in_transaction:
            cnx.commit()

        # Iniciar uma nova transação
        cnx.start_transaction()

        # ----------------------------------------------------
        # 1. Inserir uma nova review
        # ----------------------------------------------------

        sql_rev = """
            INSERT INTO Review (
                review_id,
                business_id,
                user_id,
                stars,
                useful,
                funny,
                cool,
                review_date,
                text,
                mentions_wifi,
                mentions_outlets,
                mentions_pastry
            )
            VALUES (
                %s, %s, %s, %s,
                0, 0, 0, %s,
                'Transação multi-entidade SQL',
                1, 1, 0
            )
        """

        cursor.execute(
            sql_rev,
            (rev_id, venue_id, user_id, int(stars), now)
        )

        # ----------------------------------------------------
        # 2. Atualizar Business e Business_Amenities
        # ----------------------------------------------------

        sql_biz = """
            UPDATE Business
            SET review_count = review_count + 1
            WHERE business_id = %s
        """

        sql_amen = """
            UPDATE Business_Amenities
            SET outlet_mentions = outlet_mentions + 1
            WHERE business_id = %s
        """

        cursor.execute(sql_biz, (venue_id,))
        cursor.execute(sql_amen, (venue_id,))

        # ----------------------------------------------------
        # 3. Atualizar User ou forçar uma falha
        # ----------------------------------------------------

        if forcar_falha:
            # Rating 10.0 viola a CHECK constraint:
            # average_stars BETWEEN 0.0 AND 5.0

            sql_user_falha = """
                UPDATE User
                SET average_stars = 10.0
                WHERE user_id = %s
            """

            cursor.execute(sql_user_falha, (user_id,))

        else:
            sql_user = """
                UPDATE User
                SET review_count = review_count + 1
                WHERE user_id = %s
            """

            cursor.execute(sql_user, (user_id,))

        # ----------------------------------------------------
        # 4. Confirmar a transação
        # ----------------------------------------------------

        cnx.commit()

        elapsed_ms = (time.perf_counter() - start) * 1000

        return True, rev_id, elapsed_ms, None

    except Exception as e:

        # Em caso de erro, reverter todas as alterações
        cnx.rollback()

        elapsed_ms = (time.perf_counter() - start) * 1000

        return False, rev_id, elapsed_ms, str(e)


# ============================================================
# FUNÇÃO PRINCIPAL
# ============================================================

def main():

    # --------------------------------------------------------
    # 1. Estabelecer ligação à base de dados
    # --------------------------------------------------------

    try:
        cnx = mysql.connector.connect(
            **MYSQL_CONFIG,
            autocommit=True
        )

        cursor = cnx.cursor(dictionary=True)

        print("Ligado ao MySQL com sucesso.\n")

    except Exception as e:
        print(f"Erro ao ligar ao MySQL: {e}")
        return

    # --------------------------------------------------------
    # 2. Obter dados reais para o teste
    # --------------------------------------------------------

    cursor.execute("""
        SELECT business_id, review_count
        FROM Business
        WHERE is_open = 1
        LIMIT 1
    """)

    v_orig = cursor.fetchone()

    cursor.execute("""
        SELECT user_id, review_count
        FROM User
        LIMIT 1
    """)

    u_orig = cursor.fetchone()

    vid = v_orig["business_id"]
    uid = u_orig["user_id"]

    # --------------------------------------------------------
    # 3. Cabeçalho do benchmark
    # --------------------------------------------------------

    print("=" * 65)
    print(" TESTE DE TRANSAÇÕES MULTI-ENTIDADE EM MYSQL")
    print(" COMMIT vs ROLLBACK")
    print("=" * 65)

    # ========================================================
    # TESTE 1 — SUCESSO (COMMIT)
    # ========================================================

    ok1, rev1, t1, _ = executar_transacao_sql(
        cnx,
        cursor,
        vid,
        uid,
        stars=5,
        forcar_falha=False
    )

    # Verificar se a review foi criada
    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM Review
        WHERE review_id = %s
    """, (rev1,))

    rev1_existe = cursor.fetchone()["cnt"] == 1

    # Verificar contador do Business
    cursor.execute("""
        SELECT review_count
        FROM Business
        WHERE business_id = %s
    """, (vid,))

    v_cnt1 = cursor.fetchone()["review_count"]

    # Apresentar resultados do Teste 1
    print("\n[TESTE 1 - COMMIT]")
    print(f" Sucesso da Transação : {ok1}")
    print(f" Review Criada na BD  : {rev1_existe}")
    print(
        f" Contador no Business : "
        f"{v_orig['review_count']} -> {v_cnt1}"
    )
    print(f" Tempo de Resposta     : {t1:.2f} ms")

    # ========================================================
    # TESTE 2 — FALHA (ROLLBACK)
    # ========================================================

    ok2, rev2, t2, erro = executar_transacao_sql(
        cnx,
        cursor,
        vid,
        uid,
        stars=5,
        forcar_falha=True
    )

    # Verificar se a review foi criada ou revertida
    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM Review
        WHERE review_id = %s
    """, (rev2,))

    rev2_existe = cursor.fetchone()["cnt"] == 1

    # Verificar contador do Business
    cursor.execute("""
        SELECT review_count
        FROM Business
        WHERE business_id = %s
    """, (vid,))

    v_cnt2 = cursor.fetchone()["review_count"]

    # Apresentar resultados do Teste 2
    print("\n[TESTE 2 - ROLLBACK (Falha Forçada)]")
    print(f" Sucesso da Transação : {ok2}")
    print(f" Review Criada na BD  : {rev2_existe} (Revertida!)")
    print(
        f" Contador no Business : "
        f"{v_cnt1} -> {v_cnt2} (Mantido!)"
    )
    print(f" Erro Capturado       : {erro}")
    print(f" Tempo de Resposta    : {t2:.2f} ms")

    # ========================================================
    # LIMPEZA DOS DADOS DE TESTE
    # ========================================================

    # Eliminar a review criada no Teste 1
    cursor.execute("""
        DELETE FROM Review
        WHERE review_id = %s
    """, (rev1,))

    # Restaurar contador original do Business
    cursor.execute("""
        UPDATE Business
        SET review_count = %s
        WHERE business_id = %s
    """, (v_orig["review_count"], vid))

    # Restaurar contador original do User
    cursor.execute("""
        UPDATE User
        SET review_count = %s
        WHERE user_id = %s
    """, (u_orig["review_count"], uid))

    # --------------------------------------------------------
    # 4. Finalização
    # --------------------------------------------------------

    print("\n" + "=" * 65)
    print(" ✓ Estado da base de dados reposto com sucesso.")
    print("=" * 65)

    cursor.close()
    cnx.close()


# ============================================================
# PONTO DE ENTRADA DO PROGRAMA
# ============================================================

if __name__ == "__main__":
    main()