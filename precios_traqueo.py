#!/usr/bin/env python3
"""Traqueo de precios del hogar.

Todo el trabajo lo hace este script: consulta las tiendas con
`precios_sm.py` usando un navegador real, guarda el precio de cada día y avisa **solo cuando el
precio baja de lo normal** (no cuando está igual al de la vez pasada).

Modos:
    python precios_traqueo.py              # informe del día: el más barato de cada producto, con link
    python precios_traqueo.py --avisar     # SOLO las bajadas reales (silencio si no hay ninguna)
    python precios_traqueo.py --grupo 2    # un tercio de la lista (para repartir el trabajo)
    python precios_traqueo.py --item leche # un solo producto
    python precios_traqueo.py --historial leche   # últimos precios guardados

Criterio del aviso (`--avisar`):
  - "precio normal" de un producto = la mediana de los precios observados en los días anteriores.
  - Se avisa solo si el más barato de hoy está **al menos un 5% bajo** ese precio normal.
  - No se repite el mismo aviso: si ya se avisó ese producto a ese precio (o más bajo), se calla.
  - Mientras no haya **3 días** de historia, no se avisa nada: sin historia, cualquier precio parece
    una oferta y el aviso sería ruido.

Lista: `data/precios_traqueo.json` · Historial: `data/precios_historial/<item>.json`.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import subprocess
import sys
from datetime import datetime

# Raíz del proyecto (se puede fijar con la variable de entorno PRECIOS_HOME).
BASE = pathlib.Path(os.environ.get("PRECIOS_HOME") or pathlib.Path(__file__).resolve().parent)
DATA = BASE / "data"
LISTA = DATA / "precios_traqueo.json"
HISTORIAL = DATA / "precios_historial"
SCRIPT = BASE / "precios_sm.py"
PYTHON = os.environ.get("PYTHON_BIN") or sys.executable

BAJADA_MINIMA = 0.05      # 5% bajo el precio normal
DIAS_MINIMOS = 3          # sin esta historia, no se avisa


def sin_acentos(t: str) -> str:
    rep = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    return (t or "").translate(rep)


def pesos(n) -> str:
    return f"${int(n):,}".replace(",", ".")


def cargar_lista() -> list[dict]:
    return json.loads(LISTA.read_text(encoding="utf-8")).get("items", [])


def archivo_historial(item_id: str) -> pathlib.Path:
    return HISTORIAL / f"{item_id}.json"


def leer_historial(item_id: str) -> list[dict]:
    a = archivo_historial(item_id)
    return json.loads(a.read_text(encoding="utf-8")) if a.is_file() else []


# ---------------------------------------------------------------------------
def consultar(item: dict) -> dict:
    cmd = [str(PYTHON), str(SCRIPT), item["termino"], "--json"]
    for t in item.get("tiendas", ["santa-isabel"]):
        cmd += ["--tienda", t]
    salida = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    try:
        data = json.loads(salida.stdout)
    except Exception:
        return {"item": item["id"], "error": (salida.stderr or salida.stdout or "")[-200:]}
    mejores = []
    for r in data:
        if r.get("error") or not r.get("items"):
            continue
        orden = sorted(r["items"], key=lambda x: (x.get("unitario") or x["precio"], x["precio"]))
        for it in orden[:4]:
            mejores.append({
                "tienda": r.get("tienda", ""),
                "nombre": it["nombre"],
                "precio": it["precio"],
                "unitario": it.get("unitario"),
                "normal": it.get("normal"),
                "url": it.get("url", ""),
            })
    # Filtro de nombre: el buscador de las tiendas es difuso y devuelve cosas que no son
    # (un "aceite" que trae leche, un "pollo" que trae desodorante). Se exige que el nombre
    # traiga alguna de las palabras clave del producto.
    claves = [sin_acentos(w).lower() for w in item.get("filtro", [])]
    if claves:
        antes = len(mejores)
        mejores = [m for m in mejores if any(c in sin_acentos(m["nombre"]).lower() for c in claves)]
        if not mejores:
            return {"item": item["id"], "fecha": datetime.now().strftime("%Y-%m-%d"),
                    "mejores": [], "descartados": antes}
    mejores.sort(key=lambda x: (x.get("unitario") or x["precio"], x["precio"]))
    return {"item": item["id"], "fecha": datetime.now().strftime("%Y-%m-%d"),
            "mejores": mejores[:6]}


def guardar(res: dict) -> None:
    HISTORIAL.mkdir(parents=True, exist_ok=True)
    a = archivo_historial(res["item"])
    datos = leer_historial(res["item"])
    hoy = res["fecha"]
    if datos and datos[-1].get("fecha") == hoy:      # se reemplaza la lectura del día
        datos[-1] = {"fecha": hoy, "mejores": res["mejores"]}
    else:
        datos.append({"fecha": hoy, "mejores": res["mejores"]})
    a.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


REFERENCIA = DATA / "precios_referencia.json"


def leer_referencias() -> dict:
    return json.loads(REFERENCIA.read_text(encoding="utf-8")) if REFERENCIA.is_file() else {}


def guardar_referencias(d: dict) -> None:
    REFERENCIA.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def referencia_de(item_id: str) -> dict | None:
    """Precio de referencia dado a mano por el usuario ('normal' o 'caro'), si existe."""
    return leer_referencias().get(item_id)


def normal_de(item_id: str, hoy: str) -> int | None:
    """Precio normal: mediana de los días anteriores. None si todavía no hay historia suficiente."""
    ref = referencia_de(item_id)
    if ref and ref.get("precio_normal"):
        return int(ref["precio_normal"])
    previos = [d for d in leer_historial(item_id) if d.get("fecha") != hoy and d.get("mejores")]
    if len(previos) < DIAS_MINIMOS:
        return None
    valores = []
    for d in previos[-14:]:
        m = d["mejores"][0]
        valores.append(m.get("unitario") or m["precio"])
    return int(statistics.median(valores))


def ya_avisado(item_id: str, valor: int) -> bool:
    """¿Ya se avisó este producto a este precio (o más barato) alguna vez?"""
    for d in leer_historial(item_id):
        if d.get("aviso") is not None and d["aviso"] <= valor:
            return True
    return False


def marcar_aviso(item_id: str, valor: int) -> None:
    a = archivo_historial(item_id)
    datos = leer_historial(item_id)
    if datos:
        datos[-1]["aviso"] = valor
        a.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
def linea_producto(item: dict, m: dict) -> str:
    # El precio por unidad se muestra solo cuando es creíble (menor que el del paquete): si sale
    # mayor, es que la página mezcló el precio con otra cosa y es mejor no mostrarlo.
    u = ""
    if m.get("unitario") and m["unitario"] < m["precio"]:
        u = f" ({pesos(m['unitario'])} por unidad/kilo)"
    envase = m["nombre"][:58]
    partes = [f"*{item['etiqueta']}*: {pesos(m['precio'])}{u} en {m['tienda']}",
              f"  {envase}"]
    if m.get("normal") and m["normal"] > m["precio"]:
        partes.append(f"  antes {pesos(m['normal'])} en esa tienda")
    if m.get("url"):
        partes.append(f"  {m['url']}")
    return "\n".join(partes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--item")
    ap.add_argument("--historial")
    ap.add_argument("--grupo", type=int, choices=[1, 2, 3])
    ap.add_argument("--avisar", action="store_true",
                    help="imprime solo las bajadas reales; si no hay ninguna, no imprime nada")
    args = ap.parse_args()

    if args.historial:
        for d in leer_historial(args.historial)[-8:]:
            m = d["mejores"][0] if d["mejores"] else None
            if m:
                print(f"  {d['fecha']} · {pesos(m.get('unitario') or m['precio'])} · {m['nombre'][:45]}")
        return 0

    items = cargar_lista()
    if args.grupo:
        items = items[args.grupo - 1::3]
    if args.item:
        items = [i for i in items if i["id"] == args.item]

    hoy = datetime.now().strftime("%Y-%m-%d")
    alertas, informe, preguntas = [], [], []
    referencias = leer_referencias()
    preguntados_hoy = {d.get("preguntado") for d in leer_historial("_preguntas") if d}
    for item in items:
        res = consultar(item)
        if res.get("error") or not res.get("mejores"):
            if not args.avisar:
                informe.append(f"*{item['etiqueta']}*: no se pudo consultar")
            continue
        guardar(res)
        mejor = res["mejores"][0]
        valor = mejor.get("unitario") or mejor["precio"]
        normal = normal_de(item["id"], hoy)
        if normal and valor <= normal * (1 - BAJADA_MINIMA) and not ya_avisado(item["id"], valor):
            marca = f"bajó de {pesos(normal)} a {pesos(valor)}"
            alertas.append(linea_producto(item, mejor) + f"\n  {marca}")
            marcar_aviso(item["id"], valor)
        else:
            # Sin precio normal todavía: se pide una vez (máximo 3 por pasada) para aprender.
            ref = referencia_de(item["id"])
            ya_preguntado = ref and ref.get("preguntado")
            if not ref and len(preguntas) < 5:
                preguntas.append(
                    f"*{item['etiqueta']}*: {pesos(valor)} en {mejor['tienda']} "
                    f"({mejor['nombre'][:48]})\n  {mejor.get('url', '')}\n"
                    "  ¿Te parece caro o es precio normal?"
                )
                referencias.setdefault(item["id"], {})
                referencias[item["id"]]["preguntado"] = hoy
                referencias[item["id"]]["pregunta_precio"] = valor
                guardar_referencias(referencias)
        if not args.avisar:
            linea = linea_producto(item, mejor)
            if normal:
                linea += f"\n  (normal {pesos(normal)})"
            informe.append(linea)

    if args.avisar:
        if alertas:
            print("Bajaron estos productos:")
            print("\n\n".join(alertas))
        return 0
    print("\n\n".join(informe))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
