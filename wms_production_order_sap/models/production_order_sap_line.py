from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
import logging
import pytz
_logger = logging.getLogger(__name__)


class ProductionOrderSAPLine(models.Model):
    _name = 'production.order.sap.line'
    _description = 'Production Order SAP Line'
    
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', index=False, ondelete='cascade')
    no_item = fields.Char(string="Seq")
    product_id = fields.Many2one(comodel_name='product.product', string="Product")
    uom_id = fields.Many2one(comodel_name='uom.uom', string="Unit")
    order_qty = fields.Float(string="Qty")
    total_picking_wip = fields.Integer(string="Total WIP")
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string="OP Type")
    picking_created = fields.Boolean(string="Picking Created")
    warehouse_id = fields.Many2one(comodel_name='stock.warehouse', string="SLOC")
    
    def now_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        return datetime.now(tz)
    
    def action_create_picking_wip(self):
        right_now = self.now_jakarta()
        now_hour = right_now.strftime('%H%M')
        prod_shift = self.env['production.shift'].sudo().search([('date_start', '<=', now_hour),('date_end', '>=', now_hour)], limit=1)
        
        for rec in self:
            if rec.po_sap_id.active and rec.picking_type_id:
                picking = self.env['stock.picking'].create({
                    'picking_type_id': rec.picking_type_id.id,
                    'location_dest_id': rec.picking_type_id.default_location_dest_id.id,
                    'production_shift_id': prod_shift.id if prod_shift else False,
                    'scheduled_date': rec.po_sap_id.finish_date,
                    'date_deadline': rec.po_sap_id.finish_date,
                    'po_sap_id': rec.po_sap_id.id,
                    'company_id': rec.po_sap_id.company_id.id,
                    'origin': rec.po_sap_id.po_number,
                    'note': f"WIP Created From Production Order {rec.po_sap_id.po_number}",
                    'user_id': False,
                })
                
                move_vals = []
                if picking and rec.product_id:
                    move_vals.append({
                        'picking_id': picking.id,
                        'product_id': rec.product_id.id,
                        'product_uom_qty': rec.order_qty,
                        'product_uom': rec.uom_id.id,
                        'company_id': rec.po_sap_id.company_id.id,
                        'location_id': rec.picking_type_id.default_location_src_id.id,
                        'location_dest_id': rec.picking_type_id.default_location_dest_id.id,
                    })
                    
                    if move_vals:
                        self.env['stock.move'].sudo().create(move_vals)
                        
                    picking.message_post(body=f"WIP Created From Production Order {rec.po_sap_id.po_number}")
                    picking.action_confirm()
                    
                    if picking.move_line_ids:
                        picking.move_line_ids.sudo().write({'stock_type': 'QI'})
                        
                    rec.write({'picking_created': True})