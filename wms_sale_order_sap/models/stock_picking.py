from odoo import models, fields, api

class SaleStockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Lewati jika name sudah diisi (selain '/')
            if vals.get('name', '/') != '/':
                continue
            
            picking_type_id = vals.get('picking_type_id')
            if not picking_type_id:
                continue
            
            sale_id = self.env.context.get('sequence_sale_order_id')
            sale = self.env['sale.order']

            # 1. Dari context (prioritas utama, misal di-inject dari button action)
            if sale_id:
                sale = sale.browse(sale_id)
                
            # 2. TANGKAPAN KHUSUS BACKORDER (Mengambil SO dari picking asalnya)
            elif vals.get('backorder_id'):
                backorder = self.env['stock.picking'].browse(vals.get('backorder_id'))
                # Memastikan field sale_id ada pada model stock.picking (bawaan modul sale_stock)
                if hasattr(backorder, 'sale_id') and backorder.sale_id:
                    sale = backorder.sale_id
                    
            # 3. Dari nilai langsung jika Odoo V19 melemparnya di dalam vals
            elif vals.get('sale_id'):
                sale = sale.browse(vals.get('sale_id'))
                    
            # 4. Fallback terakhir dari field origin
            elif vals.get('origin'):
                sale = sale.search([('name', '=', vals.get('origin'))], limit=1)

            # Jika SO ditemukan dan punya nilai do_sap, inject context ke generator sequence
            if sale and sale.exists() and sale.do_sap:
                picking_type = self.env['stock.picking.type'].browse(picking_type_id)
                sequence = picking_type.sequence_id
                if sequence:
                    vals['name'] = sequence.with_context(sequence_sale_order_id=sale.id).next_by_id()

        return super().create(vals_list)