# -*- coding: utf-8 -*-
import csv, io, os, unicodedata, re, logging
from odoo import models, fields
_logger = logging.getLogger(__name__)

# ---------- Utilidades CSV/mapeo (compatibles con tu infortisa_catalog) ----------
def _norm_key(s: str) -> str:
    if s is None: return ""
    t = str(s).replace("\u00a0"," ").replace("\u2007"," ").replace("\u202f"," ")
    nfkd = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()
    t = t.replace("&", " y ").replace("/", " / ")
    return re.sub(r"\s+", " ", "".join(ch for ch in t if ord(ch) < 128 or ch.isspace())).strip()

def _csv_reader(text: str) -> csv.DictReader:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
    except Exception:
        class _D: delimiter = ';'
        dialect = _D()
    return csv.DictReader(io.StringIO(text), dialect=dialect)

def _read_file(path: str) -> str:
    last = None
    for enc in ("utf-8","utf-8-sig","cp1252","latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except Exception as e:
            last = e
    raise last

def _pick_headers(fieldnames_low: dict):
    # Columnas “origen” y “destino” muy tolerantes (mismas que usamos en infortisa_catalog)
    src_cands = [
        "categoría infortisa","categoria infortisa","infortisa",
        "categoría de producto","categoria de producto",
        "categoría","categoria","origen"
    ]
    dst_cands = [
        "categoría final","categoria final","final","destino",
        "mi categoría","mi categoria"
    ]
    src = next((fieldnames_low.get(k) for k in src_cands if fieldnames_low.get(k)), None)
    dst = next((fieldnames_low.get(k) for k in dst_cands if fieldnames_low.get(k)), None)
    if not src and dst:
        for orig in fieldnames_low.values():
            if orig and orig != dst:
                src = orig; break
    return src, dst

def _load_cat_map(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    txt = _read_file(path)
    rdr = _csv_reader(txt)
    fl = {(c or "").strip().lower(): c for c in (rdr.fieldnames or [])}
    src, dst = _pick_headers(fl)
    if not (src and dst):
        return {}
    mapping = {}
    for row in rdr:
        s = (row.get(src) or "").strip()
        d = (row.get(dst) or "").strip()
        if s:
            mapping[_norm_key(s)] = d or s
    return mapping

def _find_map(mapping: dict, src_text: str):
    if not mapping:
        return None
    key = _norm_key(src_text)
    if key in mapping:
        return mapping[key]
    # prefijo/sufijo/fuzzy suave
    for k in mapping.keys():
        if key.startswith(k) or key.endswith(k) or k.startswith(key):
            return mapping[k]
    try:
        # minifuzzy: coincidencia por “bloques” principales
        parts = [p for p in re.split(r"[ >/]", key) if p]
        for k in mapping.keys():
            if all(p in k for p in parts[:2]):  # dos primeras palabras
                return mapping[k]
    except Exception:
        pass
    return None

# ---------- Split de rutas tipo "A / B" o "A > B" (ignorando paréntesis) ----------
def _smart_split_path(text):
    s = str(text or '')
    parts, buf, depth = [], [], 0
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '(': depth += 1
        elif ch == ')' and depth > 0: depth -= 1
        if depth == 0 and i+2 < n and s[i]==' ' and s[i+1] in '/>' and s[i+2]==' ':
            seg = ''.join(buf).strip()
            if seg: parts.append(seg)
            buf = []; i += 3; continue
        buf.append(ch); i += 1
    last = ''.join(buf).strip()
    if last: parts.append(last)
    return parts or [s.strip()]

# ---------- Helpers de creación/búsqueda de categorías ----------
def _get_or_create_internal_category(env, path: str):
    Cat = env["product.category"].sudo()
    parent = None
    for name in _smart_split_path(path):
        dom = [("name","=",name),("parent_id","=",parent.id if parent else False)]
        cat = Cat.search(dom, limit=1)
        if not cat:
            cat = Cat.create({"name": name, "parent_id": parent.id if parent else False})
        parent = cat
    return parent

def _get_or_create_public_category(env, path: str, website):
    Public = env["product.public.category"].sudo()
    parent = None
    for name in _smart_split_path(path):
        dom = [("name","=",name),("parent_id","=",parent.id if parent else False)]
        if "website_id" in Public._fields and website:
            dom.append(("website_id","=",website.id))
        cat = Public.search(dom, limit=1)
        if not cat:
            vals = {"name": name, "parent_id": parent.id if parent else False}
            if "website_id" in Public._fields and website:
                vals["website_id"] = website.id
            cat = Public.create(vals)
        parent = cat
    return parent

# ---------- Acción principal ----------
class VendorCatalogRemapCategories(models.Model):
    _inherit = "vendor.catalog.config"

    def action_remap_categories_from_csv(self, path=None, apply_internal=True, apply_public=True,
                                         batch_commit=200, dry_run=False, limit=None):
        """
        Reasigna categorías de productos usando el CSV de mapeo.
        - path: ruta al CSV (si no se pasa, usa _get_category_map_path()).
        - apply_internal: actualiza product.category (categ_id).
        - apply_public:   actualiza product.public.category (public_categ_ids) a una ruta única.
        - batch_commit: commits periódicos.
        - dry_run: no escribe, solo cuenta.
        - limit: máximo de productos a procesar.
        Solo toca productos vinculados al partner de esta configuración (seller_ids.partner_id = vendor_id).
        """
        self.ensure_one()
        env = self.env

        # Cargar mapeo
        if not path:
            try:
                path = self._get_category_map_path()
            except Exception:
                path = ""
        mapping = _load_cat_map(path)
        if not mapping:
            raise ValueError("No se pudo cargar el CSV de mapeo de categorías: %s" % (path or "(no especificado)"))

        # Selección de productos: por proveedor de esta configuración
        Product = env["product.template"].sudo()
        dom = []
        if self.vendor_id:
            dom = [("seller_ids.partner_id","=", self.vendor_id.id)]
        ids = Product.search(dom).ids
        if not ids:
            _logger.info("Remap categorías: 0 productos para vendor=%s", self.vendor_id.display_name if self.vendor_id else "N/D")
            return

        # Iteración controlada
        total = len(ids) if not limit else min(limit, len(ids))
        upd_int = upd_pub = skipped = 0
        website = self.website_id if hasattr(self, "website_id") else False

        for i, pid in enumerate(ids[:total], start=1):
            pt = Product.browse(pid)

            # Texto “origen” desde donde deducimos el mapeo (prioridad simple)
            src_txt = (pt.categ_id and pt.categ_id.display_name) or ""
            if not src_txt and getattr(pt, "public_categ_ids", False):
                src_txt = ", ".join(pt.public_categ_ids.mapped("name")) or ""

            dst = _find_map(mapping, src_txt)
            if not dst:
                skipped += 1
                continue

            # Aplicar internas
            if apply_internal:
                new_cat = _get_or_create_internal_category(env, dst)
                if new_cat and (not pt.categ_id or pt.categ_id.id != new_cat.id):
                    if not dry_run:
                        pt.write({"categ_id": new_cat.id})
                    upd_int += 1

            # Aplicar públicas (una sola ruta destino)
            if apply_public and "public_categ_ids" in Product._fields:
                new_pub = _get_or_create_public_category(env, dst, website)
                if new_pub:
                    if not dry_run:
                        pt.public_categ_ids = [(6, 0, [new_pub.id])]
                    upd_pub += 1

            # Commit por lotes para no bloquear
            if batch_commit and (i % int(batch_commit) == 0):
                env.cr.commit()

        msg = (f"Remap categorías desde CSV\n"
               f"Total procesados: {total} | "
               f"Internas actualizadas: {upd_int} | "
               f"eCommerce actualizadas: {upd_pub} | "
               f"Sin mapeo: {skipped}")
        _logger.info(msg)
        self.sudo().write({"last_run": fields.Datetime.now(), "last_result": msg})
        return msg
