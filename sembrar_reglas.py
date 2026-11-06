import os
import json
 
import psycopg
from dotenv import load_dotenv
 
load_dotenv()
 
REGLAS = [
    {
        "nombre": "R1_intentos_fallidos_repetidos",
        "descripcion": "5 o mas logins fallidos del mismo usuario en 5 minutos",
        "condicion": {"si": [["accion", "==", "login"], ["resultado", "==", "fallo"],
                             ["fallos_5min", ">=", 5]]},
        "conclusion": "intento_fuerza_bruta", "severidad": "media", "certeza": 0.80,
    },
    {
        "nombre": "R2_fuerza_bruta_desde_host_externo",
        "descripcion": "Intento de fuerza bruta originado en un host que el usuario nunca usa",
        "condicion": {"si": [["conclusiones", "tiene", "intento_fuerza_bruta"],
                             ["host_nuevo", "==", True]]},
        "conclusion": "fuerza_bruta_externa", "severidad": "alta", "certeza": 0.95,
    },
    {
        "nombre": "R3_login_madrugada_host_nuevo",
        "descripcion": "Login exitoso fuera de horario desde un host no habitual",
        "condicion": {"si": [["accion", "==", "login"], ["resultado", "==", "exito"],
                             ["host_nuevo", "==", True], ["fuera_horario", "==", True]]},
        "conclusion": "posible_suplantacion", "severidad": "alta", "certeza": 0.85,
    },
    {
        "nombre": "R4_archivo_sensible_sin_privilegio",
        "descripcion": "Usuario no administrador lee un archivo sensible",
        "condicion": {"si": [["accion", "==", "leer_archivo"], ["sensible", "==", True],
                             ["es_admin", "==", False]]},
        "conclusion": "acceso_sensible_no_autorizado", "severidad": "media", "certeza": 0.75,
    },
    {
        "nombre": "R5_sudo_sin_ser_admin",
        "descripcion": "Usuario no administrador usa privilegios de superusuario",
        "condicion": {"si": [["accion", "==", "usar_sudo"], ["es_admin", "==", False]]},
        "conclusion": "intento_escalada_privilegios", "severidad": "alta", "certeza": 0.85,
    },
    {
        "nombre": "R6_lectura_masiva",
        "descripcion": "20 o mas archivos leidos por el mismo usuario en 10 minutos",
        "condicion": {"si": [["accion", "==", "leer_archivo"], ["lecturas_10min", ">=", 20]]},
        "conclusion": "posible_exfiltracion", "severidad": "alta", "certeza": 0.80,
    },
    {
        "nombre": "R7_lectura_fuera_horario_host_nuevo",
        "descripcion": "Lectura de archivos fuera de horario desde un host no habitual",
        "condicion": {"si": [["accion", "==", "leer_archivo"], ["fuera_horario", "==", True],
                             ["host_nuevo", "==", True]]},
        "conclusion": "actividad_sospechosa_host_externo", "severidad": "media", "certeza": 0.60,
    },
]
 
 
def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for r in REGLAS:
            conn.execute(
                """INSERT INTO reglas (nombre, descripcion, condicion, conclusion, severidad, certeza)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (nombre) DO UPDATE SET descripcion=EXCLUDED.descripcion,
                     condicion=EXCLUDED.condicion, conclusion=EXCLUDED.conclusion,
                     severidad=EXCLUDED.severidad, certeza=EXCLUDED.certeza""",
                (r["nombre"], r["descripcion"], json.dumps(r["condicion"]),
                 r["conclusion"], r["severidad"], r["certeza"]))
        print(conn.execute("SELECT COUNT(*) FROM reglas").fetchone()[0], "reglas en la base")
 
 
if __name__ == "__main__":
    main()
 
