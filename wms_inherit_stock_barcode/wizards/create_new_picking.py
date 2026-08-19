from odoo import models, fields, api
from odoo.exceptions import ValidationError


class CreateNewPicking(models.TransientModel):
    _name = 'create.new.picking'
    _description = 'Create New Picking'
    
    picking_id = fields.Many2one(comodel_name='stock.picking', string="Pick")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    line_ids = fields.One2many(comodel_name='create.new.picking.line', inverse_name='create_new_picking_id', string="Products")
    
    def create_new_picking_from_wizard(self):
        self.ensure_one()
        
        if not self.picking_id:
            raise ValidationError("Referensi Picking asal tidak ditemukan untuk membuat Picking baru.")
            
        orig_picking = self.picking_id
        sales_pick_type = orig_picking.sale_id.warehouse_id.pick_type_id
        
        new_picking = self.env['stock.picking'].with_context(sequence_sale_order_id=orig_picking.sale_id.id).create({
            'picking_type_id': sales_pick_type.id,
            'location_id': sales_pick_type.default_location_src_id.id,
            'location_dest_id': sales_pick_type.default_location_dest_id.id,
            'origin': orig_picking.sale_id.name if orig_picking.sale_id else False,
            'sale_id': orig_picking.sale_id.id if orig_picking.sale_id else False,
            'company_id': self.company_id.id,
            'user_id': False
        })
        
        for line in self.line_ids:
            if line.qty <= 0:
                continue
            
            so_line = orig_picking.sale_id.order_line.filtered(lambda sol: sol.product_id.id == line.product_id.id)
            so_line = so_line[:1]
            self.env['stock.move'].create({
                'picking_id': new_picking.id,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty, # Demand
                'quantity': line.qty,
                'product_uom': line.product_uom_id.id,
                # 'product_uom_qty': line.qty_pack,
                # 'quantity': line.qty_pack,
                # 'product_uom': line.pack_uom_id.id,
                'location_id': sales_pick_type.default_location_src_id.id,
                'location_dest_id': sales_pick_type.default_location_dest_id.id,
                'origin': orig_picking.sale_id.name if orig_picking.sale_id else False,
                'sale_line_id': so_line.id if so_line else False,
                'sap_seq': so_line.sap_sequence if so_line else 0,
                'order_seq': so_line.order_seq if so_line else 0,
                'order_selection': so_line.order_selection if so_line else 0,
                'company_id': self.company_id.id,
            })
            
        ctx = dict(self.env.context, bypass_adjust_demand=True)
        new_picking.message_post(body=f"New Picking created from {self.picking_id.name} New Picking")
        new_picking.with_context(ctx).action_confirm()
        new_picking.with_context(ctx).action_assign()
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Picking',
            'res_model': 'stock.picking',
            'res_id': new_picking.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
class CreateNewPickingLine(models.TransientModel):
    _name = 'create.new.picking.line'
    _description = 'Create New Picking Line'

    create_new_picking_id = fields.Many2one(comodel_name='create.new.picking', string="Wizard Reference", required=True, ondelete='cascade')
    product_id = fields.Many2one(comodel_name='product.product', string="Product", required=True)
    qty = fields.Float(string="Quantity")
    product_uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    qty_pack = fields.Float(string="Quantity")
    pack_uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    company_id = fields.Many2one(comodel_name='res.company', string="Company")
    
    @api.onchange('qty_pack')
    def _onchange_qty_pack(self):
        for rec in self:
            if rec.qty_pack > 0 and rec.pack_uom_id and rec.product_uom_id:
                rec.qty = rec.pack_uom_id._compute_quantity(rec.qty_pack, rec.product_uom_id)