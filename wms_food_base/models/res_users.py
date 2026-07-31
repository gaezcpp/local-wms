from odoo import fields, models


class FoodResUsers(models.Model):
    _inherit = 'res.users'

    # Related, non-stored: lets the views below decide per-record whether to
    # show the FEED-customized arch or the plain Odoo one. Related through the
    # user's own default company_id, same as res.company.wms_type everywhere
    # else -- res.users has no more specific "acting warehouse" company.
    wms_type = fields.Selection(related='company_id.wms_type', string="WMS Type", store=True, index=True)
