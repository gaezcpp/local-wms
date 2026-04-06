from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InheritBaseStockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    production_line_id = fields.Many2one(comodel_name='production.line', string="Line")
    first_count = fields.Float(string="First Count")
    last_count = fields.Float(string="Last Count")
    detail_text = fields.Char(string="Detail Text")
    production_only = fields.Boolean(string="Production Only", related='picking_type_id.production_only')
    
    # fields buat chriss
    sloc_name = fields.Char(related='location_dest_id.sloc_name', string="SLOC")
    destination_package_status = fields.Selection(related='result_package_id.state')
    production_shift_id = fields.Many2one(related='picking_id.production_shift_id', string="Shift")
    production_order_name = fields.Char(related='picking_id.production_order_name', string="Production Order")
    
    # ini dipake kalo odoo.sh salah
    def _skip_custom_logic(self):
        ctx = self.env.context
        return (
            ctx.get('inventory_mode') or
            ctx.get('install_mode') or
            ctx.get('install_demo') or
            ctx.get('test_enable')
        )
    
    def _get_or_create_lot(self):
        self.ensure_one()
        if not self.expiration_date or not self.move_id.product_id:
            return False

        date_str = self.expiration_date.strftime("%d%m%Y")
        po_number = self.move_id.picking_id.po_sap_id.po_number or ''
        lot_name = f"{po_number}-{date_str}"

        lot = self.env['stock.lot'].search([
            ('name', '=', lot_name),
            ('product_id', '=', self.move_id.product_id.id)
        ], limit=1)

        if not lot:
            lot = self.env['stock.lot'].create({
                'name': lot_name,
                'product_id': self.move_id.product_id.id,
            })

        return lot

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec._is_prod_in():
                lot = rec._get_or_create_lot()
                if lot:
                    rec.lot_id = lot.id
        return records


    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if 'expiration_date' in vals and rec._is_prod_in():
                lot = rec._get_or_create_lot()
                if lot:
                    rec.lot_id = lot.id
        return res
    
    def _is_prod_in(self, vals=None):
        picking = False
        if vals and vals.get('picking_id'):
            picking = self.env['stock.picking'].browse(vals['picking_id'])
        elif self.picking_id:
            picking = self.picking_id
        elif self.move_id and self.move_id.picking_id:
            picking = self.move_id.picking_id
        return picking and picking.picking_type_id.sequence_code == 'PROD-IN'
    
    @api.onchange('production_line_id', 'first_count', 'last_count', 'detail_text')
    def _onchange_prod_in_fields(self):
        for rec in self:
            if not rec._is_prod_in():
                raise ValidationError("Production fields hanya boleh diedit pada Operation Type PROD-IN")