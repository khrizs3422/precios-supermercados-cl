# Precios de supermercados (Chile) — traqueo automático

Scripts en Python para **seguir el precio de una lista de productos** en los supermercados y
farmacias chilenas y **avisar solo cuando el precio baja de lo normal**.

El problema que resuelve: en Chile los precios de supermercado cambian todas las semanas y las
tiendas no tienen API pública, así que comparar a mano cuesta tiempo y las bajadas reales se
pierden entre ofertas falsas. Estos scripts consultan las tiendas con un navegador real, guardan
el precio de cada día y avisan únicamente cuando el precio baja respecto de su propio historial.

- Autor: **Christopher Aguila** ([@khrizs3422](https://github.com/khrizs3422))
- Licencia: MIT

## Cómo funciona

1. `precios_sm.py` se conecta por **CDP** (Chrome DevTools Protocol) a un navegador Chrome/Chromium
   real que está abierto, entra al buscador de cada tienda, espera a que la página cargue y lee los
   precios ya renderizados. Soporta tiendas WooCommerce y Shopify (que exponen su buscador en JSON)
   y tiendas que solo ofrecen HTML, que se leen por selector CSS.
2. `precios_traqueo.py` recorre la lista de productos, guarda el resultado del día en un historial y
   calcula el **precio normal** de cada producto (la mediana de los días anteriores).
3. Con `--avisar`, el script imprime **solo las bajadas reales**: el producto más barato del día que
   esté al menos un **5 % bajo** su precio normal y que no se haya avisado antes a ese precio.
   Sin al menos **3 días** de historia no avisa nada: sin historia, cualquier precio parece oferta.

El resultado es un texto corto, listo para mandar por WhatsApp, Telegram, correo o un cron.
El trabajo pesado lo hacen los scripts: no consume tokens de ningún modelo.

## Requisitos

- Python 3.10 o superior.
- `websockets` (`pip install -r requirements.txt`).
- Un navegador basado en Chromium (Chrome, Edge, Brave) abierto con depuración remota:

```bash
chrome.exe --remote-debugging-port=9222 --user-data-dir=/ruta/al/perfil
```

El puerto se puede cambiar con la variable de entorno `CDP_HOST` (por defecto
`http://127.0.0.1:9222`).

## Instalación

```bash
git clone https://github.com/khrizs3422/precios-supermercados-cl.git
cd precios-supermercados-cl
pip install -r requirements.txt
mkdir -p data
cp precios_traqueo.example.json data/precios_traqueo.json    # y edita tu lista
```

## Uso

Consultar un producto en todas las tiendas configuradas:

```bash
python precios_sm.py "leche entera 1 l"
```

Consultar en una sola tienda, o ver la estructura cruda de la página para calibrar selectores:

```bash
python precios_sm.py "leche entera 1 l" --tienda jumbo
python precios_sm.py "leche entera 1 l" --diag
```

Agregar, listar y quitar productos de la lista:

```bash
python precios_agregar.py "pan de molde" --filtro pan
python precios_agregar.py --listar
python precios_agregar.py --quitar pan-de-molde
```

Informe del día, historial de un producto y aviso de bajadas:

```bash
python precios_traqueo.py                     # el más barato de cada producto, con link
python precios_traqueo.py --historial leche   # últimos precios guardados de un producto
python precios_traqueo.py --avisar            # solo las bajadas reales; si no hay, no imprime nada
python precios_traqueo.py --grupo 2           # un tercio de la lista (para repartir la carga)
```

`--avisar` está pensado para un cron: si no hay ninguna bajada, no imprime nada y no molesta a
nadie. Ejemplo de tarea programada (cada día a las 9:00):

```
0 9 * * *  cd /ruta/precios-supermercados-cl && python precios_traqueo.py --avisar
```

## Configuración

| Variable de entorno | Por defecto | Para qué sirve |
| --- | --- | --- |
| `CDP_HOST` | `http://127.0.0.1:9222` | Dónde escucha el navegador con depuración remota |
| `PRECIOS_HOME` | carpeta de los scripts | Raíz del proyecto (los datos quedan en `<raíz>/data`) |
| `PYTHON_BIN` | el Python que ejecuta el script | Intérprete con el que se llama a `precios_sm.py` |

Las tiendas están definidas en el diccionario `TIENDAS` de `precios_sm.py`: nombre, URL de búsqueda,
selector CSS y, cuando hace falta, un pequeño script para cerrar carteles de cookies o cuadros de
"modo de entrega" que tapan el listado.

## Estructura

```
precios-supermercados-cl/
├── precios_sm.py                 # consulta las tiendas por CDP y devuelve precios
├── precios_traqueo.py            # historial, precio normal y avisos de bajada
├── precios_agregar.py            # alta, baja y listado de productos
├── precios_traqueo.example.json  # ejemplo de lista de productos
├── requirements.txt
└── data/                         # (no versionado) lista real, historial y referencias
    ├── precios_traqueo.json
    ├── precios_referencia.json
    └── precios_historial/<producto>.json
```

## Limitaciones conocidas

- **Depende del HTML de cada tienda.** Si una tienda cambia su buscador, su selector o su formato
  de precio, esa tienda deja de responder hasta ajustar `TIENDAS`. El modo `--diag` existe para
  recalibrar rápido.
- **Necesita un navegador abierto.** No hay API pública; si el navegador con depuración remota no
  está corriendo, no hay precios.
- El precio por unidad (kilo o litro) se muestra solo cuando es creíble: si sale mayor que el del
  paquete, la página mezcló datos y se omite.
- El buscador de las tiendas es difuso y devuelve productos que no son (un "aceite" que trae leche).
  Por eso cada producto puede llevar un `filtro` con las palabras que deben aparecer en el nombre.
- Consulta las tiendas de a poco: este script hace una navegación real por producto, así que una
  lista muy larga conviene repartirla con `--grupo`. Revisa los términos de uso de cada sitio y no
  lo uses para martillar los servidores.

## Licencia

MIT — ver [LICENSE](LICENSE).
