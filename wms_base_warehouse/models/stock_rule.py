from odoo import models, fields, api


class StockRule(models.Model):
    _inherit = 'stock.rule'

    # prepare stock.move dari sale.order
    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_id, name, origin, company_id, values):
        move_values = super(StockRule, self)._get_stock_move_values(product_id, product_qty, product_uom, location_id, name, origin, company_id, values)
        
        if values.get('sap_sequence'):
            move_values['sap_seq'] = values.get('sap_sequence')
        if values.get('order_seq'):
            move_values['order_seq'] = values.get('order_seq')
        if values.get('order_selection'):
            move_values['order_selection'] = values.get('order_selection')
            
        return move_values