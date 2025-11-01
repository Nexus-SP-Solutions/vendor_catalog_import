# -*- coding: utf-8 -*-
from odoo import models, fields

class VendorCatalogConfigStatsPatch(models.Model):
    _inherit = 'vendor.catalog.config'

    last_no_extra_images = fields.Integer(
        string='Sin imagen extra',
        compute='_compute_last_no_extra_images',
        readonly=True,
    )

    def _compute_last_no_extra_images(self):
        Log = self.env['vendor.catalog.log'].sudo()
        for rec in self:
            val = 0
            try:
                log = Log.search([('config_id', '=', rec.id)],
                                 order='run_date desc, id desc', limit=1)
                if log and hasattr(log, 'no_extra_images'):
                    val = int(log.no_extra_images or 0)
            except Exception:
                val = 0
            rec.last_no_extra_images = val
