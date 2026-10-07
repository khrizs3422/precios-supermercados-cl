#!/usr/bin/env python3
"""Agrega un producto a la lista del traqueo de precios del hogar.

Uso:
    python precios_agregar.py "pan de molde" --filtro pan
    python precios_agregar.py "yogur natural" --termino "yogur natural 1 l" --filtro yogur
    python precios_agregar.py --listar
    python precios_agregar.py --quitar pan-de-molde

Queda en `data/precios_traqueo.json` y entra solo en la próxima pasada del traqueo (por ejemplo, el
cron diario). Es la vía para agregar productos sin editar el JSON a mano.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import unicodedata

# Raíz del proyecto (se puede fijar con la variable de entorno PRECIOS_HOME).
BASE = pathlib.Path(os.environ.get("PRECIOS_HOME") or pathlib.Path(__file__).resolve().parent)
LISTA = BASE / "data" / "precios_traqueo.json"
TIENDAS_POR_DEFECTO = ["santa-isabel", "jumbo", "unimarc", "lider"]


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:40] or "producto"


def leer() -> dict:
    return json.loads(LISTA.read_text(encoding="utf-8"))


def guardar(d: dict) -> None:
    LISTA.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("producto", nargs="?")
    ap.add_argument("--termino", help="cómo buscarlo en las tiendas (por defecto, el producto tal cual)")
    ap.add_argument("--filtro", action="append", default=[],
                    help="palabra que DEBE traer el nombre del producto (se puede repetir)")
    ap.add_argument("--tienda", action="append", default=[],
                    help="tienda donde buscarlo (por defecto las cuatro de siempre)")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--quitar")
    args = ap.parse_args()

    d = leer()

    if args.listar:
        for it in d["items"]:
            print(f"  {it['id']:16s} {it['etiqueta']:38s} busca «{it['termino']}» · filtro {it.get('filtro')}")
        return 0

    if args.quitar:
        antes = len(d["items"])
        d["items"] = [i for i in d["items"] if i["id"] != args.quitar]
        guardar(d)
        print(f"quitado {args.quitar}" if len(d["items"]) < antes else f"no existía {args.quitar}")
        return 0

    if not args.producto:
        print(__doc__)
        return 2

    nuevo = {
        "id": slug(args.producto),
        "etiqueta": args.producto.strip(),
        "termino": args.termino or args.producto.strip(),
        "filtro": args.filtro or [slug(args.producto).split("-")[0]],
        "tiendas": args.tienda or TIENDAS_POR_DEFECTO,
    }
    if any(i["id"] == nuevo["id"] for i in d["items"]):
        print(f"ya estaba en la lista: {nuevo['id']}")
        return 0
    d["items"].append(nuevo)
    guardar(d)
    print(f"agregado: {nuevo['id']} · busca «{nuevo['termino']}» · filtro {nuevo['filtro']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
