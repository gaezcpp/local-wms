from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)

class InheritStockQuant(models.Model):
    _inherit = 'stock.quant'

    uom_bag_id = fields.Many2one('uom.uom', related='product_id.uom_bag_id', store=True)
    uom_pallet_id = fields.Many2one('uom.uom', related='product_id.uom_pallet_id', store=True)
    bag_qty = fields.Float(string="Bag", compute='_compute_bag_pallet_qty', store=True)
    pallet_qty = fields.Float(string="Pallet", compute='_compute_bag_pallet_qty', store=True)
    bag_dummy_qty = fields.Float(string="Bag Dummy", compute='_compute_dummy_qty', inverse='_inverse_bag_dummy_qty', store=True)
    pallet_dummy_qty = fields.Float(string="Pallet Dummy Qty", compute='_compute_dummy_qty', store=True)

    def _skip_custom_logic(self):
        ctx = self.env.context
        return (
            ctx.get('inventory_mode') or
            ctx.get('install_mode') or
            ctx.get('install_demo') or
            ctx.get('test_enable')
        )
    
    @api.depends('quantity', 'product_uom_id', 'uom_bag_id', 'uom_pallet_id')
    def _compute_bag_pallet_qty(self):
        for rec in self:
            if rec.quantity and rec.product_uom_id:
                if rec.uom_bag_id and rec.uom_bag_id.factor:
                    rec.bag_qty = ((rec.quantity * rec.product_uom_id.factor) / 1000) / (rec.uom_bag_id.factor / 1000)
                else:
                    rec.bag_qty = 0.0

                if rec.uom_pallet_id and rec.uom_pallet_id.factor:
                    rec.pallet_qty = ((rec.quantity * rec.product_uom_id.factor) / 1000) / (rec.uom_pallet_id.factor / 1000)
                else:
                    rec.pallet_qty = 0.0
            else:
                rec.bag_qty = 0.0
                rec.pallet_qty = 0.0

    @api.depends('inventory_quantity', 'product_uom_id', 'uom_bag_id', 'uom_pallet_id')
    def _compute_dummy_qty(self):
        for rec in self:
            if rec.inventory_quantity and rec.product_uom_id:
                if rec.uom_bag_id and rec.uom_bag_id.factor:
                    rec.bag_dummy_qty = ((rec.inventory_quantity * rec.product_uom_id.factor) / 1000) / (rec.uom_bag_id.factor / 1000)
                else:
                    rec.bag_dummy_qty = 0.0

                if rec.uom_pallet_id and rec.uom_pallet_id.factor:
                    rec.pallet_dummy_qty = ((rec.inventory_quantity * rec.product_uom_id.factor) / 1000) / (rec.uom_pallet_id.factor / 1000)
                else:
                    rec.pallet_dummy_qty = 0.0
            else:
                rec.bag_dummy_qty = 0.0
                rec.pallet_dummy_qty = 0.0

    def _inverse_bag_dummy_qty(self):
        for rec in self:
            if rec.bag_dummy_qty and rec.uom_bag_id and rec.product_uom_id and rec.product_uom_id.factor:
                rec.inventory_quantity = (rec.bag_dummy_qty / 1000.0) * rec.uom_bag_id.factor / rec.product_uom_id.factor
            elif not rec.bag_dummy_qty:
                rec.inventory_quantity = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self._skip_custom_logic():
            records._recompute_package_pallet_status()
        return records
    
    def write(self, vals):
        res = super().write(vals)
        if not self._skip_custom_logic():
            # Optimasi: Hanya hitung ulang status jika ada perubahan pada kuantitas
            if any(k in vals for k in ('quantity', 'inventory_quantity', 'package_id')):
                self._recompute_package_pallet_status()
        return res
    
    def _recompute_package_pallet_status(self):
        param = self.env['ir.config_parameter'].sudo().get_param('pembagi_pallet')
        if not param:
            return

        try:
            pembagi_pallet = float(param)
        except ValueError:
            return

        if pembagi_pallet == 0:
            return

        packages = self.mapped('package_id').filtered(lambda p: p)
        for pkg in packages:
            pallet_status = 'eceran'
            quants = pkg.contained_quant_ids.filtered(lambda q: q.quantity > 0)

            product_ids = quants.mapped('product_id')
            if len(product_ids) == 1 and quants:
                quant = quants[0]
                uom_pallet = quant.product_id.uom_pallet_id

                if uom_pallet and quant.quantity:
                    try:
                        result = (uom_pallet.factor / pembagi_pallet) / quant.quantity
                        # Toleransi koma desimal menggunakan fungsi absolut
                        if abs(result - 1) < 0.00001:
                            pallet_status = 'full_pallet'
                    except ZeroDivisionError:
                        pass

            if pkg.pallet_status != pallet_status:
                pkg.pallet_status = pallet_status