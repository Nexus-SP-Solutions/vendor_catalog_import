# -*- coding: utf-8 -*-
import base64
from odoo import models
from .vendor_catalog import _download_first_ok  # ya existe en tu módulo

class ProductTemplateGallerySafe(models.Model):
    _inherit = 'product.template'

    def vc_apply_gallery_urls(self, urls, replace=False):
        Image = self.env['product.image'].sudo()
        web_ids = self.env['website'].sudo().search([]).ids
        for tmpl in self:
            dom_all = [('product_tmpl_id', '=', tmpl.id)]
            # 1) Si piden reemplazar: borra vendor-images y cualquier imagen sin binario
            if replace:
                dom_vendor = list(dom_all)
                if 'x_vendor_image' in Image._fields:
                    dom_vendor.append(('x_vendor_image', '=', True))
                Image.search(dom_vendor).unlink()
            Image.search(dom_all + [('image_1920', '=', False)]).unlink()

            # 2) Secuencia base
            seq = max(Image.search(dom_all).mapped('sequence') or [0]) + 10

            # 3) Descargar y crear SOLO si hay binario
            created = 0
            for i, u in enumerate(urls or [], start=1):
                content = _download_first_ok(u)
                if not content:
                    continue
                vals = {
                    'product_tmpl_id': tmpl.id,
                    'image_1920': base64.b64encode(content),
                    'sequence': seq + i,
                    'name': tmpl.name or 'Image',
                }
                if 'is_published' in Image._fields:
                    vals['is_published'] = True
                if web_ids and 'website_ids' in Image._fields:
                    vals['website_ids'] = [(6, 0, web_ids)]
                if 'x_vendor_image' in Image._fields:
                    vals['x_vendor_image'] = True
                if 'x_vendor_image_url' in Image._fields:
                    vals['x_vendor_image_url'] = u
                Image.create(vals); created += 1
        return True
