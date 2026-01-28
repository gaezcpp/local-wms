from odoo import models, fields, api
from odoo.exceptions import ValidationError


class UnpackStockPackage(models.TransientModel):
    _name = 'unpack.stock.package.wizard'
    _description = 'Unpack by Quantity'
    
    stock_package_id = fields.Many2one(comodel_name='stock.package')
    line_ids = fields.One2many('unpack.stock.package.line', 'unpack_stock_id')
    location_dest_id = fields.Many2one(comodel_name='stock.location')
    
    def action_unpack_qty(self):
        if not self.stock_package_id:
            raise ValidationError("ID Packages tidak ditemukan")
        
        lines = self.line_ids.filtered(lambda l: l.qty_unpack > 0)
        if not lines:
            raise ValidationError("Tidak ada quantity yang di-unpack")
        
        if not self.location_dest_id:
            raise ValidationError("Destination Location harus diisi!")

        self.stock_package_id.unpack_by_lines(lines=lines, location=self.location_dest_id)
        
        
class UnpackStockPackageLine(models.TransientModel):
    _name = 'unpack.stock.package.line'
    _description = 'Unpack Stock Package Line'

    unpack_stock_id = fields.Many2one('unpack.stock.package.wizard', ondelete='cascade')
    quant_id = fields.Many2one('stock.quant', required=True, readonly=True)
    product_id = fields.Many2one(related='quant_id.product_id', readonly=True)
    lot_id = fields.Many2one(related='quant_id.lot_id', readonly=True)
    package_id = fields.Many2one(related='quant_id.package_id', readonly=True)
    location_id = fields.Many2one(related='quant_id.location_id', readonly=True)
    qty_available = fields.Float(related='quant_id.quantity', readonly=True, string="Qty Available")
    product_uom_id = fields.Many2one(related='quant_id.product_uom_id')
    
    qty_unpack = fields.Float(string="Qty to Unpack", default=0.0)