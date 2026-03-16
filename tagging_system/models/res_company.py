from odoo import models, fields

class ResCompany(models.Model):
    _inherit = "res.company"

    company_code = fields.Char(string="Company Code", copy=False, index=True)
    _sql_constraints = [
        ("res_company_company_code_uniq", "unique(company_code)", "Company Code must be unique."),
    ]