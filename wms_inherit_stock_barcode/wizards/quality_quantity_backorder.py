from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
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
        _logger.info(f"Starting Quality Backorder for Picking: {self.picking_id.name if self.picking_id else 'None'}")
        
        if not self.picking_type_id:
            raise UserError(_("Operation Type wajib diisi!"))
        if not self.line_ids:
            raise UserError(_("Tambahkan setidaknya satu produk!"))

        # 1. Buat Picking Baru
        new_picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type_id.id,
            'location_id': self.line_ids[0].location_id.id,
            'location_dest_id': self.picking_type_id.default_location_dest_id.id,
            'company_id': self.company_id.id,
            'origin': self.picking_id.name if self.picking_id else "Quality Backorder",
            'backorder_id': self.picking_id.id if self.picking_id else False,
            'po_sap_id': self.picking_id.po_sap_id.id if self.picking_id.po_sap_id else False,
        })
        _logger.info(f"New Picking created: {new_picking.name}")

        # 2. Proses Move dan Move Lines
        for line in self.line_ids:
            _logger.info(f"Processing line for product {line.product_id.display_name}, Qty: {line.qty}")
            
            # Hitung base quantity
            base_qty = line.product_uom_id._compute_quantity(line.qty, line.product_id.uom_id)
            
            # Buat Stock Move di Picking baru
            move = self.env['stock.move'].create({
                'product_id': line.product_id.id,
                'product_uom_qty': base_qty,
                'product_uom': line.product_id.uom_id.id,
                'location_id': line.location_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'picking_id': new_picking.id,
                'company_id': self.company_id.id,
            })
            move._action_confirm()
            
            # Update/Reduce Move Line Asli
            if line.move_line_id:
                orig_ml = line.move_line_id
                _logger.info(f"Reducing original move line {orig_ml.id}. Old Qty: {orig_ml.quantity}")
                
                new_orig_ml_qty = orig_ml.quantity - line.qty
                new_orig_ml_qty_pack = orig_ml.bag_qty - line.qty_pack
                if new_orig_ml_qty > 0:
                    orig_ml.write({
                        'quantity': new_orig_ml_qty,
                        'bag_qty': new_orig_ml_qty_pack,
                    })
                else:
                    orig_ml.unlink()

            # Create Move Line di Picking baru
            move.move_line_ids.unlink()
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': new_picking.id,
                'product_id': line.product_id.id,
                'product_uom_id': line.product_uom_id.id,
                'quantity': line.qty,
                'uom_bag_id': line.pack_uom_id.id,
                'bag_qty': line.qty_pack,
                'location_id': line.location_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'lot_id': line.lot_id.id if hasattr(line, 'lot_id') else False,
                'package_id': line.package_id.id if line.package_id else False, 
                'result_package_id': line.result_package_id.id if line.result_package_id else False,
                'production_line_id': line.production_line_id.id,
                'stock_type': 'QI',
            })

        # 3. Finalisasi Picking
        new_picking.action_assign()
        new_picking.action_confirm()
        if new_picking.state == 'assigned':
            new_picking.with_context(skip_backorder=True).button_validate()
            _logger.info(f"Picking {new_picking.name} validated successfully.")
        else:
            _logger.warning(f"Picking {new_picking.name} status: {new_picking.state}. Attempting force done.")
            new_picking.action_done()
        
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Success",
                "message": "Quality Backorder telah diproses.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"}, # Menutup wizard
            },
        }
        
class QualityQuantityBackorderLine(models.TransientModel):
    _name = 'quality.quantity.backorder.line'
    _description = 'Quality Quantity Backorder Line'

    backorder_wizard_id = fields.Many2one(comodel_name='quality.quantity.backorder', string="Wizard Reference", required=True, ondelete='cascade')
    move_line_id = fields.Many2one(comodel_name='stock.move.line', string="MoveLine")
    product_id = fields.Many2one(comodel_name='product.product', string="Product", required=True)
    qty = fields.Float(string="Quantity")
    product_uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    qty_pack = fields.Float(string="Quantity")
    pack_uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    result_package_id = fields.Many2one(comodel_name='stock.package', string="Destination Package")
    lot_id = fields.Many2one(comodel_name='stock.lot', string="Lot/Serial Number")
    location_id = fields.Many2one(comodel_name='stock.location', string="Source Location")
    package_id = fields.Many2one(comodel_name='stock.package', string="Package")
    production_line_id = fields.Many2one(comodel_name='production.line', string="Production Line")
    
    @api.onchange('qty_pack')
    def _onchange_qty_pack(self):
        for rec in self:
            if rec.qty_pack > 0 and rec.pack_uom_id and rec.product_uom_id:
                rec.qty = rec.pack_uom_id._compute_quantity(rec.qty_pack, rec.product_uom_id)