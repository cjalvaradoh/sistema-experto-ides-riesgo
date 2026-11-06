import os
from datetime import timedelta
 
import psycopg
from dotenv import load_dotenv
 
load_dotenv()
 
BRECHA_CASO = timedelta(minutes=30)   # alertas separadas por menos de esto = mismo caso
ORDEN_SEV = {"baja": 0, "media": 1, "alta": 2}
 
 
def agrupar_casos(alertas):
    """alertas: dicts con id, usuario, fecha_hora, origen, conclusion, severidad, certeza."""
    casos = []
    for a in sorted(alertas, key=lambda x: (x["usuario"], x["fecha_hora"])):
        ultimo = casos[-1] if casos else None
        if ultimo and ultimo["usuario"] == a["usuario"] and a["fecha_hora"] - ultimo["fin"] <= BRECHA_CASO:
            ultimo["alertas"].append(a)
            ultimo["fin"] = max(ultimo["fin"], a["fecha_hora"])
        else:
            casos.append({"usuario": a["usuario"], "inicio": a["fecha_hora"],
                          "fin": a["fecha_hora"], "alertas": [a]})
    return [resolver(c) for c in casos]
 
 
def resolver(caso):
    al = caso["alertas"]
    fuentes = sorted({a["origen"] for a in al})
    sev = max((a["severidad"] for a in al), key=ORDEN_SEV.get)
    if len(fuentes) == 2 and sev == "media":
        sev = "alta"                      # dos fuentes independientes coinciden: se sube un nivel
    cf = {}
    for f in fuentes:                     # mejor certeza de cada fuente
        cf[f] = max(float(a["certeza"]) for a in al if a["origen"] == f)
    certeza = 0.0
    for c in cf.values():                 # combinacion: c = c1 + c2 * (1 - c1)
        certeza = certeza + c * (1 - certeza)
    caso.update({
        "severidad": sev, "certeza": round(certeza, 2), "fuentes": "+".join(fuentes),
        "resumen": ", ".join(sorted({a["conclusion"] for a in al}))})
    return caso
 
 
def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        cur = conn.execute("""SELECT a.id, e.usuario, e.fecha_hora, a.origen, a.conclusion, a.severidad, a.certeza
                              FROM alertas a JOIN eventos e ON e.id = a.evento_id""")
        cols = [c.name for c in cur.description]
        alertas = [dict(zip(cols, f)) for f in cur.fetchall()]
        casos = agrupar_casos(alertas)
 
        conn.execute("UPDATE alertas SET caso_id = NULL")
        conn.execute("DELETE FROM casos")
        for c in casos:
            caso_id = conn.execute(
                """INSERT INTO casos (usuario, inicio, fin, severidad, certeza, fuentes, resumen)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (c["usuario"], c["inicio"], c["fin"], c["severidad"], c["certeza"],
                 c["fuentes"], c["resumen"])).fetchone()[0]
            conn.execute("UPDATE alertas SET caso_id = %s WHERE id = ANY(%s)",
                         (caso_id, [a["id"] for a in c["alertas"]]))
        print(f"{len(alertas)} alertas -> {len(casos)} casos")
        for fila in conn.execute("""SELECT id, usuario, severidad, certeza, fuentes, resumen
                                    FROM casos ORDER BY inicio"""):
            print(fila)
 
 
if __name__ == "__main__":
    main()