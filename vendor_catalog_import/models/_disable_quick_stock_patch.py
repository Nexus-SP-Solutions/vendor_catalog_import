# -*- coding: utf-8 -*-
from odoo import models

class VendorCatalogDisableQuickStock(models.Model):
    _inherit = 'vendor.catalog.config'

    def _vc__try_quick_rest(self, code, kwargs):
        """
        Cortacircuito para desactivar por completo las consultas JSON de stock.
        Se activa si:
          - context['disable_quick_stock'] es true/1
          - ICP 'vendor_catalog.disable_quick_stock' es true/1
          - ICP 'vendor_catalog.only_csv_import' es true/1 (alias)
          - ICP 'vendor_catalog.disable_web_refresh' es true/1 (para web)
        """
        try:
            ICP = self.env['ir.config_parameter'].sudo()
            def _on(v): 
                v = str(v or '').strip().lower()
                return v in ('1','true','yes','on')
            disabled = _on(self.env.context.get('disable_quick_stock')) \
                or _on(ICP.get_param('vendor_catalog.disable_quick_stock')) \
                or _on(ICP.get_param('vendor_catalog.only_csv_import')) \
                or _on(ICP.get_param('vendor_catalog.disable_web_refresh'))
        except Exception:
            disabled = False

        if disabled:
            # No llamamos a la API; dejamos que otros caminos (p.ej. CSV) gestionen el stock
            return None

        # Si no está deshabilitado, usar la implementación original
        return super()._vc__try_quick_rest(code, kwargs)
