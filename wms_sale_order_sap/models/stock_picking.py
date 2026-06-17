from odoo import models, fields, api

class SaleStockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') != '/':
                continue

            picking_type_id = vals.get('picking_type_id')
            if not picking_type_id:
                continue

            # 1. Prioritaskan pembacaan context dari eksekusi cron
            # 2. Cek sale_id bawaan jika odoo mem-passing nilainya secara langsung
            sale_id = self.env.context.get('sequence_sale_order_id') or vals.get('sale_id')
            sale = self.env['sale.order']

            if sale_id:
                sale = sale.browse(sale_id)
            # 3. Fallback menggunakan field 'origin' yang mencatat persis nomor dokumen (misal: S00012)
            elif vals.get('origin'):
                sale = sale.search([('name', '=', vals.get('origin'))], limit=1)

            if not sale or not sale.exists() or not sale.do_sap:
                continue

            picking_type = self.env['stock.picking.type'].browse(picking_type_id)
            sequence = picking_type.sequence_id
            if not sequence:
                continue

            # Melanjutkan injeksi context agar generator sequence ir.sequence berfungsi normal
            vals['name'] = sequence.with_context(sequence_sale_order_id=sale.id).next_by_id()

        return super().create(vals_list)