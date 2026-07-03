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
        
        do_sap_value = sale.do_sap.strip() if sale.do_sap else ''
        po_sap_value = sale.po_sap.strip() if sale.po_sap else ''
        naming = do_sap_value if do_sap_value else po_sap_value
        replacements = {
            '{do_sap}': naming or '',
        }
        
        for placeholder, value in replacements.items():
            if placeholder in prefix:
                prefix = prefix.replace(placeholder, value)
            if placeholder in suffix:
                suffix = suffix.replace(placeholder, value)
        
        return prefix, suffix