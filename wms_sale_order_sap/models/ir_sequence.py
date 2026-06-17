from odoo import models, fields, api


class InheritIrSequence(models.Model):
    _inherit = 'ir.sequence'
    
    def _get_prefix_suffix(self, date=None, date_range=None):
        prefix, suffix = super()._get_prefix_suffix(date=date, date_range=date_range)
        
        sale_id = self.env.context.get('sequence_sale_order_id')
        if not sale_id and self.env.context.get('active_model') == 'sale.order':
             sale_id = self.env.context.get('active_id')

        if not sale_id:
            return prefix, suffix
        
        sale = self.env['sale.order'].browse(sale_id)
        if not sale.exists():
            return prefix, suffix
        
        replacements = {
            '{do_sap}': sale.do_sap or '',
            '{po_sap}': sale.po_sap or '',
        }
        
        for placeholder, value in replacements.items():
            if placeholder in prefix:
                prefix = prefix.replace(placeholder, value)
            if placeholder in suffix:
                suffix = suffix.replace(placeholder, value)
        
        return prefix, suffix