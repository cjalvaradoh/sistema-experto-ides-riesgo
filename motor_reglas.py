import os
import operator
from collections import Counter
from datetime import timedelta, timezone
 
import psycopg
from dotenv import load_dotenv
 
load_dotenv()
 
TZ = timezone(timedelta(hours=-6))  # Guatemala
ADMINS = {"marta_admin"}
ARCHIVOS_SENSIBLES = {"/etc/shadow", "/etc/passwd", "/var/db/clientes.sql"}
VENTANA_DEDUP = timedelta(minutes=15)  # evita alertas repetidas del mismo caso
 
OPS = {"==": operator.eq, "!=": operator.ne, ">=": operator.ge,
       "<=": operator.le, ">": operator.gt, "<": operator.lt}
 
 
# ---------- 1. Base de hechos ----------
def calcular_hechos(eventos):
    """Convierte cada evento en un diccionario de hechos (agrega contexto)."""
    host_habitual = {}
    for u in {e["usuario"] for e in eventos}:
        hosts = Counter(e["host_origen"] for e in eventos if e["usuario"] == u)
        host_habitual[u] = hosts.most_common(1)[0][0]
 
    por_usuario = {}
    for e in eventos:
        por_usuario.setdefault(e["usuario"], []).append(e)
 
    hechos = []
    for e in eventos:
        t = e["fecha_hora"].astimezone(TZ)
        previos = [x for x in por_usuario[e["usuario"]]
                   if e["fecha_hora"] - timedelta(minutes=10) < x["fecha_hora"] <= e["fecha_hora"]]
        hechos.append({
            "evento_id": e["id"], "usuario": e["usuario"], "fecha_hora": e["fecha_hora"],
            "accion": e["accion"], "resultado": e["resultado"], "objeto": e["objeto"],
            "host_nuevo": e["host_origen"] != host_habitual[e["usuario"]],
            "fuera_horario": t.hour < 6 or t.hour >= 20 or t.weekday() >= 5,
            "es_admin": e["usuario"] in ADMINS,
            "sensible": e["objeto"] in ARCHIVOS_SENSIBLES,
            "fallos_5min": sum(1 for x in previos if x["accion"] == "login" and x["resultado"] == "fallo"
                               and x["fecha_hora"] > e["fecha_hora"] - timedelta(minutes=5)),
            "lecturas_10min": sum(1 for x in previos if x["accion"] == "leer_archivo"),
        })
    return hechos
 
 
# ---------- 2. Motor de inferencia ----------
def evaluar(condicion, hechos, conclusiones):
    """Devuelve (cumple, certeza_de_premisas)."""
    cf_prem = 1.0
    for campo, op, valor in condicion["si"]:
        if op == "tiene":
            if valor not in conclusiones:
                return False, 0
            cf_prem = min(cf_prem, conclusiones[valor])
        elif not OPS[op](hechos[campo], valor):
            return False, 0
    return True, cf_prem
 
 
def inferir(hechos, reglas):
    """Repite hasta que ninguna regla nueva se dispare (encadenamiento hacia adelante)."""
    conclusiones, disparos = {}, []
    disparadas, hubo_cambio = set(), True
    while hubo_cambio:
        hubo_cambio = False
        for r in reglas:
            if r["nombre"] in disparadas:
                continue
            cumple, cf_prem = evaluar(r["condicion"], hechos, conclusiones)
            if cumple:
                cf = float(r["certeza"]) * cf_prem          # certeza de la regla x premisas
                previo = conclusiones.get(r["conclusion"], 0)
                conclusiones[r["conclusion"]] = previo + cf * (1 - previo)  # combina evidencias
                disparadas.add(r["nombre"])
                disparos.append((r, round(cf, 2)))
                hubo_cambio = True
    return disparos
 
 
# ---------- 3. Modulo de explicacion ----------
def explicar(regla, hechos):
    usados = [f"{c}={hechos[c]}" for c, op, _ in regla["condicion"]["si"] if op != "tiene"]
    previas = [v for c, op, v in regla["condicion"]["si"] if op == "tiene"]
    texto = f"{regla['nombre']}: {regla['descripcion']}. Usuario {hechos['usuario']}. Hechos: " + ", ".join(usados)
    if previas:
        texto += f". Se apoya en la conclusion previa: {', '.join(previas)}"
    return texto
 
 
# ---------- 4. Ejecucion completa ----------
def generar_alertas(eventos, reglas):
    """Funcion pura: eventos + reglas -> lista de alertas (sin tocar la base)."""
    alertas, ultima = [], {}
    for h in calcular_hechos(eventos):
        for regla, cf in inferir(h, reglas):
            clave = (h["usuario"], regla["conclusion"])
            if clave in ultima and h["fecha_hora"] - ultima[clave] < VENTANA_DEDUP:
                continue
            ultima[clave] = h["fecha_hora"]
            alertas.append({"evento_id": h["evento_id"], "regla_id": regla.get("id"),
                            "conclusion": regla["conclusion"], "severidad": regla["severidad"],
                            "certeza": cf, "explicacion": explicar(regla, h)})
    return alertas
 
 
def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        cur = conn.execute("SELECT id, usuario, accion, objeto, host_origen, resultado, fecha_hora "
                           "FROM eventos ORDER BY fecha_hora, id")
        cols = [c.name for c in cur.description]
        eventos = [dict(zip(cols, f)) for f in cur.fetchall()]
        cur = conn.execute("SELECT id, nombre, descripcion, condicion, conclusion, severidad, certeza "
                           "FROM reglas WHERE activa ORDER BY id")
        cols = [c.name for c in cur.description]
        reglas = [dict(zip(cols, f)) for f in cur.fetchall()]
 
        alertas = generar_alertas(eventos, reglas)
        conn.execute("DELETE FROM alertas WHERE origen = 'regla'")
        with conn.cursor() as c:
            c.executemany(
                """INSERT INTO alertas (evento_id, regla_id, origen, conclusion, severidad, certeza, explicacion)
                   VALUES (%(evento_id)s, %(regla_id)s, 'regla', %(conclusion)s, %(severidad)s,
                           %(certeza)s, %(explicacion)s)""", alertas)
        print(f"{len(eventos)} eventos, {len(reglas)} reglas, {len(alertas)} alertas generadas")
        for fila in conn.execute("SELECT conclusion, severidad, COUNT(*) FROM alertas GROUP BY 1,2 ORDER BY 3 DESC"):
            print(fila)
 
 
if __name__ == "__main__":
    main()