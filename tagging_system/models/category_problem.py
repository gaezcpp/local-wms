from odoo import models, fields, api

class CategoryProblem(models.Model):
    _name = "category.problem"
    _description = "Category Problem Master"
    _rec_name = "cat_masalah"

    system_id = fields.Many2one(
        "tagging.system",
        string="Sistem",
        required=True,
        ondelete="restrict",
    )

    subsystem_id = fields.Many2one(
        "tagging.subsystem",
        string="Sub Sistem",
        required=True,
        ondelete="restrict",
        domain="[('system_id', '=', system_id)]",
    )

    # opsional (kalau kamu butuh cepat cari/filter berdasarkan code)
    system_code = fields.Char(string="Sys Code", related="system_id.code", store=True, readonly=True)
    subsystem_code = fields.Char(string="Sub Code", related="subsystem_id.code", store=True, readonly=True)

    cat_masalah = fields.Char(string="Category Masalah")
    problem_id = fields.Many2one(comodel_name='tagging.problem', string="Problem", required=True)
    active = fields.Boolean(default=True)
    
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('problem_id'):
                problem = self.env['tagging.problem'].browse(vals['problem_id'])
                vals['cat_masalah'] = problem.name
        res = super(CategoryProblem, self).create(vals_list)
        return res
    
    def write(self, vals):
        if vals.get('problem_id'):
            problem = self.env['tagging.problem'].browse(vals['problem_id'])
            vals['cat_masalah'] = problem.name
            
        return super(CategoryProblem, self).write(vals)
    
    # @api.onchange('problem_id')
    # def _onchange_problem(self):
    #     for rec in self:
    #         if rec.problem_id:
    #             rec.cat_masalah = rec.problem_id.name
    #         else:
    #             rec.cat_masalah = "-"
