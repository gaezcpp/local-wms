from odoo import models, fields, api


class ProductionLineCustom(models.Model):
    _name = 'production.line'
    _description = 'Production Line'
    _rec_name = 'code'
    
    active = fields.Boolean(string="Active", default=True)
    code = fields.Char(string="Code")
    name = fields.Char(string="Name")
    sap_sync = fields.Boolean(string="SAP Sync")
    company_id = fields.Many2one(comodel_name='res.company', string="Company", default=lambda self: self.env.company)
    
    _sql_constraints = [
        (
            "code_uniq",
            "unique (code)",
            "code sudah digunakan",
        )
    ]