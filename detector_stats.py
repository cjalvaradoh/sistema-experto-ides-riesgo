import os
import math
from datetime import timedelta
from collections import Counter
 
import psycopg
from dotenv import load_dotenv
 
from motor_reglas import TZ
 
load_dotenv()
 
DIAS_APRENDIZAJE = 7     # periodo con el que se construye el perfil
UMBRAL_Z = 3.0           # desviaciones estandar para considerar algo anormal
UMBRAL_DEPURACION = 2.0  # al aprender, se descartan valores con |z| mayor a esto
STD_MINIMA = {"eventos_por_hora": 1.5, "hora_login": 0.5}  # evita dividir entre ~0
 
 
def _valores(eventos):
    """Devuelve {(usuario, medida): [(valor, evento_id, fecha_hora), ...]}"""
    vals, buckets = {}, {}
    for e in eventos:
        t = e["fecha_hora"].astimezone(TZ)
        buckets.setdefault((e["usuario"], t.date(), t.hour), []).append(e)
        if e["accion"] == "login" and e["resultado"] == "exito":
            vals.setdefault((e["usuario"], "hora_login"), []).append(
                (t.hour + t.minute / 60, e["id"], e["fecha_hora"]))
    for (u, _, _), evs in buckets.items():
        vals.setdefault((u, "eventos_por_hora"), []).append(
            (len(evs), evs[0]["id"], evs[0]["fecha_hora"]))
    return vals
 
 
def calcular_perfiles(eventos):
    """Perfil = (n, suma, suma_cuadrados) con el periodo de aprendizaje.
    Depuracion: se descartan los valores atipicos (|z| > UMBRAL_DEPURACION) y se recalcula,
    para que un ataque ocurrido durante el aprendizaje no contamine el perfil."""
    corte = min(e["fecha_hora"] for e in eventos) + timedelta(days=DIAS_APRENDIZAJE)
    aprendizaje = [e for e in eventos if e["fecha_hora"] < corte]
    perfiles = {}
    for (u, medida), v in _valores(aprendizaje).items():
        xs = [x[0] for x in v]
        for _ in range(2):  # 2 pasadas de depuracion
            n, s, sc = len(xs), sum(xs), sum(x ** 2 for x in xs)
            media, std = media_std(n, s, sc, medida)
            xs = [x for x in xs if abs(x - media) / std <= UMBRAL_DEPURACION]
        perfiles[(u, medida)] = (len(xs), sum(xs), sum(x ** 2 for x in xs))
    return perfiles
 
 
def media_std(n, suma, suma_cuad, medida):
    media = suma / n
    var = max(suma_cuad / n - media ** 2, 0)
    return media, max(math.sqrt(var), STD_MINIMA[medida])
 
 
def detectar(eventos, perfiles):
    alertas = []
    for (u, medida), valores in _valores(eventos).items():
        if (u, medida) not in perfiles:
            continue
        media, std = media_std(*perfiles[(u, medida)], medida)
        for valor, evento_id, _ in valores:
            z = (valor - media) / std
            anormal = z > UMBRAL_Z if medida == "eventos_por_hora" else abs(z) > UMBRAL_Z
            if anormal:
                concl = "actividad_anormal" if medida == "eventos_por_hora" else "hora_login_anomala"
                alertas.append({
                    "evento_id": evento_id, "conclusion": concl,
                    "severidad": "alta" if abs(z) >= 5 else "media",
                    "certeza": min(0.95, round(0.5 + 0.05 * abs(z), 2)),
                    "explicacion": (f"Perfil de {u}, medida {medida}: valor observado {valor:.1f}, "
                                    f"normal {media:.1f} +- {std:.1f} (z = {z:.1f}, umbral {UMBRAL_Z})")})
    return alertas
 
 
def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        cur = conn.execute("SELECT id, usuario, accion, resultado, fecha_hora FROM eventos ORDER BY fecha_hora, id")
        cols = [c.name for c in cur.description]
        eventos = [dict(zip(cols, f)) for f in cur.fetchall()]
 
        perfiles = calcular_perfiles(eventos)
        conn.execute("DELETE FROM perfiles")
        conn.execute("DELETE FROM alertas WHERE origen = 'estadistico'")
        with conn.cursor() as c:
            c.executemany("INSERT INTO perfiles (usuario, medida, n, suma, suma_cuadrados) VALUES (%s,%s,%s,%s,%s)",
                          [(u, m, n, s, sc) for (u, m), (n, s, sc) in perfiles.items()])
            alertas = detectar(eventos, perfiles)
            c.executemany(
                """INSERT INTO alertas (evento_id, origen, conclusion, severidad, certeza, explicacion)
                   VALUES (%(evento_id)s, 'estadistico', %(conclusion)s, %(severidad)s, %(certeza)s, %(explicacion)s)""",
                alertas)
        print(f"{len(perfiles)} perfiles guardados, {len(alertas)} alertas estadisticas")
        for u, m, n, s, sc in conn.execute("SELECT * FROM perfiles ORDER BY usuario, medida"):
            media, std = media_std(n, s, sc, m)
            print(f"  {u:12} {m:17} n={n:3} media={media:5.1f} desv={std:4.1f}")
        for fila in conn.execute("SELECT conclusion, severidad, COUNT(*) FROM alertas WHERE origen='estadistico' GROUP BY 1,2"):
            print(fila)
 
 
if __name__ == "__main__":
    main()