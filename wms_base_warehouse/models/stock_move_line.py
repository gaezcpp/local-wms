from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InheritBaseStockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    production_line_id = fields.Many2one(comodel_name='production.line', string="Line")
    first_count = fields.Float(string="First Count")
    last_count = fields.Float(string="Last Count")
    detail_text = fields.Char(string="Detail Text")
    production_only = fields.Boolean(string="Production Only", related='picking_type_id.production_only', store=True)
    
    # fields buat chriss
    sloc_name = fields.Char(related='location_dest_id.sloc_name', string="SLOC Name", store=True)
    sloc_id = fields.Many2one(comodel_name='storage.location', string="SLOC")
    production_shift_id = fields.Many2one(related='picking_id.production_shift_id', string="Shift", store=True)
    production_order_name = fields.Char(related='picking_id.production_order_name', string="Production Order Name", store=True)
    stock_type = fields.Selection([
        ('QI', 'QI'),
        ('BLOCKED', 'BLOCKED'),
        ('UU', 'UU'),
    ], string="Stock Type")
    
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
        if not self.move_id.product_id:
            return False

        prod_code_rec = self.env['production.code'].search([('company_id', '=', self.company_id.id)], limit=1)
        if not prod_code_rec or not prod_code_rec.code:
            raise ValidationError("Konfigurasi Production Code (Format Lot) belum diatur untuk company ini!")

        prod_group = self.env['production.group'].sudo().search([
            ('user_id', '=', self.env.user.id),
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        
        group_code = prod_group.code if prod_group else ''
        localdict = {
            'self': self,
            'picking': self.picking_id,
            'moveline': self,
            'fields': fields,
            'str': str,
            'int': int,
            'group_code': group_code,
        }

        try:
            lot_name = eval(f'f"""{prod_code_rec.code}"""', localdict)
        except Exception as e:
            raise ValidationError(f"Terjadi kesalahan saat memproses format Production Code: {e}")

        lot = self.env['stock.lot'].search([
            ('name', '=', lot_name),
            ('product_id', '=', self.move_id.product_id.id),
            ('company_id', '=', self.company_id.id)
        ], limit=1)

        if not lot:
            lot = self.env['stock.lot'].search([
                ('id', '=', self.lot_id.id),
                ('product_id', '=', self.move_id.product_id.id),
                ('company_id', '=', self.company_id.id)
            ], limit=1)
            if not lot:
                lot = self.env['stock.lot'].create({
                    'name': lot_name,
                    'product_id': self.move_id.product_id.id,
                    'company_id': self.company_id.id,
                })

        return lot
    
    def _create_update_lot_aft(self):
        self.ensure_one()
        if not self.move_id.product_id:
            return False

        lot = self._get_or_create_lot()
        if not lot:
            return False

        existing_aft = lot.lot_aft_ids.filtered(lambda l: l.stock_type == (self.stock_type or 'QI'))
        
        bag = self.bag_qty
        if bag <= 0:
            bag = ((self.quantity * self.product_uom_id.factor) / 1000) / (self.uom_bag_id.factor / 1000)

        if existing_aft:
            aft = existing_aft[0]
            old_qty = aft.quantity
            old_bag = aft.bag_qty
            new_qty = old_qty + self.quantity
            new_bag = old_bag + bag

            aft.write({
                'quantity': new_qty,
                'bag_qty': new_bag,
            })

            lot.message_post(body=(
                f"Stock Type : {self.stock_type or 'QI'} "
                f"Quantity   : {old_qty} → {new_qty} {self.product_uom_id.name} "
                f"Bag Qty    : {old_bag} → {new_bag} {self.uom_bag_id.name} "
            ))
        else:
            self.env['stock.lot.aft'].create({
                'lot_id': lot.id,
                'quantity': self.quantity,
                'uom_id': self.product_uom_id.id,
                'bag_qty': bag,
                'uom_bag_id': self.uom_bag_id.id,
                'stock_type': self.stock_type or 'QI',
            })

            lot.message_post(body=(
                f"Stock Type : {self.stock_type or 'QI'} "
                f"Quantity   : {self.quantity} {self.product_uom_id.name} "
                f"Bag Qty    : {bag} {self.uom_bag_id.name} "
            ))

        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec._is_gr_prod():
                lot = rec._get_or_create_lot()
                if lot:
                    rec.lot_id = lot.id
                    rec.stock_type = lot.stock_type
                    rec._create_update_lot_aft()
        return records


    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if 'expiration_date' in vals and rec._is_gr_prod():
                lot = rec._get_or_create_lot()
                if lot:
                    rec.lot_id = lot.id
                    rec._create_update_lot_aft()
        return res
    
    def _is_gr_prod(self, vals=None):
        picking = False
        prod_in_move_type = self.env['ir.config_parameter'].sudo().get_param('prod_in_move_type')
        if not prod_in_move_type:
            raise ValidationError("prod_in_move_type pada Operation Type belum disetting!")
        else:
            if vals and vals.get('picking_id'):
                picking = self.env['stock.picking'].browse(vals['picking_id'])
            elif self.picking_id:
                picking = self.picking_id
            elif self.move_id and self.move_id.picking_id:
                picking = self.move_id.picking_id
            return picking and picking.picking_type_id.move_type_sap == str(prod_in_move_type)
        
    @api.onchange('lot_id')
    def _onchange_lot_id_stock_type(self):
        for rec in self:
            if rec.lot_id and rec.lot_id.stock_type:
                rec.stock_type = rec.lot_id.stock_type
            else:
                rec.stock_type = 'QI'