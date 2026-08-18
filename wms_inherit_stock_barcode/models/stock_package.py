from odoo import models, fields, api


class InheritStockPackage(models.Model):
    _inherit = 'stock.package'
    
    pallet_status = fields.Selection([
        ('full_pallet', 'Full Pallet'),
        ('eceran', 'Eceran'),
    ], string="Pallet Status", compute="_compute_pallet_status", store=True)
    can_be_use = fields.Boolean(string="Can Be Use", compute="_compute_pallet_status", store=True)
    is_reserved = fields.Boolean(string="Is Reserved", compute='_compute_is_reserved', store=True)
    
    @api.depends('quant_ids')
    def _compute_is_reserved(self):
        for rec in self:
            domain = [
                '|',
                ('package_id', '=', rec.id),
                ('result_package_id', '=', rec.id),
                ('picking_id.picking_type_id.uu_only', '=', True),
                ('state', 'not in', ['done', 'cancel'])
            ]
            move_line_count = self.env['stock.move.line'].sudo().search_count(domain)
            rec.is_reserved = move_line_count > 0
    
    @api.depends('quant_ids.quantity', 'quant_ids.product_id', 'move_line_ids.pallet_qty')
    def _compute_pallet_status(self):
        param = self.env['ir.config_parameter'].sudo().get_param('pembagi_pallet')
        
        try:
            pembagi_pallet = float(param) if param else 0.0
        except ValueError:
            pembagi_pallet = 0.0
        for pkg in self:
            total_pallet_move = sum(pkg.move_line_ids.mapped('pallet_qty'))
            if total_pallet_move >= 1:
                pkg.pallet_status = 'full_pallet'
                pkg.can_be_use = False
                continue

            if pembagi_pallet == 0:
                pkg.pallet_status = False
                pkg.can_be_use = True
                continue

            quants = pkg.quant_ids.filtered(lambda q: q.quantity > 0)
            
            if not quants:
                pkg.pallet_status = False
                pkg.can_be_use = True
                continue

            pallet_status = 'eceran'
            product_ids = quants.mapped('product_id')
            
            if len(product_ids) >= 1:
                quant = quants[0]
                uom_pallet = quant.product_id.product_tmpl_id.uom_pallet_id

                if uom_pallet and quant.quantity:
                    try:
                        result = (uom_pallet.factor / pembagi_pallet) / quant.quantity
                        if abs(result - 1) < 0.00001:
                            pallet_status = 'full_pallet'
                    except ZeroDivisionError:
                        pass
            
            pkg.pallet_status = pallet_status
            pkg.can_be_use = (pallet_status == 'eceran')
            
    @api.model
    def get_last_do_sap(self, package_id):
        if not package_id:
            return False
        line = self.env['stock.move.line'].sudo().search([
            ('package_id', '=', package_id),
            ('state', '=', 'done'),
        ],order='date desc, id desc', limit=1)
        if not line:
            return False
        sale = line.picking_id.sale_id
        no_do = sale.name
        if sale.do_sap:
            no_do = sale.do_sap
        return {
            'do_sap': no_do,
            'picking_name': line.picking_id.name,
            'date': line.date,
        }