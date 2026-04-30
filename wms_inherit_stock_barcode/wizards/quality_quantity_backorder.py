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
        
        # 1. Validasi Pengecekan Input
        if not self.picking_type_id:
            raise UserError(_("Operation Type wajib diisi untuk membuat proses picking baru!"))
            
        if not self.line_ids:
            raise UserError(_("Anda harus menambahkan setidaknya satu produk untuk diproses!"))
            
        # 2. Persiapan data untuk stock.picking baru
        loc_src = self.picking_type_id.default_location_src_id.id or (self.picking_id.location_id.id if self.picking_id else False)
        loc_dest = self.picking_type_id.default_location_dest_id.id or (self.picking_id.location_dest_id.id if self.picking_id else False)
        
        new_picking_vals = {
            'picking_type_id': self.picking_type_id.id,
            'location_id': loc_src,
            'location_dest_id': loc_dest,
            'company_id': self.company_id.id,
            'origin': self.picking_id.origin or self.picking_id.name if self.picking_id else "Manual Backorder",
            'backorder_id': self.picking_id.id if self.picking_id else False,
        }
        
        # 3. Membuat record stock.picking
        new_picking = self.env['stock.picking'].create(new_picking_vals)
        
        # 4. Membuat baris produk (stock.move) berdasarkan inputan di wizard
        move_vals_list = []
        for line in self.line_ids:
            if line.qty <= 0:
                raise UserError(_(f"Kuantitas untuk produk {line.product_id.display_name} harus lebih besar dari 0!"))
                
            uom_bag = line.product_uom_id
            product_uom = line.product_id.uom_id # Target UOM (misal: Kg)
            
            # --- KONVERSI NATIVE ODOO (BEST PRACTICE) ---
            # Mengubah input Bag (misal 5) menjadi Kg (misal 40) secara presisi
            base_qty = uom_bag._compute_quantity(line.qty, product_uom)
            
            if self.picking_id:
                original_moves = self.picking_id.move_ids.filtered(lambda m: m.product_id == line.product_id)
                original_demand = sum(original_moves.mapped('product_uom_qty'))
                
                if round(base_qty, 4) > round(original_demand, 4):
                    max_bag = product_uom._compute_quantity(original_demand, uom_bag)
                    raise UserError(_(
                        f"Produk {line.product_id.display_name} melebihi Demand awal!\n"
                        f"Input Anda: {line.qty} {uom_bag.name}\n"
                        f"Maksimal Demand: {max_bag} {uom_bag.name}"
                    ))
                
            move_vals_list.append({
                'description_picking': line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': base_qty,        # Menggunakan base qty (misal 40 Kg)
                'product_uom': product_uom.id,      # Menggunakan UOM standar (Kg)
                'location_id': new_picking.location_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'picking_id': new_picking.id,
                'company_id': new_picking.company_id.id,
            })
            
        if move_vals_list:
            self.env['stock.move'].create(move_vals_list)
            
        # 5. Mengonfirmasi picking baru (generate stock.move.line)
        new_picking.action_confirm()
        
        # 6. Assign Destination Package dan Auto-fill qty_done dari Line
        for move in new_picking.move_ids:
            # Cari baris (line) di wizard yang sesuai
            wizard_line = self.line_ids.filtered(lambda l: l.product_id == move.product_id)[:1]
            
            if wizard_line:
                for move_line in move.move_line_ids:
                    move_line.quantity = move_line.quantity_product_uom or move.product_uom_qty
                    move_line.result_package_id = wizard_line.result_package_id.id

        # 7. Mengarahkan antarmuka (UI) ke form stock.picking yang baru saja dibuat
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