# -*- coding: utf-8 -*-
import os, requests

BASE = "https://apiv2.infortisa.com"

def _to_int(x):
    try:
        return int(float(str(x).replace(",", ".").strip()))
    except Exception:
        return 0

def _flatten(d):
    if isinstance(d, dict) and isinstance(d.get("Product"), dict):
        return d["Product"]
    return d

def _extract_stock(payload):
    """
    **CENTRAL ONLY**
    - Devuelve 'Stock' (central) si existe.
    - Si no existe, intenta 'StockCentral' / 'stock_central'.
    - En cualquier otro caso, 0 (no suma Palma/Externo/TotalStock).
    """
    if not isinstance(payload, dict):
        return 0
    obj = _flatten(payload)
    low = {str(k).lower(): v for k, v in (obj or {}).items()}

    # 1) 'stock' (Infortisa lo usa como central en la ficha)
    if "stock" in low:
        return max(0, _to_int(low["stock"]))

    # 2) alias explícitos de central
    for k in ("stockcentral", "stock_central", "stock central"):
        if k in low:
            return max(0, _to_int(low[k]))

    # 3) sin central -> 0 (no queremos totales ni otras sedes)
    return 0

def _api_get_json(path, params, app_key=None, auth_mode=None, header_name=None):
    url = f"{BASE}{path}"
    key = (app_key or os.getenv("INFORTISA_APP_KEY") or "").strip()
    header_name = header_name or "Authorization-Token"
    headers = {"Accept": "application/json"}

    # Intentar: modo indicado -> header -> bearer -> query
    modes = [m for m in (auth_mode, "header", "bearer", "query") if m]
    for mode in modes:
        h = dict(headers); q = dict(params or {})
        if mode in ("header", "token"):
            if key: h[header_name] = key
        elif mode == "bearer":
            if key: h["Authorization"] = f"Bearer {key}"
        elif mode == "query":
            if key: q["user"] = key
        r = requests.get(url, params=q, headers=h, timeout=20)
        if not r.ok:
            continue
        try:
            return r.json()
        except Exception:
            continue
    return None

def quick_stock_lookup(code, map_by="supplierinfo", app_key=None, auth_mode=None, header_name=None):
    code = (code or "").strip()
    if not code:
        return {"stock": 0}

    # SKU/Partnumber: probamos ambos, pero **no** sumamos; cogemos el primero que devuelva central
    order = [
        ("/api/Product/GetProductBySku",        {"Sku": code}),
        ("/api/Product/GetProductByPartnumber", {"partnumber": code}),
    ]
    if map_by not in ("supplierinfo", "default_code"):
        order.reverse()

    for path, params in order:
        data = _api_get_json(path, params, app_key=app_key, auth_mode=auth_mode, header_name=header_name)
        if not data:
            continue
        return {"stock": _extract_stock(data)}
    return {"stock": 0}
