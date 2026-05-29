from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
_logger = logging.getLogger(__name__)


class PickingPackagingLine(models.Model):
    _name = 'picking.packaging.line'
    _description = 'Picking Packaging Line'
    
    picking_id = fields.Many2one(comodel_name='stock.picking', string="Picking", ondelete='cascade')
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    product_uom_desc = fields.Char(string="UoM")
    packaging_code = fields.Char(string="Packaging")
    packaging_desc = fields.Char(string="Packaging Description")
    qty_packaging_sap = fields.Float(string="Qty", compute='_compute_qty_packaging', store=False)
    company_id = fields.Many2one(comodel_name='res.company', string="Company")
    packaging_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Packaging Type")
    sloc_packaging = fields.Char(string="SLOC Packaging")
    sloc_id = fields.Many2one(comodel_name='storage.location', string="SLOC")
    move_type_sap = fields.Char(string="Move Type")
    
    @api.depends('picking_id.move_ids', 'product_id')
    def _compute_qty_packaging(self):
        for line in self:
            if not line.picking_id or not line.product_id:
                line.qty_packaging_sap = 0.0
                continue

            moves = line.picking_id.move_ids.filtered(lambda m: m.product_id.product_tmpl_id == line.product_id)
            line.qty_packaging_sap = sum(moves.mapped('qty_packaging_sap'))