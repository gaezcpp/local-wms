from odoo import fields, models


class InheritedStockPicking(models.Model):
    _inherit = "stock.picking.type"

    bool_picking_type = fields.Boolean(string='Picking Flag', default=False)
    is_allowed_operation_type = fields.Boolean(
        string='Allowed Operation Type',
        compute='_compute_is_allowed_operation_type',
        search='_search_is_allowed_operation_type',
    )

    def _compute_is_allowed_operation_type(self):
        allowed_ids = set(self.env.user.allowed_operation_types.ids)
        for rec in self:
            rec.is_allowed_operation_type = rec.id in allowed_ids

    def _search_is_allowed_operation_type(self, operator, value):
        if self.env.user.has_group(
                'sttl_warehouse_access_control.group_warehouse_manager'):
            return []
        allowed_ids = self.env.user.allowed_operation_types.ids
        if operator in ('in', 'not in'):
            wants_true = True in value
        else:
            wants_true = bool(value)
        if operator in ('!=', '<>', 'not in'):
            wants_true = not wants_true
        if wants_true:
            return [('id', 'in', allowed_ids)]
        return [('id', 'not in', allowed_ids)]
