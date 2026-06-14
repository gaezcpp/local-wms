from odoo import models, fields, api


class InheritStockPickingType(models.Model):
    _inherit = 'stock.picking.type'
    
    uu_only = fields.Boolean(string="UU Only", default=False)
    production_only = fields.Boolean(string="Production Only", default=False)
    move_type_sap = fields.Char(string="Move Type SAP")
    packaging_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Packaging Type")
    checker_only = fields.Boolean(string="Checker In", default=False)
    checker_type_id = fields.Many2one(comodel_name='stock.picking.type')
    quality_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Quality Type")
    quantity_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Quantity Type")
    checker_out = fields.Boolean(string="Checker Out", default=False)
    book_full_pallet = fields.Boolean(string="Book Full Pallet", default=False)
    quality_out_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Quality Type")
    quantity_out_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Quantity Type")
    mandatory_destination = fields.Boolean(string="Mandatory Destination", default=False)
    
    @api.onchange('checker_only')
    def _onchange_checker_only(self):
        for rec in self:
            if not rec.checker_only:
                rec.quality_type_id = False
                rec.quantity_type_id = False
                
    @api.onchange('checker_out')
    def _onchange_checker_out(self):
        for rec in self:
            if not rec.checker_out:
                rec.quality_out_type_id = False
                rec.quantity_out_type_id = False