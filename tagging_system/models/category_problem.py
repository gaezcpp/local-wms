from odoo import models, fields

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
    system_code = fields.Char(related="system_id.code", store=True, readonly=True)
    subsystem_code = fields.Char(related="subsystem_id.code", store=True, readonly=True)

    cat_masalah = fields.Char(string="Category Masalah", required=True)
    active = fields.Boolean(default=True)
