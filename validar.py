import os
from collections import defaultdict
 
import psycopg
from dotenv import load_dotenv
 
from motor_reglas import TZ
 
load_dotenv()
 
 
def matriz(unidades, positivas_reales, positivas_pred):
    vp = len(positivas_reales & positivas_pred)
    fp = len(positivas_pred - positivas_reales)
    fn = len(positivas_reales - positivas_pred)
    vn = len(unidades) - vp - fp - fn
    prec = vp / (vp + fp) if vp + fp else 0
    rec = vp / (vp + fn) if vp + fn else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    return {"VP": vp, "FP": fp, "FN": fn, "VN": vn, "exactitud": (vp + vn) / len(unidades),
            "precision": prec, "recall": rec, "f1": f1}
 
 
def revisar_reglas(reglas, disparadas):
    """Revision estructural: reglas muertas, cadenas rotas, duplicadas o contradictorias."""
    hallazgos = []
    concluyen = {r["conclusion"] for r in reglas}
    vistas = {}
    for r in reglas:
        premisas = tuple(sorted(map(tuple, r["condicion"]["si"]), key=str))
        for campo, op, valor in r["condicion"]["si"]:
            if op == "tiene" and valor not in concluyen:
                hallazgos.append(f"{r['nombre']}: depende de '{valor}' pero ninguna regla lo concluye")
        if premisas in vistas:
            o = vistas[premisas]
            tipo = "CONTRADICTORIA" if o["severidad"] != r["severidad"] or o["conclusion"] != r["conclusion"] else "REDUNDANTE"
            hallazgos.append(f"{r['nombre']} y {o['nombre']} tienen las mismas premisas ({tipo})")
        vistas[premisas] = r
        if r["nombre"] not in disparadas:
            hallazgos.append(f"{r['nombre']}: nunca se disparo con los datos simulados")
    return hallazgos or ["Sin hallazgos"]
 
 
def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        ev = {i: (u, f.astimezone(TZ).date(), et, inc) for i, u, f, et, inc in conn.execute(
            "SELECT id, usuario, fecha_hora, etiqueta_real, incidente_id FROM eventos")}
        alertas = conn.execute("SELECT evento_id, origen, regla_id FROM alertas").fetchall()
        reglas = [dict(id=i, nombre=n, condicion=c, conclusion=k, severidad=s) for i, n, c, k, s in conn.execute(
            "SELECT id, nombre, condicion, conclusion, severidad FROM reglas ORDER BY id")]
 
    # ---- 1) deteccion por incidente
    incidentes = defaultdict(lambda: {"tipo": "", "reglas": False, "estadistico": False})
    for u, d, et, inc in ev.values():
        if inc:
            incidentes[inc]["tipo"] = et
    for evento_id, origen, _ in alertas:
        inc = ev[evento_id][3]
        if inc:
            incidentes[inc]["reglas" if origen == "regla" else "estadistico"] = True
    print("== Deteccion por incidente ==")
    print(f"{'#':>2} {'tipo':22} reglas  estadistica  combinado")
    for inc, d in sorted(incidentes.items()):
        si = lambda b: "si" if b else "NO"
        print(f"{inc:>2} {d['tipo']:22} {si(d['reglas']):6}  {si(d['estadistico']):11}  {si(d['reglas'] or d['estadistico'])}")
 
    # ---- 2) matriz de confusion por usuario-dia
    unidades = {(u, d) for u, d, _, _ in ev.values()}
    reales = {(u, d) for u, d, et, _ in ev.values() if et != "normal"}
    print(f"\n== Matriz de confusion (unidad = usuario-dia, {len(unidades)} unidades, {len(reales)} con ataque real) ==")
    for nombre, filtro in [("Solo reglas", {"regla"}), ("Solo estadistica", {"estadistico"}),
                           ("Combinado", {"regla", "estadistico"})]:
        pred = {(ev[e][0], ev[e][1]) for e, o, _ in alertas if o in filtro}
        m = matriz(unidades, reales, pred)
        print(f"{nombre:17} VP={m['VP']:2} FP={m['FP']:2} FN={m['FN']:2} VN={m['VN']:2} | "
              f"exactitud={m['exactitud']:.2f} precision={m['precision']:.2f} recall={m['recall']:.2f} F1={m['f1']:.2f}")
 
    # ---- 3) revision de la base de conocimientos
    disparadas = {r["nombre"] for r in reglas if r["id"] in {rid for _, _, rid in alertas}}
    print("\n== Revision de reglas ==")
    for h in revisar_reglas(reglas, disparadas):
        print(" -", h)
 
 
if __name__ == "__main__":
    main()