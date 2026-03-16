from odoo import models


class ProductProduct(models.Model):
    _inherit = "product.product"

    def name_get(self):
        if self.env.context.get("display_name_only"):
            return [(p.id, p.name or "") for p in self]
        return super().name_get()
