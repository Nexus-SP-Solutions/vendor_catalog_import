# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models

class ProductTemplateWebsiteStockRefresh(models.Model):
    _inherit = 'product.template'

    x_vendor_stock_last_sync = fields.Datetime(
        string='Última sincronización stock proveedor',
        readonly=True
    )

    def _stock_ttl_minutes(self):
        icp = self.env['ir.config_parameter'].sudo()
        try:
            return max(1, int(icp.get_param('vendor_catalog.stock_ttl_minutes', '10')))
        except Exception:
            return 10

    def _web_refresh_disabled(self):
        icp = self.env['ir.config_parameter'].sudo()
        def _flag(v):
            v = str(v or '').strip().lower()
            return v in ('1','true','yes','on')
        return _flag(icp.get_param('vendor_catalog.disable_web_refresh')) or \
               _flag(icp.get_param('vendor_catalog.disable_quick_stock')) or \
               _flag((self.env.context or {}).get('disable_quick_stock'))

    def _vc_pick_config_and_code(self):
        self.ensure_one()
        Config = self.env['vendor.catalog.config'].sudo()
        cfgs = Config.search([('active', '=', True)])
        if not cfgs:
            return None, None, None
        for seller in self.seller_ids:
            cfg = next((c for c in cfgs if c.vendor_id and c.vendor_id.id == seller.partner_id.id), None)
            if not cfg:
                continue
            if cfg.map_by == 'supplierinfo' and seller.product_code:
                return cfg, seller.product_code.strip(), seller
            if cfg.map_by == 'default_code' and self.default_code:
                return cfg, self.default_code.strip(), seller
            if cfg.map_by == 'barcode' and self.barcode:
                return cfg, self.barcode.strip(), seller
        if self.default_code:
            for cfg in cfgs:
                if cfg.map_by == 'default_code':
                    return cfg, self.default_code.strip(), None
        if self.barcode:
            for cfg in cfgs:
                if cfg.map_by == 'barcode':
                    return cfg, self.barcode.strip(), None
        return None, None, None

    def website_refresh_vendor_stock(self):
        """Si está desactivado, NO llama a proveedor y devuelve el valor guardado."""
        self.ensure_one()

        # Gate global para desactivar refresco en ficha
        if self._web_refresh_disabled():
            return int(self.x_vendor_stock or 0)

        force = bool(self.env.context.get('force_refresh'))
        if self.x_vendor_stock_last_sync and not force:
            ttl = self._stock_ttl_minutes()
            if fields.Datetime.now() - self.x_vendor_stock_last_sync < timedelta(minutes=ttl):
                return int(self.x_vendor_stock or 0)

        cfg, code, seller = self._vc_pick_config_and_code()
        if not cfg or not code:
            self.sudo().write({'x_vendor_stock_last_sync': fields.Datetime.now()})
            return int(self.x_vendor_stock or 0)

        stock_val = 0
        try:
            res = cfg.sudo().get_stock_for_code(code) or {}
            stock_val = int(res.get('stock') or 0)
        except Exception:
            stock_val = int(self.x_vendor_stock or 0)

        vals = {
            'x_vendor_stock': max(0, stock_val),
            'x_vendor_name': (cfg.vendor_id and cfg.vendor_id.display_name) or (self.x_vendor_name or False),
            'x_vendor_stock_last_sync': fields.Datetime.now(),
        }
        self.sudo().write(vals)
        if seller:
            seller.sudo().write({'x_vendor_stock_info': max(0, stock_val)})

        return int(self.x_vendor_stock or 0)
