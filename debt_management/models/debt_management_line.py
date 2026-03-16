from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class DebtManagementLine(models.Model):
    _name = 'debt.management.line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Debt Management line'
    _order = 'end_date asc'
    
    debt_management_id = fields.Many2one(comodel_name='debt.management', string="Debt Management", tracking=True)
    debt_type_id = fields.Many2one(comodel_name='debt.type', string="Type", tracking=True)
    start_date = fields.Date(string="Start Date", default=fields.Date.today(), tracking=True)
    end_date = fields.Date(string="End Date", tracking=True)
    due_days = fields.Char(string="Due Days", compute='_compute_due_days')
    amount = fields.Float(string="Amount", tracking=True)
    partially_paid = fields.Boolean(string="Partial?", default=False, tracking=True)
    paid_amount = fields.Float(string="Paid Amount", tracking=True)
    amount_total = fields.Float(string="Total", compute='_compute_all_total_amount', store=True, tracking=True)
    notes = fields.Text(string="Notes", tracking=True)
    state = fields.Selection([
        ('in_progress', 'In Progress'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid')
    ], string="State", default="in_progress", tracking=True)
    
    def unlink(self):
        if any(self.filtered(lambda debt: debt.state in ('paid', 'partially_paid'))):
            raise ValidationError("You cannot delete a line which is paid or partially paid!")
        return super().unlink()
    
    @api.depends('start_date', 'end_date')
    def _compute_due_days(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                due = (rec.end_date - fields.Date.today()).days
                rec.due_days = f"{due} Days"
            else:
                rec.due_days = "No Due Days"
                
    @api.depends('amount', 'paid_amount')
    def _compute_all_total_amount(self):
        for rec in self:
            rec.amount_total = max(rec.amount - (rec.paid_amount or 0), 0)
                
    def action_paid(self):
        for rec in self:
            if rec.state == 'in_progress':
                pass
            else:
                raise ValidationError("Staus Already Paid!")