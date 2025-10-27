
# -*- coding: utf-8 -*-
import os, io, csv, re, unicodedata
from urllib.parse import urlparse
import requests

BASE = "https://apiv2.infortisa.com"
CSV_EXT_URL = f"{BASE}/api/Tarifa/GetFileV5EXT"

# ---------- util ----------
def _strip_accents(s):
    if s is None: return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch) and ord(ch) < 128)

def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(s).lower().strip())

def _to_float_es(val):
    if val is None: 
        return 0.0
    s = str(val).replace("\u00a0"," ").strip()
    s = s.replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return float(s) if s else 0.0
    except Exception:
        m = re.search(r"[-+]?\d*\.?\d+", s or "")
        return float(m.group()) if m else 0.0

def _to_int(val):
    try:
        return int(round(float(str(val).replace(",", ".").strip())))
    except Exception:
        return 0

def _peso_from_row(row):
    """Devuelve el peso en **kg** leyendo la columna PESO (o variantes).
    Acepta: '0,24', '0.24', '240 g', '240gr', '240G'."""
    raw = (row.get('PESO') or row.get('Peso') or row.get('peso') or
           row.get('WEIGHT') or row.get('Weight') or row.get('weight') or '')
    raw = str(raw).strip()
    if not raw:
        return 0.0
    txt = raw.replace(",", ".").lower()
    m = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*([a-z]*)', txt)
    if not m:
        try:
            return float(txt)
        except Exception:
            return 0.0
    val = float(m.group(1))
    unit = m.group(2)
    if unit.startswith('g'):
        val /= 1000.0
    return round(val, 6)

def _col(row, candidates):
    """Busca la primera columna existente (ignorando tildes/mayús/espacios)."""
    keys = {_norm_key(k): k for k in row.keys()}
    for c in candidates:
        k = keys.get(_norm_key(c))
        if k is not None:
            v = row.get(k)
            if v not in (None, "", "null", "None"):
                return str(v).strip()
    return ""

def _sum_stock(r):
    return _to_int(r.get("STOCKCENTRAL")) + _to_int(r.get("STOCKPALMA")) + _to_int(r.get("STOCKEXTERNO"))

def _normalize_image_url(url: str):
    if not url: return None
    s = str(url).strip()
    try: urlparse(s)
    except Exception: pass
    return s or None

def _desc_to_html(raw: str) -> str:
    if not raw: return ""
    txt = str(raw).replace("\r\n","\n").replace("\r","\n").strip()
    if "<" in txt and ">" in txt:
        return txt
    parts = [p.strip() for p in re.split(r"\s*[•\-]\s+|\n+", txt) if p.strip()]
    return "<br/>".join(parts) if parts else txt

# ---------- fetch ----------
def _fetch_csv(app_key: str, mode="query", header_name: str = "X-Api-Key"):
    params, headers = {}, {}
    if mode == "query": params["user"] = app_key
    elif mode == "header": headers[header_name] = app_key
    elif mode == "bearer": headers["Authorization"] = f"Bearer {app_key}"
    r = requests.get(CSV_EXT_URL, params=params, headers=headers, timeout=120)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

# ---------- entrypoint ----------
def get_items(app_key=None, auth_mode="query", header_name="X-Api-Key",
              min_stock=1, limit=None, vendor_name=None, **kwargs):
    app_key = (app_key or os.getenv("INFORTISA_APP_KEY") or "").strip()
    if not app_key:
        raise RuntimeError("Falta APP KEY (INFORTISA_APP_KEY o parámetro).")

    try: min_stock = int(min_stock or 0)
    except Exception: min_stock = 0
    lim = int(limit) if (isinstance(limit, (int, str)) and str(limit).isdigit()) else None

    csv_text = _fetch_csv(app_key, mode=auth_mode, header_name=header_name)
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")

    NAME = ['titulo','título','name','title']
    CODE = ['codigointerno','codigo','código','sku','ref','referencia','productcode','itemcode']
    BAR  = ['ean/upc','ean','barcode','código barras','codigo barras']
    IMG  = ['imagen','image','image_url','urlimagen','foto']
    DESC = ['ficha','descripcion','descripción','description','desc']
    FAM1 = ['titulofamilia','familia']
    FAM2 = ['titulosubfamilia','subfamilia']
    FAM3 = ['tituloseccion','seccion','sección']

    def _c(r, cands): return _col(r, cands)

    items = []
    for row in reader:
        try:
            name = _c(row, NAME)
            if not name:
                continue

            price = _to_float_es(row.get("PRECIO"))
            stock_total = _sum_stock(row)
            if price <= 0 or stock_total < min_stock:
                continue

            sku = _c(row, CODE)
            barcode = _c(row, BAR)
            image_url = _normalize_image_url(_c(row, IMG))
            if not image_url:
                # MANTENER tu filtro: sin imagen => descartar
                continue

            desc_html = _desc_to_html(_c(row, DESC))

            # categoría: usa lo que ya traiga el feed
            category = (_c(row, FAM2) or _c(row, FAM1) or _c(row, FAM3)) or None

            item = {
                "name": name,
                "sku": sku or barcode,
                "cost": float(f"{price:.2f}"),
                "list_price": None,
                "barcode": barcode or None,
                "image_url": image_url,
                "category": category,
                "vendor_code": sku or None,
                "vendor_name": (vendor_name or "Infortisa").strip(),
                "vendor_stock": int(stock_total),
                # === PESO desde columna PESO (kg) ===
                "weight": _peso_from_row(row),
            }
            if desc_html:
                item["description_ecommerce"] = desc_html
                item["website_description"] = desc_html

            items.append(item)
            if lim and len(items) >= lim:
                break
        except Exception:
            continue
    return items

def get_items_mapped(**kwargs):
    return get_items(**kwargs)
