from odoo import models, fields, api


class StockPackageAFT(models.Model):
    _inherit = 'stock.package'
    
    aft_count = fields.Integer(string="AFT Count", compute='_compute_aft_count')
    block_action_id = fields.Many2one(comodel_name='action.quality.packages', string="Block Action")
    
    def _compute_aft_count(self):
        domain = [('package_id', 'in', self.ids)]
        groups = self.env['quality.packages.summary.line'].sudo()._read_group(
            domain=domain,
            groupby=['package_id'],
            aggregates=['__count'],
        )
        count_map = {package.id: count for package, count in groups}
        for rec in self:
            rec.aft_count = count_map.get(rec.id, 0)
            
    def action_summary_aft(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Summary AFT',
            'view_mode': 'list,form',
            'res_model': 'quality.packages.summary.line',
            'domain': [('package_id', '=', self.id)],
            'context': {
                'create': 0,
                'edit': 0,
                'delete': 0,
                'duplicate': 0,
            }
        }