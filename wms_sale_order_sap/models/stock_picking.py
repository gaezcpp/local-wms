from odoo import models, fields, api

class SaleStockPicking(models.Model):
    _inherit = 'stock.picking'

    def _find_sale_for_sequence(self, vals):
        Sale = self.env['sale.order'].sudo()

        def is_valid(sale):
            return sale and sale.exists() and (sale.do_sap or sale.po_sap)

        sale_id = self.env.context.get('sequence_sale_order_id')
        if sale_id:
            sale = Sale.browse(sale_id)
            if is_valid(sale):
                return sale

        backorder_id = vals.get('backorder_id')
        visited = set()
        while backorder_id and backorder_id not in visited:
            visited.add(backorder_id)
            parent = self.env['stock.picking'].browse(backorder_id)
            if parent.exists():
                if is_valid(parent.sale_id):
                    return parent.sale_id
                backorder_id = parent.backorder_id.id if parent.backorder_id else False
            else:
                backorder_id = False

        if vals.get('sale_id'):
            sale = Sale.browse(vals.get('sale_id'))
            if is_valid(sale):
                return sale

        if vals.get('origin'):
            for name in [o.strip() for o in vals.get('origin').split(',') if o.strip()]:
                sale = Sale.search([('name', '=', name)], limit=1)
                if is_valid(sale):
                    return sale

        return Sale.browse(False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') != '/':
                continue
            picking_type_id = vals.get('picking_type_id')
            if not picking_type_id:
                continue
            sale = self._find_sale_for_sequence(vals)
            if sale:
                picking_type = self.env['stock.picking.type'].browse(picking_type_id)
                sequence = picking_type.sequence_id
                if sequence:
                    vals['name'] = sequence.with_context(
                        sequence_sale_order_id=sale.id
                    ).next_by_id()
        return super().create(vals_list)

    def _do_sap_autofix_name(self):
        for picking in self:
            if not picking.name or picking.name == '/':
                continue
            sale = picking.sale_id
            if not sale or not (sale.do_sap or sale.po_sap):
                continue
            sequence = picking.picking_type_id.sequence_id
            if not sequence:
                continue

            # Suffix yang SEHARUSNYA (dengan sale_id benar)
            _, correct_suffix = sequence.with_context(
                sequence_sale_order_id=sale.id
            )._get_prefix_suffix()
            # Suffix "rusak" (tanpa context sale sama sekali, ini yang
            # kemungkinan besar terpasang saat create() gagal resolve)
            _, broken_suffix = sequence.with_context(
                sequence_sale_order_id=False
            )._get_prefix_suffix()

            if correct_suffix == broken_suffix:
                continue  # tidak ada bedanya, tidak perlu difix

            if picking.name.endswith(broken_suffix):
                base_name = (
                    picking.name[: len(picking.name) - len(broken_suffix)]
                    if broken_suffix else picking.name
                )
                new_name = base_name + correct_suffix
                if new_name != picking.name:
                    picking.with_context(skip_do_sap_autofix=True).write({'name': new_name})

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('skip_do_sap_autofix'):
            if 'sale_id' in vals or 'move_ids' in vals or 'move_line_ids' in vals:
                self._do_sap_autofix_name()
        return res