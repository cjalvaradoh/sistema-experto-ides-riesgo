import os
import random
import itertools
from datetime import datetime, timedelta, timezone
 
import psycopg
from dotenv import load_dotenv
 
load_dotenv()
random.seed(42)  
 
TZ = timezone(timedelta(hours=-6))          # hora de Guatemala
INICIO = datetime(2026, 10, 19, tzinfo=TZ)  # lunes
DIAS = 14
HOST_EXTERNO = "203.0.113.45"
 
USUARIOS = {
    "ana":         {"host": "10.0.0.11", "archivos": ["/home/ana/reporte.docx", "/home/ana/datos.csv"]},
    "luis":        {"host": "10.0.0.12", "archivos": ["/home/luis/codigo.py", "/home/luis/notas.txt"]},
    "carla":       {"host": "10.0.0.13", "archivos": ["/home/carla/factura.xlsx", "/home/carla/clientes.csv"]},
    "pedro":       {"host": "10.0.0.14", "archivos": ["/home/pedro/plan.pptx", "/home/pedro/informe.pdf"]},
    "marta_admin": {"host": "10.0.0.10", "archivos": ["/etc/hosts", "/var/log/syslog"]},
}
ARCHIVOS_SENSIBLES = ["/etc/shadow", "/etc/passwd", "/var/db/clientes.sql"]
 
 
def dt(dia, hora, minuto=0):
    return (INICIO + timedelta(days=dia)).replace(hour=hora, minute=minuto)
 
 
def eventos_normales():
    ev = []
    for dia in range(DIAS):
        if dia % 7 >= 5:  # sabado y domingo no hay actividad
            continue
        for u, p in USUARIOS.items():
            t = dt(dia, 7, 30) + timedelta(minutes=random.randint(0, 120))
            if random.random() < 0.10:  # error de tecleo ocasional
                ev.append((u, "login", None, p["host"], "fallo", t - timedelta(seconds=30), "normal", None))
            ev.append((u, "login", None, p["host"], "exito", t, "normal", None))
            for _ in range(random.randint(5, 12)):
                ta = t + timedelta(minutes=random.randint(5, 420))
                ev.append((u, "leer_archivo", random.choice(p["archivos"]), p["host"], "exito", ta, "normal", None))
            if u == "marta_admin":  # el admin usa sudo y lee archivos del sistema con normalidad
                for _ in range(random.randint(1, 3)):
                    ta = t + timedelta(minutes=random.randint(10, 400))
                    ev.append((u, "usar_sudo", "root", p["host"], "exito", ta, "normal", None))
                ta = t + timedelta(minutes=random.randint(10, 400))
                ev.append((u, "leer_archivo", "/etc/passwd", p["host"], "exito", ta, "normal", None))
            tf = dt(dia, 16, 30) + timedelta(minutes=random.randint(0, 90))
            ev.append((u, "logout", None, p["host"], "exito", tf, "normal", None))
    return ev
 
 
def eventos_ataque():
    ev = []
    inc = itertools.count(1)  # id de incidente
 
    for dia, u in [(3, "luis"), (8, "carla")]:  # fuerza bruta: 8 fallos en 2 minutos
        i, t = next(inc), dt(dia, 2, 15)
        for k in range(8):
            ev.append((u, "login", None, HOST_EXTERNO, "fallo", t + timedelta(seconds=15 * k), "fuerza_bruta", i))
 
    for dia, u in [(4, "ana"), (9, "pedro")]:  # suplantacion: login exitoso de madrugada desde host nuevo
        i, t = next(inc), dt(dia, 3, 0)
        ev.append((u, "login", None, HOST_EXTERNO, "exito", t, "suplantacion", i))
        for k, arch in enumerate(USUARIOS[u]["archivos"]):
            ev.append((u, "leer_archivo", arch, HOST_EXTERNO, "exito", t + timedelta(minutes=2 + k), "suplantacion", i))
 
    for dia, u in [(2, "carla"), (10, "luis")]:  # usuario normal lee archivos sensibles
        i, t = next(inc), dt(dia, 11, 0)
        for k, arch in enumerate(ARCHIVOS_SENSIBLES[:2]):
            ev.append((u, "leer_archivo", arch, USUARIOS[u]["host"], "exito", t + timedelta(minutes=k), "acceso_sensible", i))
 
    for dia, u in [(1, "pedro"), (7, "ana")]:  # intenta usar sudo sin ser admin
        i, t = next(inc), dt(dia, 14, 0)
        for k in range(3):
            ev.append((u, "usar_sudo", "root", USUARIOS[u]["host"], "fallo", t + timedelta(seconds=20 * k), "escalada_privilegios", i))
        ev.append((u, "usar_sudo", "root", USUARIOS[u]["host"], "exito", t + timedelta(seconds=70), "escalada_privilegios", i))
 
    for dia, u in [(3, "ana"), (11, "carla")]:  # lectura masiva de archivos en pocos minutos
        i, t = next(inc), dt(dia, 15, 0)
        for k in range(40):
            ev.append((u, "leer_archivo", f"/home/{u}/docs/doc_{k}.pdf", USUARIOS[u]["host"], "exito", t + timedelta(seconds=7 * k), "exfiltracion", i))
    return ev
 
 
def main():
    datos = sorted(eventos_normales() + eventos_ataque(), key=lambda e: e[5])
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("TRUNCATE alertas, eventos, perfiles RESTART IDENTITY")
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO eventos (usuario, accion, objeto, host_origen, resultado,
                   fecha_hora, etiqueta_real, incidente_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", datos)
        for fila in conn.execute(
            "SELECT etiqueta_real, COUNT(*) FROM eventos GROUP BY 1 ORDER BY 2 DESC"):
            print(fila)
 
 
if __name__ == "__main__":
    main()