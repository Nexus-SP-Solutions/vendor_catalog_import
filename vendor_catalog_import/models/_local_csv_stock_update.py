# -*- coding: utf-8 -*-
import os, csv, io, re, logging
from odoo import models, fields
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)

def _read_file_anyenc(path):
    last = None
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc, errors="ignore") as f:
                return f.read()
        except Exception as e:
            last = e
    raise last

# CSV robusto para Infortisa (protege &xxxx; para no romper por ';')
def _csv_reader_infortisa(text):
    if not isinstance(text, str):
        text = str(text or "")
    safe = re.sub(r'&([A-Za-z0-9#]{1,20});', r'§E:\1§', text)
    rdr = csv.DictReader(io.StringIO(safe), delimiter=';')
    def _restore(row):
        out = {}
        for k, v in (row or {}).items():
            if isinstance(v, str):
                v = re.sub(r'§E:([A-Za-z0-9#]{1,20})§', r'&\1;', v)
            out[k] = v
        return out
    class _Iter:
        def __iter__(self_inner):
            for r in rdr:
                yield _restore(r)
    return _Iter()

def _norm_key(s):
    s = (s or "").strip().lower()
    s = s.replace("\u00a0"," ")
    s = re.sub(r"\s+", " ", s)
    return s

def _col(row, candidates):
    keys = {_norm_key(k): k for k in row.keys()}
    for c in candidates:
        k = keys.get(_norm_key(c))
        if k is not None:
            v = row.get(k)
            if v not in (None, "", "null", "None"):
                return str(v).strip()
    return ""

def _toi(x):
    try:
        return int(round(float(str(x).replace(",", ".").strip())))
    except Exception:
        return 0

def _sum_stock(row):
    total = 0
    for k in ("STOCKCENTRAL","STOCK PALMA","STOCKPALMA","STOCKEXTERNO","STOCK EXTERNO",
              "STOCK","STOCKWEB","UNIDADES","DISPONIBLE","DISPONIBLES","TotalStock"):
        total += _toi(row.get(k))
    if total:
        return total
    for k, v in (row or {}).items():
        nk = _norm_key(k)
        if "stock" in nk or "dispon" in nk:
            total += _toi(v)
    return total

class VendorCatalogLocalCSVStock(models.Model):
    _inherit = 'vendor.catalog.config'

    def action_update_stock_from_local_csv(self, path=None, min_stock=0):
        """Actualiza x_vendor_stock/x_vendor_stock_info leyendo un CSV local."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if not path:
            path = self.env.context.get('stock_csv_path') or ICP.get_param('vendor_catalog.local_stock_csv_path')
        if not path:
            raise UserError("Falta ruta del CSV. Pásala como argumento 'path' o define 'vendor_catalog.local_stock_csv_path'.")

        if not os.path.exists(path):
            raise UserError("No existe el archivo CSV: %s" % path)

        txt = _read_file_anyenc(path)
        reader = _csv_reader_infortisa(txt)

        CODE = ['codigointerno','codigo','código','sku','ref','referencia','productcode','itemcode']
        BAR  = ['ean/upc','ean','barcode','código barras','codigo barras']

        ProductT = self.env['product.template'].sudo()
        SupplierInfo = self.env['product.supplierinfo'].sudo()

        total = updated = missing = 0
        for row in reader:
            total += 1
            sku = _col(row, CODE)
            barcode = _col(row, BAR)
            stock = _sum_stock(row)
            if stock < (int(min_stock or 0)):
                stock = 0

            # Reutiliza tu propio buscador de plantilla
            tmpl = self._find_template(sku, barcode)
            if not tmpl:
                missing += 1
                continue

            vals = {
                'x_vendor_stock': max(0, int(stock)),
                'x_vendor_name': (self.vendor_id and self.vendor_id.display_name) or (tmpl.x_vendor_name or False),
            }
            tmpl.write(vals)

            if self.vendor_id and sku:
                si = SupplierInfo.search([('partner_id','=',self.vendor_id.id),
                                          ('product_tmpl_id','=',tmpl.id)], limit=1)
                if si:
                    si.write({'x_vendor_stock_info': max(0, int(stock))})

            updated += 1

            if (self.env.context or {}).get('progress_every') in (1, '1'):
                _logger.info("[CSV-STOCK] %s -> %s", sku or barcode or "N/A", stock)

            # commits por lote grandes no necesarios aquí; es una pasada rápida de campos

        msg = "Stock CSV: filas=%s | actualizados=%s | sin_plantilla=%s" % (total, updated, missing)
        now = fields.Datetime.now()
        try:
            self.sudo().write({'last_run': now, 'last_result': msg})
        except Exception:
            pass

        _logger.info(msg)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": "Stock desde CSV", "message": msg, "type": "success", "sticky": False},
        }
