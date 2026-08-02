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
    check_warehouse = fields.Boolean(string='Check warehouse',compute='check_warehouse_update',store=True)
    check_location = fields.Boolean(string='Check location',compute='check_location_update',store=True)
    check_operation = fields.Boolean(string='Check operation',compute='check_operation_update',store=True)
    
    # @api.onchange('allowed_warehouse_ids')
    # def change_location_on_change_warehouse(self):
        # if not self.allowed_warehouse_ids:
        #     self.allowed_location_ids = False
        #     self.allowed_operation_types = False
        #     return
        # warehouse_ids = self.allowed_warehouse_ids.ids
        # view_locations = self.env['stock.location'].search([
        #     ('warehouse_id', 'in', warehouse_ids),
        #     ('usage', '=', 'view')
        # ]).ids


        # additional_locations = self.allowed_location_ids.filtered(
        #     lambda loc: not loc.warehouse_id or loc.warehouse_id.id in warehouse_ids
        # ).ids

        # filtered_operation = []
        # for i in self.allowed_operation_types:
        #     if i.warehouse_id.id in self.allowed_warehouse_ids.ids:
        #         filtered_operation.append(i.id)

        # filtered_locations = list(set(view_locations + additional_locations))
        # self.allowed_location_ids = [(6, 0, filtered_locations)]
        # self.allowed_operation_types = [(6,0,filtered_operation)]

    @api.depends('allowed_warehouse_ids')
    def check_warehouse_update(self):
        for rec in self:
            if len(rec.allowed_warehouse_ids.ids) == 0:
                rec.check_warehouse = False
            else:
                rec.check_warehouse = True

    @api.depends('allowed_location_ids')
    def check_location_update(self):
        for rec in self:
            if len(rec.allowed_location_ids.ids) == 0:
                rec.check_location = False
            else:
                rec.check_location = True

    @api.depends('allowed_operation_types')
    def check_operation_update(self):
        for rec in self:
            if len(rec.allowed_operation_types.ids) == 0:
                rec.check_operation = False
            else:
                rec.check_operation = True

    def write(self, values):
        res = super(ResUsers, self).write(values)

        # Skip check for admin users
        if self.env.user.has_group('base.group_system'):
            self.env.cache.clear()
            return res

        # Ensure all locations belong to allowed warehouses
        for location in self.allowed_location_ids:
            if location.warehouse_id and location.warehouse_id not in self.allowed_warehouse_ids:
                raise UserError(
                    f"You need warehouse access to view/manage stock in location '{location.name}'"
                )
        self.env.cache.clear()
        self.env.invalidate_all()
        return res
    
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