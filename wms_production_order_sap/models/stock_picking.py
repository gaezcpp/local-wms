from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
import pytz
import logging
_logger = logging.getLogger(__name__)
class InheritBaseStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="PO SAP", tracking=True)

    def now_jakarta(self):
        tz = pytz.timezone('Asia/Jakarta')
        return datetime.now(tz)

    def _prepare_backorder_picking_vals(self):
        self.ensure_one()
        vals = super()._prepare_backorder_picking_vals()
        Shift = self.env['production.shift'].sudo()
        prod_shift = self.production_shift_id
        right_now = self.now_jakarta()
        now_hour = right_now.strftime('%H%M')
        if not prod_shift:
            all_shifts = Shift.search([])
            for shift in all_shifts:
                start = shift.date_start
                end = shift.date_end
                if start <= end:
                    if start <= now_hour <= end:
                        prod_shift = shift
                        break
                else: 
                    if now_hour >= start or now_hour <= end:
                        prod_shift = shift
                        break

        vals.update({
            'production_shift_id': prod_shift.id if prod_shift else False,
            'po_sap_id': self.po_sap_id.id,
        })

        return vals
    
    def action_confirm(self):
        for picking in self:
            if picking.picking_type_id.production_only:
                if not picking.po_sap_id:
                    raise ValidationError("Tidak dapat melakukan Validate karena tidak memiliki PO SAP!")
            if picking.po_sap_id and (not picking.po_sap_id.active or picking.po_sap_id.state in ('teco', 'closed')):
                raise ValidationError("Tidak dapat melakukan Confirm. PO SAP tidak aktif atau berstatus TECO!")
        
        res = super().action_confirm()
        Shift = self.env['production.shift'].sudo()
        for picking in self:
            right_now = self.now_jakarta()
            now_hour = right_now.strftime('%H%M')
            # _logger.info(f"NOW HOUR {now_hour}")
            prod_shift = picking.production_shift_id
            if not prod_shift:
                all_shifts = Shift.search([])
                for shift in all_shifts:
                    start = shift.date_start
                    end = shift.date_end
                    if start <= end:
                        if start <= now_hour <= end:
                            prod_shift = shift
                            break
                    else: 
                        if now_hour >= start or now_hour <= end:
                            prod_shift = shift
                            break
            if prod_shift:
                picking.production_shift_id = prod_shift.id
        return res

    def button_validate(self):
        for picking in self:
            if picking.picking_type_id.production_only and not picking.po_sap_id:
                raise ValidationError(f"Tidak bisa melakukan Validate karena {picking.picking_type_id.name} membutuhkan PO SAP")
            if picking.po_sap_id and (not picking.po_sap_id.active or picking.po_sap_id.state in ('teco', 'closed')):
                raise ValidationError("Tidak dapat melakukan Validate. PO SAP tidak aktif atau berstatus TECO!")
        
        res = super().button_validate()
        Shift = self.env['production.shift'].sudo()
        for picking in self:
            right_now = self.now_jakarta()
            now_hour = right_now.strftime('%H%M')
            prod_shift = picking.production_shift_id
            if not prod_shift:
                all_shifts = Shift.search([])
                for shift in all_shifts:
                    start = shift.date_start
                    end = shift.date_end
                    if start <= end:
                        if start <= now_hour <= end:
                            prod_shift = shift
                            break
                    else: 
                        if now_hour >= start or now_hour <= end:
                            prod_shift = shift
                            break
            if prod_shift:
                picking.production_shift_id = prod_shift.id

            next_pickings = picking.move_ids.move_dest_ids.picking_id.filtered(lambda p: p.state not in ('done', 'cancel'))
            if next_pickings:
                next_pickings.sudo().write({
                    'production_shift_id': prod_shift.id if prod_shift else False,
                    **(({'po_sap_id': picking.po_sap_id.id}) if picking.po_sap_id else {}),
                })
        return res
    
    def _action_done(self):
        res = super()._action_done()
        for picking in self:
            # picking._propagate_po_sap_to_quant() # Pindah related stock.lot
            if picking.po_sap_id and picking.po_sap_id.state not in ('teco', 'closed'):
                picking.po_sap_id.state = 'in_progress'
        return res
    
    # isi po_sap_id di stock.quant
    # Pindah related stock.lot
    # def _propagate_po_sap_to_quant(self):
    #     for picking in self.filtered(lambda p: p.po_sap_id and p.state == 'done'):
    #         quants = picking.move_line_ids.mapped('quant_id')
    #         quants = quants.filtered(lambda q: not q.po_sap_id)
    #         if quants:
    #             quants.write({'po_sap_id': picking.po_sap_id.id})