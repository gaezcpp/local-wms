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

    @api.model
    def _find_current_shift(self):
        """Shift produksi yang sedang berjalan (waktu Jakarta).

        Dipakai bergantian oleh action_confirm(), button_validate() dan
        _prepare_backorder_picking_vals(); semuanya dulu menyalin loop yang sama
        DAN memanggil `production.shift` search([]) di dalam loop per picking.
        """
        now_hour = self.now_jakarta().strftime('%H%M')
        for shift in self.env['production.shift'].sudo().search([]):
            start = shift.date_start
            end = shift.date_end
            if start <= end:
                if start <= now_hour <= end:
                    return shift
            elif now_hour >= start or now_hour <= end:
                return shift
        return self.env['production.shift']

    def _prepare_backorder_picking_vals(self):
        self.ensure_one()
        vals = super()._prepare_backorder_picking_vals()
        prod_shift = self.production_shift_id or self._find_current_shift()

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
        missing_shift = self.filtered(lambda p: not p.production_shift_id)
        if missing_shift:
            current_shift = self._find_current_shift()
            if current_shift:
                missing_shift.production_shift_id = current_shift.id
        return res

    def button_validate(self):
        for picking in self:
            if picking.picking_type_id.production_only and not picking.po_sap_id:
                raise ValidationError(f"Tidak bisa melakukan Validate karena {picking.picking_type_id.name} membutuhkan PO SAP")
            if picking.po_sap_id and (not picking.po_sap_id.active or picking.po_sap_id.state in ('teco', 'closed')):
                raise ValidationError("Tidak dapat melakukan Validate. PO SAP tidak aktif atau berstatus TECO!")
            if picking.po_sap_id and picking.picking_type_id.production_only:
                qty_to_validate = sum(picking.move_ids.mapped('quantity'))
                picking.po_sap_id.over_tolerance(additional_qty=qty_to_validate)
        
        res = super().button_validate()
        if isinstance(res, dict):
            # Masih menunggu wizard: shift & PO SAP baru relevan setelah
            # dokumennya benar-benar selesai, jadi tidak perlu menulis apa-apa.
            return res

        # `_find_current_shift()` menembak `production.shift` sekali saja untuk
        # seluruh batch, bukan sekali per picking di dalam loop.
        current_shift = None
        for picking in self:
            prod_shift = picking.production_shift_id
            if not prod_shift:
                if current_shift is None:
                    current_shift = self._find_current_shift()
                prod_shift = current_shift
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
            if picking.po_sap_id and picking.po_sap_id.state not in ('teco', 'closed'):
                picking.po_sap_id.state = 'in_progress'
        return res