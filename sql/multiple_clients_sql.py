import threading
import time
import mysql.connector

MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "BDA2627_68059",  # alterar
    "database": "studyspot",
}

N_CLIENTES = 10   #nº de clientes (threads) em simultâneo
OPS = 5           #nº de incrementos que cada cliente faz


#cada cliente lê o review_count e escreve +1
#com_lock=False -> sem controlo de concorrência
#com_lock=True  -> transação + SELECT ... FOR UPDATE (bloqueia a linha até ao commit)
def cliente(business_id, com_lock):
    cnx = mysql.connector.connect(**MYSQL_CONFIG, autocommit=True)
    cur = cnx.cursor()
    for _ in range(OPS):
        if com_lock:
            cnx.start_transaction()
        cur.execute("SELECT review_count FROM Business WHERE business_id = %s"
                    + (" FOR UPDATE" if com_lock else ""), (business_id,))
        atual = cur.fetchone()[0]
        time.sleep(0.01)  #simula processamento
        cur.execute("UPDATE Business SET review_count = %s WHERE business_id = %s", (atual + 1, business_id))
        if com_lock:
            cnx.commit()
    cnx.close()


def testar(nome, business_id, com_lock):
    cnx = mysql.connector.connect(**MYSQL_CONFIG, autocommit=True)
    cur = cnx.cursor()
    cur.execute("SELECT review_count FROM Business WHERE business_id = %s", (business_id,))
    inicial = cur.fetchone()[0]

    #lançar os clientes todos ao mesmo tempo
    threads = [threading.Thread(target=cliente, args=(business_id, com_lock)) for _ in range(N_CLIENTES)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    tempo = time.perf_counter() - t0

    #verificar consistência
    cur.execute("SELECT review_count FROM Business WHERE business_id = %s", (business_id,))
    final = cur.fetchone()[0]
    esperado = inicial + N_CLIENTES * OPS
    estado = "OK" if final == esperado else f"INCONSISTENTE ({esperado - final} updates perdidos)"
    print(f"{nome}: {inicial} -> {final} (esperado {esperado}) | tempo: {tempo:.3f} s | {estado}")

    #repoe o valor original
    cur.execute("UPDATE Business SET review_count = %s WHERE business_id = %s", (inicial, business_id))
    cnx.close()


cnx = mysql.connector.connect(**MYSQL_CONFIG)
cur = cnx.cursor()
cur.execute("SELECT business_id FROM Business LIMIT 1")
business_id = cur.fetchone()[0]
cnx.close()

testar("Sem controlo", business_id, com_lock=False)
testar("Com FOR UPDATE", business_id, com_lock=True)