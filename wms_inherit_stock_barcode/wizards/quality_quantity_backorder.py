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
    result_package_id = fields.Many2one(comodel_name='stock.package', string="Destination Pallet")
    is_quality = fields.Boolean(string="Is Quality", default=False)
    line_ids = fields.One2many(comodel_name='quality.quantity.backorder.line',inverse_name='backorder_wizard_id', string="Products")
    
    def action_create_backorder_from_qq(self):
        self.ensure_one()

        if not self.picking_type_id:
            raise UserError("Operation Type wajib diisi!")
        if not self.line_ids:
            raise UserError("Tambahkan setidaknya satu produk!")
        
        for line in self.line_ids:
            if line.qty_pack > line.limit_qty_pack:
                raise ValidationError(f"Quantity untuk Product {line.product_id.default_code} melebihi batas")
            if not line.result_package_id:
                raise ValidationError(f"Destination Pallet untuk Product {line.product_id.default_code} harus diisi!")
            if not line.wh_category_id:
                raise ValidationError(f"Category untuk Product {line.product_id.default_code} harus diisi!")

        new_picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type_id.id,
            'location_id': self.line_ids[0].location_id.id,
            'location_dest_id': self.picking_type_id.default_location_dest_id.id,
            'company_id': self.company_id.id,
            'origin': self.picking_id.name if self.picking_id else "Quality Backorder",
            'backorder_id': self.picking_id.id if self.picking_id else False,
            'po_sap_id': self.picking_id.po_sap_id.id if self.picking_id.po_sap_id else False,
        })

        for line in self.line_ids:
            base_qty = line.product_uom_id._compute_quantity(line.qty, line.product_id.uom_id)

            orig_ml = line.move_line_id
            orig_move = orig_ml.move_id if orig_ml else False
            source_package_id = orig_ml.package_id.id if orig_ml and orig_ml.package_id else (line.package_id.id if line.package_id else False) #AI
            source_lot_id = orig_ml.lot_id.id if orig_ml and orig_ml.lot_id else (line.lot_id.id if line.lot_id else False) #AI

            move = self.env['stock.move'].create({
                'product_id': line.product_id.id,
                'product_uom_qty': base_qty,
                'product_uom': line.product_id.uom_id.id,
                'location_id': line.location_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'picking_id': new_picking.id,
                'company_id': self.company_id.id,
                'sale_line_id': orig_move.sale_line_id.id if orig_move and orig_move.sale_line_id else False,
                'purchase_line_id': orig_move.purchase_line_id.id if orig_move and orig_move.purchase_line_id else False,
                'sap_seq': orig_move.sap_seq if orig_move else 0,
                'order_seq': orig_move.order_seq if orig_move else 0,
                'order_selection': orig_move.order_selection if orig_move else 0,
            })
            move._action_confirm()

            if orig_ml:
                new_orig_ml_qty = orig_ml.quantity - line.qty
                new_orig_ml_qty_pack = orig_ml.bag_qty - line.qty_pack
                if new_orig_ml_qty > 0:
                    orig_ml.write({
                        'quantity': new_orig_ml_qty,
                        'bag_qty': new_orig_ml_qty_pack,
                    })
                else:
                    orig_ml.unlink()
                
                # Ngurangin demand  
                # if orig_move:
                #     deduct_qty = line.product_uom_id._compute_quantity(line.qty, orig_move.product_uom)
                #     new_move_qty = orig_move.product_uom_qty - deduct_qty
                #     orig_move.write({'product_uom_qty': max(0, new_move_qty)})
                #     _logger.info(f"Reducing original move {orig_move.id} demand to {max(0, new_move_qty)}")

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
                'lot_id': source_lot_id,
                'package_id': source_package_id,
                'result_package_id': line.result_package_id.id if line.result_package_id else False,
                'production_line_id': line.production_line_id.id,
                'stock_type': line.move_line_id.stock_type if line.move_line_id else 'QI',
                'wh_category_id': line.wh_category_id.id if line.wh_category_id else False,
            })

        new_picking.action_confirm()
        new_picking.action_assign()
        if new_picking.state == 'assigned':
            new_picking.with_context(skip_backorder=True).button_validate()
        else:
            new_picking.action_done()
        
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Success",
                "message": "Quality Backorder telah diproses.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
    
    # def action_create_backorder_from_qq(self):
    #     self.ensure_one()

    #     if not self.picking_type_id:
    #         raise UserError("Operation Type wajib diisi!")
    #     if not self.line_ids:
    #         raise UserError("Tambahkan setidaknya satu produk!")
        
    #     for line in self.line_ids:
    #         if line.qty_pack > line.limit_qty_pack:
    #             raise ValidationError(f"Quantity untuk Product {line.product_id.default_code} melebihi batas")
    #         if not line.result_package_id:
    #             raise ValidationError(f"Destination Pallet untuk Product {line.product_id.default_code} harus diisi!")
    #         if not line.wh_category_id:
    #             raise ValidationError(f"Category untuk Product {line.product_id.default_code} harus diisi!")

    #     new_picking = self.env['stock.picking'].create({
    #         'picking_type_id': self.picking_type_id.id,
    #         'location_id': self.line_ids[0].location_id.id,
    #         'location_dest_id': self.picking_type_id.default_location_dest_id.id,
    #         'company_id': self.company_id.id,
    #         'origin': self.picking_id.name if self.picking_id else "Quality Backorder",
    #         'backorder_id': self.picking_id.id if self.picking_id else False,
    #         'po_sap_id': self.picking_id.po_sap_id.id if self.picking_id.po_sap_id else False,
    #     })

    #     move_vals_list = []
    #     for line in self.line_ids:
    #         base_qty = line.product_uom_id._compute_quantity(line.qty, line.product_id.uom_id)
    #         orig_ml = line.move_line_id
    #         orig_move = orig_ml.move_id if orig_ml else False

    #         move_vals_list.append({
    #             'product_id': line.product_id.id,
    #             'product_uom_qty': base_qty,
    #             'product_uom': line.product_id.uom_id.id,
    #             'location_id': line.location_id.id,
    #             'location_dest_id': new_picking.location_dest_id.id,
    #             'picking_id': new_picking.id,
    #             'company_id': self.company_id.id,
    #             'sale_line_id': orig_move.sale_line_id.id if orig_move and orig_move.sale_line_id else False,
    #             'purchase_line_id': orig_move.purchase_line_id.id if orig_move and orig_move.purchase_line_id else False,
    #             'sap_seq': orig_move.sap_seq if orig_move else 0,
    #             'order_seq': orig_move.order_seq if orig_move else 0,
    #             'order_selection': orig_move.order_selection if orig_move else 0,
    #         })

    #         if orig_ml:
    #             new_orig_ml_qty = orig_ml.quantity - line.qty
    #             new_orig_ml_qty_pack = orig_ml.bag_qty - line.qty_pack
    #             if new_orig_ml_qty > 0:
    #                 orig_ml.write({
    #                     'quantity': new_orig_ml_qty,
    #                     'bag_qty': new_orig_ml_qty_pack,
    #                 })
    #             else:
    #                 orig_ml.write({
    #                     'quantity': 0,
    #                     'bag_qty': 0,
    #                 })

    #     if move_vals_list:
    #         created_moves = self.env['stock.move'].create(move_vals_list)
    #         created_moves._action_confirm()

    #     new_picking.action_confirm()
    #     new_picking.action_assign()
    #     new_picking.with_context(skip_backorder=True).button_validate()
        
    #     return {
    #         "type": "ir.actions.client",
    #         "tag": "display_notification",
    #         "params": {
    #             "title": "Success",
    #             "message": "Quality Backorder telah diproses.",
    #             "type": "success",
    #             "sticky": False,
    #             "next": {"type": "ir.actions.act_window_close"},
    #         },
    #     }
        
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
    company_id = fields.Many2one(comodel_name='res.company', string="Company")
    wh_category_id = fields.Many2one(comodel_name='stock.warehouse.category', string="Category")
    limit_qty_pack = fields.Float(string="Limit Qty Pack")
    
    @api.onchange('qty_pack')
    def _onchange_qty_pack(self):
        for rec in self:
            if rec.qty_pack > 0 and rec.pack_uom_id and rec.product_uom_id:
                rec.qty = rec.pack_uom_id._compute_quantity(rec.qty_pack, rec.product_uom_id)