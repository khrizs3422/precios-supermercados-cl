#!/usr/bin/env python3
"""Precios de supermercados: consulta las tiendas con un navegador REAL y devuelve precios.

Las tiendas chilenas no tienen API pública (bloquean el acceso automático), así que el script se
conecta por CDP a un Chrome/Chromium real que queda abierto y lee el precio de la página ya
renderizada. Todo el trabajo pesado lo hace este script: la salida es un resumen corto.

Uso:
    python precios_sm.py "leche 1 l"                 # todas las tiendas configuradas
    python precios_sm.py "leche 1 l" --tienda jumbo  # una sola
    python precios_sm.py "leche 1 l" --diag          # muestra la estructura cruda (para calibrar)
    python precios_sm.py "leche 1 l" --json          # salida cruda en JSON

Antes hay que dejar un navegador corriendo con depuración remota:
    chrome.exe --remote-debugging-port=9222 --user-data-dir=/ruta/al/perfil
El destino se puede cambiar con la variable de entorno CDP_HOST (por defecto 127.0.0.1:9222).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import websockets

# Navegador real con depuración remota (configurable con la variable de entorno CDP_HOST).
CDP_HOST = os.environ.get("CDP_HOST", "http://127.0.0.1:9222")

# Tiendas. `buscar` es la URL de resultados; si alguna cambia, se ajusta aquí.
PREPARAR: dict[str, str] = {
    # Cruz Verde abre un cartel de cookies que tapa la caja de búsqueda.
    "cruzverde": "(() => { const b=[...document.querySelectorAll('button,a')].find(x=>/aceptar|cerrar|entendido|permitir/i.test(x.innerText||'')); if(b){b.click(); return b.innerText;} return 'sin cartel'; })()",
    # Líder abre un cuadro de "modo de entrega" que tapa el listado.
    "lider": "(() => { const b=[...document.querySelectorAll('button,a,[role=button]')].find(x=>/cancelar|cerrar|omitir|seguir/i.test(x.innerText||'')); if(b){b.click(); return b.innerText;} return 'sin cuadro'; })()",
}

TIENDAS: dict[str, dict] = {
    "cugat": {
        "nombre": "Supermercado Cugat",
        # WooCommerce: su buscador público devuelve productos con precio (y el precio normal).
        "woocommerce": "https://www.cugat.cl",
    },
    "pedregal": {
        "nombre": "Alimentos del Pedregal",
        "shopify": "https://alimentosdelpedregal.com",
    },
    "cruzverde": {
        "nombre": "Cruz Verde",
        # Su buscador no va por URL: hay que escribir en la caja (y cerrar el cartel de cookies).
        "buscar": "https://www.cruzverde.cl/",
        "caja": "input[placeholder*='Buscar'], input[aria-label*='Buscar']",
    },
    "ahumada": {
        "nombre": "Farmacias Ahumada",
        "buscar": "https://www.farmaciasahumada.cl/search?q={q}",
        "selector": "",
        "bandera_comuna": None,
    },

    "santa-isabel": {
        "nombre": "Santa Isabel",
        "buscar": "https://www.santaisabel.cl/busqueda?ft={q}",
        "selector": "[data-testid='product-card'], .product-card, li[class*='product']",
        "bandera_comuna": None,
    },
    "jumbo": {
        "nombre": "Jumbo",
        "buscar": "https://www.jumbo.cl/busqueda?ft={q}",
        "selector": "[data-testid='product-card'], .product-card, li[class*='product']",
        "bandera_comuna": None,
    },
    "unimarc": {
        "nombre": "Unimarc",
        "buscar": "https://www.unimarc.cl/search?q={q}",
        "selector": "[class*='product'], li[class*='item']",
        "bandera_comuna": None,
    },
    "tottus": {
        "nombre": "Tottus",
        "buscar": "https://www.tottus.cl/tottus-cl/search?Ntt={q}",
        "selector": "[class*='product'], li[class*='item']",
        "bandera_comuna": None,
    },
    "lider": {
        "nombre": "Líder",
        # OJO: el sitio nuevo es super.lider.cl (no www.lider.cl/supermercado) y sí busca por URL.
        "buscar": "https://super.lider.cl/search?q={q}",
        "selector": "",
        "bandera_comuna": None,
    },
}


async def _cdp(ws, method, params=None, timeout=30):
    """Manda un comando CDP y espera su respuesta."""
    await ws.send(json.dumps({"id": __import__("random").randint(1, 10**9), "method": method,
                              "params": params or {}}))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if msg.get("method") == "Page.loadEventFired":
            continue
        if "result" in msg or "error" in msg:
            return msg


async def _evaluar(ws, expresion, timeout=30):
    r = await _cdp(ws, "Runtime.evaluate",
                   {"expression": expresion, "returnByValue": True, "awaitPromise": True},
                   timeout=timeout)
    res = r.get("result", {}).get("result", {})
    return res.get("value")


EXTRACTOR = r"""
(() => {
  const conPrecio = el => /\$\s?[\d.]{3,}/.test(el.innerText || '');
  // Candidatas: tarjetas chicas con precio y un enlace adentro.
  let cand = [...document.querySelectorAll('div,li,article')].filter(el =>
    conPrecio(el) && (el.innerText || '').length < 320 && el.querySelector('a[href]'));
  // Quedarse con las mas internas (que no contengan otra candidata).
  cand = cand.filter(el => !cand.some(otro => otro !== el && el.contains(otro)));
  const items = [];
  for (const el of cand) {
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
    const m = [...t.matchAll(/\$\s?([\d.]{3,})/g)].map(x => parseInt(x[1].replace(/\./g, ''), 10));
    if (!m.length) continue;
    const a = el.querySelector('a[href]');
    const href = a ? a.getAttribute('href') : '';
    if (href && /simulador|tarjeta-cl|ayuda|ingresar|login|sitemap/i.test(href)) continue;
    const uni = t.match(/\$\s?([\d.]{3,})\s*(x\s*(un|lt|kg)|c\/u)/i);
    let nombre = t.replace(/\$\s?[\d.]{3,}/g, ' ')
      .replace(/(\$\s?[\d.]{3,}\s*)?x\s*(un|lt|kg)/gi, ' ')
      .replace(/Santo Cyber[^.]*\./gi, ' ')
      .replace(/Cyber[^.]*\./gi, ' ')
      .replace(/(\d+)%\s*dcto\.?/gi, ' ')
      .replace(/Lleva \d+ por/gi, ' ')
      .replace(/Agotado/gi, ' ')
      .replace(/^Oferta\s+/i, ' ')
      .replace(/\s+/g, ' ').trim();
    items.push({nombre: nombre.slice(0, 90), precio: m[0], normal: m[1] || null,
                unitario: uni ? parseInt(uni[1].replace(/\./g, ''), 10) : null,
                url: href ? new URL(href, location.origin).href : ''});
  }
  const vistos = new Set(); const unicos = [];
  for (const o of items) { const k = o.nombre + o.precio; if (!vistos.has(k)) { vistos.add(k); unicos.push(o); } }
  unicos.sort((a, b) => (a.unitario || a.precio) - (b.unitario || b.precio));
  return {titulo: document.title, url: location.href, total: unicos.length, items: unicos.slice(0, 40)};
})()
"""


def consultar_shopify(cfg: dict, termino: str) -> dict:
    """Tienda Shopify: su buscador público devuelve productos con precio (y el precio 'antes')."""
    base = cfg["shopify"].rstrip("/")
    url = (base + "/search/suggest.json?q=" + urllib.parse.quote(termino) +
           "&resources%5Btype%5D=product&resources%5Blimit%5D=10")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    datos = json.loads(urllib.request.urlopen(req, timeout=40).read())
    prods = (datos.get("resources", {}).get("results", {}).get("products") or [])
    items = []
    for p in prods:
        precio = p.get("price")
        antes = p.get("compare_at_price_max") or p.get("compare_at_price_min")
        items.append({
            "nombre": (p.get("title") or "")[:90],
            "precio": int(float(precio)) if precio else 0,
            "normal": int(float(antes)) if antes not in (None, "", "0") else None,
            "unitario": None,
            "url": f"{base}/products/{p.get('handle','')}",
        })
    items = [i for i in items if i["precio"] > 0]
    items.sort(key=lambda x: x["precio"])
    return {"tienda": cfg["nombre"], "url": url, "total": len(items), "items": items[:40]}


def consultar_woocommerce(cfg: dict, termino: str) -> dict:
    """Tienda WooCommerce: la API pública de su buscador (Store API) da nombre, precio y link."""
    base = cfg["woocommerce"].rstrip("/")
    url = (base + "/wp-json/wc/store/v1/products?search=" +
           urllib.parse.quote(termino) + "&per_page=20")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    datos = json.loads(urllib.request.urlopen(req, timeout=40).read())
    items = []
    for p in datos if isinstance(datos, list) else []:
        precios = p.get("prices") or {}
        dec = int(precios.get("currency_minor_unit") or 0)
        def a_pesos(v):
            try:
                return int(round(float(v) / (10 ** dec)))
            except Exception:
                return 0
        precio = a_pesos(precios.get("price"))
        normal = a_pesos(precios.get("regular_price")) or None
        items.append({
            "nombre": (p.get("name") or "")[:90],
            "precio": precio,
            "normal": normal if normal and normal > precio else None,
            "unitario": None,
            "url": p.get("permalink") or "",
        })
    items = [i for i in items if i["precio"] > 0]
    items.sort(key=lambda x: x["precio"])
    return {"tienda": cfg["nombre"], "url": url, "total": len(items), "items": items[:40]}


async def consultar(nombre_clave: str, termino: str, diag: bool = False) -> dict:
    cfg = TIENDAS[nombre_clave]
    if cfg.get("shopify"):
        return consultar_shopify(cfg, termino)
    if cfg.get("woocommerce"):
        return consultar_woocommerce(cfg, termino)
    url = cfg["buscar"].format(q=urllib.parse.quote_plus(termino))

    tabs = json.loads(urllib.request.urlopen(CDP_HOST + "/json/list", timeout=10).read())
    pagina = next((t for t in tabs if t.get("type") == "page"), None)
    if not pagina:
        return {"tienda": cfg["nombre"], "error": "no hay pestaña abierta en el navegador configurado"}

    async with websockets.connect(pagina["webSocketDebuggerUrl"], max_size=20 * 1024 * 1024) as ws:
        await _cdp(ws, "Page.enable")
        await _cdp(ws, "Runtime.enable")
        await _cdp(ws, "Page.navigate", {"url": url})

        # Algunas tiendas abren un cuadro que tapa el listado (Líder, el modo de entrega).
        preparar = PREPARAR.get(nombre_clave)
        if preparar:
            await asyncio.sleep(4)
            await _evaluar(ws, preparar)

        # Tiendas que no buscan por URL: se escribe en su caja de búsqueda y se aprieta Enter.
        caja = cfg.get("caja")
        if caja:
            selector = json.dumps(caja)
            await _evaluar(ws, f"document.querySelector({selector})?.focus()")
            await _cdp(ws, "Input.insertText", {"text": termino})
            for tipo in ("keyDown", "keyUp"):
                await _cdp(ws, "Input.dispatchKeyEvent", {"type": tipo, "key": "Enter",
                                                          "code": "Enter", "windowsVirtualKeyCode": 13})
            await asyncio.sleep(3)

        # Esperar a que aparezcan precios en pantalla (la página se arma sola).
        for _ in range(20):
            await asyncio.sleep(1.5)
            listo = await _evaluar(ws, "document.body.innerText.match(/\\$[\\d.]{3,}/g)?.length || 0")
            if listo and int(listo) > 3:
                break

        if diag:
            crudo = await _evaluar(ws, "document.body.innerText.slice(0, 1500)")
            return {"tienda": cfg["nombre"], "url": url, "texto_crudo": crudo}

        datos = await _evaluar(ws, EXTRACTOR, timeout=60)
        if not datos:
            return {"tienda": cfg["nombre"], "url": url, "error": "no se pudo leer la página"}
        datos["tienda"] = cfg["nombre"]
        return datos


def texto_salida(r: dict) -> str:
    if r.get("texto_crudo") is not None:
        return f"=== {r.get('tienda')} (diagnóstico)\n{r['texto_crudo'][:700]}"
    L = [f"=== {r.get('tienda')}" + (f" — {r.get('total')} productos" if r.get("total") else "")]
    if r.get("error"):
        L.append(f"   error: {r['error']}")
        return "\n".join(L)
    for it in r.get("items", [])[:15]:
        precio = f"${it['precio']:,}".replace(",", ".")
        extra = ""
        if it.get("normal") and it["normal"] > it["precio"]:
            antes = f"${it['normal']:,}".replace(",", ".")
            pct = round(100 - it["precio"] * 100 / it["normal"])
            extra = f"  (antes {antes}, -{pct}%)"
        if it.get("unitario"):
            extra += f"  ${it['unitario']:,} c/u".replace(",", ".")
        L.append(f"   {precio:>9}{extra} · {it['nombre'][:58]}")
    return "\n".join(L)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("termino")
    ap.add_argument("--tienda", action="append")
    ap.add_argument("--diag", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    claves = args.tienda or list(TIENDAS)
    resultados = []
    for clave in claves:
        if clave not in TIENDAS:
            print(f"(tienda desconocida: {clave})", file=sys.stderr)
            continue
        try:
            resultados.append(await consultar(clave, args.termino, diag=args.diag))
        except Exception as e:
            resultados.append({"tienda": TIENDAS[clave]["nombre"], "error": str(e)[:200]})

    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=1))
    else:
        print("\n".join(texto_salida(r) for r in resultados))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
