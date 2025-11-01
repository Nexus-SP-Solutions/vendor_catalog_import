# -*- coding: utf-8 -*-
import json, logging, importlib
from odoo import models
_logger = logging.getLogger(__name__)

class VendorCatalogGetStockPatch(models.Model):
    _inherit = 'vendor.catalog.config'

    def _vc__load_kwargs(self):
        try:
            return self.python_kwargs if isinstance(self.python_kwargs, dict) else json.loads(self.python_kwargs or "{}")
        except Exception:
            return {}

    def _vc__quick_import(self):
        for modname in (
            'vendor_catalog_import.myscript.infortisa.quick_stock_api',
            'odoo.addons.vendor_catalog_import.myscript.infortisa.quick_stock_api',
        ):
            try:
                return importlib.import_module(modname).quick_stock_lookup
            except Exception as e:
                last = e
        _logger.warning("No pude importar quick_stock_api: %s", last)
        return None

    def _vc__try_quick_rest(self, code, kwargs):
        name_l = (self.vendor_id.display_name or "").lower()
        mod_l  = (self.python_module or "").lower()
        if "infortisa" not in name_l and "infortisa" not in mod_l:
            return None

        quick = self._vc__quick_import()
        if not quick:
            return None

        # PRIORIDADES:
        # 1) kwargs["app_key"] (Parámetros JSON)
        # 2) self.auth_token
        # 3) helper centralizado (_get_infortisa_app_key) / ICP / ENV
        try:
            app_key = (kwargs.get("app_key") or self.auth_token or self._get_infortisa_app_key()).strip()
        except Exception:
            app_key = (kwargs.get("app_key") or self.auth_token or "").strip()

        # Para REST: usa rest_header si está, si no header_name, si no Authorization-Token
        header_name = (kwargs.get("rest_header") or kwargs.get("header_name") or "Authorization-Token")

        # auth_mode: permitimos lo que venga pero el cliente probará header->bearer->query
        auth_mode = kwargs.get("rest_auth_mode") or kwargs.get("auth_mode") or kwargs.get("mode")

        try:
            res = quick(
                code=code,
                map_by=self.map_by,
                app_key=app_key,
                auth_mode=auth_mode,
                header_name=header_name,
            ) or {}
            if isinstance(res, dict) and "stock" in res:
                stock = max(0, int(res.get("stock") or 0))
                _logger.info("[Infortisa/JSON:Stock] code=%s stock=%s (quick)", code, stock)
                return {"stock": stock}
        except Exception as e:
            _logger.warning("quick_stock_lookup error: %s", e)
        return None

    def _vc__try_python_callable(self, code, kwargs):
        if not (self.feed_format == 'python' and self.python_module and self.python_callable):
            return None
        try:
            mod = importlib.import_module(self.python_module)
            func = getattr(mod, self.python_callable, None)
        except Exception as e:
            _logger.debug("import callable failed: %s", e); func = None
        if not callable(func):
            return None
        kw = dict(kwargs or {})
        kw.update({'filter_code': code, 'map_by': self.map_by, 'min_stock': 0, 'limit': 1})
        try:
            items = func(**kw) or []
            if not isinstance(items, list):
                items = list(items)
        except Exception as e:
            _logger.warning("callable(**kw) error: %s", e)
            items = []
        for it in items:
            cand = (it.get('sku') or it.get('default_code') or '') if self.map_by in ('supplierinfo','default_code') else (it.get('barcode') or '')
            if (cand or '').strip() != code:
                continue
            v = 0
            for k in ("vendor_stock","stock","stock_total","Stock","TotalStock","STOCKCENTRAL","STOCKPALMA","STOCKEXTERNO"):
                try: v += int(float(str(it.get(k)).replace(",", ".")))
                except Exception: pass
            return {"stock": max(0, v)}
        return None

    def get_stock_for_code(self, code):
        self.ensure_one()
        code = (code or '').strip()
        if not code:
            return {'stock': 0}
        kwargs = self._vc__load_kwargs()
        res = self._vc__try_quick_rest(code, kwargs)
        if isinstance(res, dict) and "stock" in res:
            return res
        res = self._vc__try_python_callable(code, kwargs)
        if isinstance(res, dict) and "stock" in res:
            return res
        _logger.info("get_stock_for_code fallback -> 0 (code=%s, vendor=%s)", code, self.vendor_id.display_name or "")
        return {"stock": 0}
