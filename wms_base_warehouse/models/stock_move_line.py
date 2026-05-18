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
    
    # untuk stock.lot.aft ngurangin yang UU
    def _action_done(self):
        for line in self:
            picking_type = line.picking_id.picking_type_code
            if picking_type == 'outgoing' and line.lot_id:
                lot = line.lot_id

                qty_to_reduce = line.qty_done
                bag_to_reduce = line.bag_qty

                if not bag_to_reduce:
                    product_uom = line.product_id.uom_id
                    uom_bag = line.product_id.uom_bag_id
                    if product_uom and uom_bag:
                        bag_to_reduce = product_uom._compute_quantity(qty_to_reduce, uom_bag)

                aft_uu_lines = lot.lot_aft_ids.filtered(
                    lambda a: a.stock_type == 'UU' and (a.quantity > 0 or a.bag_qty > 0)
                )

                remaining_qty = qty_to_reduce
                remaining_bag = bag_to_reduce

                for aft in aft_uu_lines:
                    if remaining_qty <= 0 and remaining_bag <= 0:
                        break

                    deduct_qty = 0
                    deduct_bag = 0

                    if remaining_qty > 0:
                        deduct_qty = min(aft.quantity, remaining_qty)
                        aft.quantity -= deduct_qty
                        remaining_qty -= deduct_qty

                    if remaining_bag > 0:
                        deduct_bag = min(aft.bag_qty, remaining_bag)
                        aft.bag_qty -= deduct_bag
                        remaining_bag -= deduct_bag

                    lot.message_post(
                        body=(
                            f"Updated from {line.picking_id.name}: "
                            f"Quantity -{deduct_qty} {aft.uom_id.name or ''} → Remaining {aft.quantity} {aft.uom_id.name or ''} | "
                            f"Bag Qty -{deduct_bag} {aft.uom_bag_id.name or ''} → Remaining {aft.bag_qty} {aft.uom_bag_id.name or ''}"
                        )
                    )
                    
            po_sap_id = line.picking_id.po_sap_id
            if not po_sap_id:
                continue

            quants = self.env['stock.quant'].sudo().search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', line.location_dest_id.id),
                ('lot_id', '=', line.lot_id.id if line.lot_id else False),
                ('package_id', '=', line.result_package_id.id if line.result_package_id else False),
            ])
            quants.write({'po_sap_id': po_sap_id.id})

        return super()._action_done()