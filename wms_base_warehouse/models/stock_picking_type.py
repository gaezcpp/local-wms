from odoo import models, fields, api


class InheritStockPickingType(models.Model):
    _inherit = 'stock.picking.type'
    
    uu_only = fields.Boolean(string="UU Only", default=False)
    production_only = fields.Boolean(string="Production Only", default=False)
    move_type_sap = fields.Char(string="Move Type SAP")
    packaging_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Packaging Type")
    checker_only = fields.Boolean(string="Checker In", default=False)
    quality_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Quality Type")
    quantity_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Quantity Type")
    checker_out = fields.Boolean(string="Checker Out", default=False)
    book_full_pallet = fields.Boolean(string="Book Full Pallet", default=False)
    quality_out_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Quality Type")
    quantity_out_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Quantity Type")
    mandatory_destination = fields.Boolean(string="Mandatory Destination", default=False)
    split_package = fields.Boolean(string="Split Package", default=False)
    bypass_entire_packs = fields.Boolean(string="Bypass Entire Packs", default=False)
    create_new_picking = fields.Boolean(string="Create Picking", default=False)
    autofill_pack_qty = fields.Boolean(string="Autofill Pack", default=False)
    restrict_over_demand = fields.Boolean(string="Restrict Over Demand", default=False)
    hide_zero_qty = fields.Boolean(string="Hide Zero Qty", default=False)
    hide_edit_barcode = fields.Boolean(string="Hide Edit Barcode", default=False)
    check_scan_pallet = fields.Boolean(string="Check Scan Pallet", default=False)
    bulk_pallet_lot = fields.Boolean(string="Bulk Pallet Lot", default=False)

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