# Chilean supermarket prices — automatic tracker

Python scripts to **track the price of a list of products** across Chilean supermarkets and
pharmacies and **alert you only when the price really drops**.

The problem it solves: in Chile supermarket prices change every week and the stores have no public
API, so comparing by hand takes time and real drops get lost among fake discounts. These scripts
query the stores with a real browser, store each day's price and alert only when a product's price
falls below its own history.

- Author: **Christopher Aguila** ([@khrizs3422](https://github.com/khrizs3422))
- License: MIT

## How it works

1. `precios_sm.py` connects over **CDP** (Chrome DevTools Protocol) to a real Chrome/Chromium browser
   that is already open, visits each store's search page, waits for it to render and reads the prices
   from the rendered page. It supports WooCommerce and Shopify stores (which expose their search as
   JSON) and plain HTML stores read through CSS selectors.
2. `precios_traqueo.py` walks the product list, stores the day's result in a history file and
   computes each product's **normal price** (the median of previous days).
3. With `--avisar`, the script prints **only real drops**: today's cheapest offer that is at least
   **5% below** its normal price and that has not been reported before at that price. With fewer than
   **3 days** of history it stays silent: without history, any price looks like a bargain.

Output is a short text message, ready to send over WhatsApp, Telegram, email or a cron job.
The heavy lifting happens in the scripts: it costs no model tokens.

## Requirements

- Python 3.10 or newer.
- `websockets` (`pip install -r requirements.txt`).
- A Chromium-based browser (Chrome, Edge, Brave) running with remote debugging:

```bash
chrome.exe --remote-debugging-port=9222 --user-data-dir=/path/to/profile
```

The port can be changed with the `CDP_HOST` environment variable (default `http://127.0.0.1:9222`).

## Install

```bash
git clone https://github.com/khrizs3422/precios-supermercados-cl.git
cd precios-supermercados-cl
pip install -r requirements.txt
mkdir -p data
cp precios_traqueo.example.json data/precios_traqueo.json    # then edit your list
```

## Usage

Query one product across every configured store:

```bash
python precios_sm.py "leche entera 1 l"
```

Query a single store, or dump the raw page structure to recalibrate selectors:

```bash
python precios_sm.py "leche entera 1 l" --tienda jumbo
python precios_sm.py "leche entera 1 l" --diag
```

Add, list and remove products:

```bash
python precios_agregar.py "pan de molde" --filtro pan
python precios_agregar.py --listar
python precios_agregar.py --quitar pan-de-molde
```

Daily report, per-product history and drop alerts:

```bash
python precios_traqueo.py                     # cheapest offer per product, with link
python precios_traqueo.py --historial leche   # last stored prices for one product
python precios_traqueo.py --avisar            # only real drops; prints nothing if there are none
python precios_traqueo.py --grupo 2           # one third of the list (to spread the load)
```

`--avisar` is meant for a cron job: when nothing dropped it prints nothing and bothers nobody.
Example schedule (every day at 9:00):

```
0 9 * * *  cd /path/precios-supermercados-cl && python precios_traqueo.py --avisar
```

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `CDP_HOST` | `http://127.0.0.1:9222` | Where the browser with remote debugging listens |
| `PRECIOS_HOME` | folder holding the scripts | Project root (data lives in `<root>/data`) |
| `PYTHON_BIN` | the Python running the script | Interpreter used to call `precios_sm.py` |

Stores are defined in the `TIENDAS` dict inside `precios_sm.py`: display name, search URL, CSS
selector and, when needed, a tiny script that dismisses cookie banners or delivery-mode dialogs that
cover the results.

## Layout

```
precios-supermercados-cl/
├── precios_sm.py                 # queries the stores over CDP, returns prices
├── precios_traqueo.py            # history, normal price and drop alerts
├── precios_agregar.py            # add, remove and list products
├── precios_traqueo.example.json  # sample product list
├── requirements.txt
└── data/                         # (not versioned) real list, history and references
    ├── precios_traqueo.json
    ├── precios_referencia.json
    └── precios_historial/<product>.json
```

## Known limitations

- **It depends on each store's HTML.** If a store changes its search page, its selectors or its price
  format, that store stops working until `TIENDAS` is updated. The `--diag` mode exists for fast
  recalibration.
- **It needs a running browser.** There is no public API; with no browser listening for remote
  debugging there are no prices.
- Unit price (per kilo or per litre) is shown only when it makes sense: if it comes out higher than
  the pack price, the page mixed up data and it is omitted.
- Store search is fuzzy and returns unrelated products (a "cooking oil" query that brings milk).
  That is why each product can carry a `filtro` list of words that must appear in the name.
- Go easy on the stores: this script performs a real navigation per product, so a long list is
  better split with `--grupo`. Check each site's terms of use and do not hammer their servers.

## License

MIT — see [LICENSE](LICENSE).
