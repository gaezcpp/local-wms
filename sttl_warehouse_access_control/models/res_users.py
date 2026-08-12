# -*- coding: utf-8 -*-
from email.policy import default

from odoo import models, fields,api
# from odoo.addons.base.models.ir_actions_report import process
from odoo.exceptions import UserError


# inherited res.users model to extend it and add allowed_location_ids field.
class ResUsers(models.Model):
    _inherit = 'res.users'
    allowed_warehouse_ids = fields.Many2many('stock.warehouse', string='Available Warehouses')
    allowed_location_ids = fields.Many2many('stock.location', string='Available Locations', domain="['|',('warehouse_id','in',allowed_warehouse_ids),('warehouse_id','=',False)]")
    allowed_operation_types = fields.Many2many('stock.picking.type',string='Operation Types',domain="[('warehouse_id','in',allowed_warehouse_ids)]")
    check_warehouse = fields.Boolean(string='Check warehouse', compute='_compute_check_warehouse', store=True)
    check_location = fields.Boolean(string='Check location', compute='_compute_check_location', store=True)
    check_operation = fields.Boolean(string='Check operation', compute='_compute_check_operation', store=True)

    @api.depends('allowed_warehouse_ids')
    def _compute_check_warehouse(self):
        for rec in self:
            rec.check_warehouse = bool(rec.allowed_warehouse_ids)

    @api.depends('allowed_location_ids')
    def _compute_check_location(self):
        for rec in self:
            rec.check_location = bool(rec.allowed_location_ids)

    @api.depends('allowed_operation_types')
    def _compute_check_operation(self):
        for rec in self:
            rec.check_operation = bool(rec.allowed_operation_types)

    @api.onchange('allowed_operation_types')
    def onchange_fill_location_by_types(self):
        if not self.allowed_operation_types:
            self.allowed_location_ids = [(5, 0, 0)]
            return
        
        warehouse_ids = self.allowed_warehouse_ids.ids
        view_locations = self.env['stock.location'].sudo().search([
            ('warehouse_id', 'in', warehouse_ids),
            ('usage', '=', 'view')
        ]).ids

        operation_location_ids = []
        for op in self.allowed_operation_types:
            if op.default_location_src_id:
                operation_location_ids.append(op.default_location_src_id.id)
            if op.default_location_dest_id:
                operation_location_ids.append(op.default_location_dest_id.id)

        final_location_ids = list(set(view_locations + operation_location_ids))
        self.allowed_location_ids = [(6, 0, final_location_ids)]