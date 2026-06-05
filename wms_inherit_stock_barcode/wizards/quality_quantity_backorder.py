from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class QualityQuantityBackorder(models.TransientModel):
    _name = 'quality.quantity.backorder'
    _description = 'Quality Quantity Backorder'
    
    picking_id = fields.Many2one(comodel_name='stock.picking', string="Pick")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string="Operation Type")
    result_package_id = fields.Many2one(comodel_name='stock.package', string="Destination Package")
    is_quality = fields.Boolean(string="Is Quality", default=False)
    line_ids = fields.One2many(comodel_name='quality.quantity.backorder.line',inverse_name='backorder_wizard_id', string="Products")
    
    def action_create_backorder_from_qq(self):
        self.ensure_one()
        
        if not self.picking_type_id:
            raise UserError(_("Operation Type wajib diisi!"))
        if not self.line_ids:
            raise UserError(_("Tambahkan setidaknya satu produk!"))

        # 1. Buat Picking Baru
        new_picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type_id.id,
            'location_id': self.line_ids[0].location_id.id, # Ambil dari baris pertama
            'location_dest_id': self.picking_type_id.default_location_dest_id.id,
            'company_id': self.company_id.id,
            'origin': self.picking_id.name if self.picking_id else "Manual Backorder",
            'backorder_id': self.picking_id.id if self.picking_id else False,
        })
        
        # 2. Proses Move dan Move Lines
        for line in self.line_ids:
            # Hitung base quantity jika menggunakan unit yang berbeda
            base_qty = line.product_uom_id._compute_quantity(line.qty, line.product_id.uom_id)
            
            # Buat Stock Move
            move = self.env['stock.move'].create({
                'product_id': line.product_id.id,
                'product_uom_qty': base_qty,
                'product_uom': line.product_id.uom_id.id,
                'location_id': line.location_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'picking_id': new_picking.id,
                'company_id': self.company_id.id,
            })
            
            # Konfirmasi move untuk generate structure
            move._action_confirm()
            
            # 3. Buat/Update Move Line (Ini kunci agar tidak 'Not Available')
            # Hapus line dummy yang mungkin terbuat otomatis
            move.move_line_ids.unlink()
            
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': new_picking.id,
                'product_id': line.product_id.id,
                'product_uom_id': line.product_uom_id.id,
                'quantity': line.qty,
                'location_id': line.location_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'lot_id': line.lot_id.id if hasattr(line, 'lot_id') else False,
                'package_id': line.package_id.id if line.package_id else False, 
                'result_package_id': line.result_package_id.id if line.result_package_id else False,
                'production_line_id': line.production_line_id.id,
                'stock_type': 'QI',
            })

        # 4. Finalisasi Status
        new_picking.action_assign()
        new_picking.button_validate()
        
        return {
            'name': 'New Quality/Quantity Backorder',
            'view_mode': 'form',
            'res_model': 'stock.picking',
            'res_id': new_picking.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
        }
        
class QualityQuantityBackorderLine(models.TransientModel):
    _name = 'quality.quantity.backorder.line'
    _description = 'Quality Quantity Backorder Line'

    backorder_wizard_id = fields.Many2one(comodel_name='quality.quantity.backorder', string="Wizard Reference", required=True, ondelete='cascade')
    product_id = fields.Many2one(comodel_name='product.product', string="Product", required=True)
    qty = fields.Float(string="Quantity")
    product_uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    result_package_id = fields.Many2one(comodel_name='stock.package', string="Destination Package")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot/Serial Number")
    location_id = fields.Many2one(comodel_name='stock.location', string="Source Location")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    production_line_id = fields.Many2one(comodel_name='production.line', string="Production Line")