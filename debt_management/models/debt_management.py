from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class DebtManagement(models.Model):
    _name = 'debt.management'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Debt Management'
    _rec_name = 'name'
    
    name = fields.Char(string="Name", default="New", tracking=True)
    customer_id = fields.Many2one(comodel_name='debt.customer', string="Debtor", tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('paid', 'Paid')
    ], string="State", default='draft', tracking=True)
    amount = fields.Float(string="Amount")
    paid_amount = fields.Float(string="Paid Amount", tracking=True)
    total_amount = fields.Float(string="Remaining", compute='_compute_total_amount', store=True)
    over_paid_amount = fields.Float(string="Over Paid Amount", tracking=True)
    debt_line_ids = fields.One2many('debt.management.line', 'debt_management_id', ondelete='cascade')
    debt_line_count = fields.Integer(string="Debt Line Count", compute='_compute_debt_line_count')
    notes = fields.Text(string="Notes", tracking=True)
    active = fields.Boolean(string="Active", default=True)
    
    def action_print_pdf(self):
        return self.env.ref('debt_management.action_report_debt_management_pdf').report_action(self)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('debt.management') or _('New')
        res = super().create(vals_list)
        return res
    
    @api.depends('debt_line_ids.amount', 'debt_line_ids.paid_amount')
    def _compute_total_amount(self):
        for rec in self:
            total = 0.0
            for line in rec.debt_line_ids:
                total += max(line.amount - line.paid_amount, 0)
                # if line.paid_amount == 0.0:
                #     line.state = 'in_progress'
                # if line.paid_amount >= 1:
                #     line.state = 'partially_paid'
                # if line.paid_amount >= line.amount:
                #     line.state = 'paid'
            rec.total_amount = total
            
    def _compute_debt_line_count(self):
        for rec in self:
            rec.debt_line_count = self.env['debt.management.line'].search_count([('debt_management_id', '=', self.id)])
            
    def action_smart_button_debt_line(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Debts Line',
            'view_mode': 'list,form',
            'res_model': 'debt.management.line',
            'domain': [('debt_management_id', '=', self.id)],
            'context': {'search_default_gr_ed': 1}
        }
    
    def _validation_document(self):
        for rec in self.debt_line_ids:
            if not rec.debt_type_id:
                raise ValidationError("Type cannot empty!")
            if rec.amount <= 0.0:
                raise ValidationError("Amount cannot less than 0!")
            if not rec.start_date or not rec.end_date:
                raise ValidationError("Start Date or End Date must be filled!")
            if rec.start_date:
                if rec.end_date and rec.end_date < rec.start_date:
                    raise ValidationError("End Date must be greater than Start Date")
                
    def action_distribute_payment(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError("Amount must be greater than 0!")

            remaining_payment = rec.amount

            lines = rec.debt_line_ids.filtered(lambda l: l.state in ('in_progress', 'partially_paid')).sorted(key=lambda l: l.end_date or fields.Date.today())
            for line in lines:
                if remaining_payment <= 0:
                    break

                line_remaining = line.amount - line.paid_amount
                if line_remaining <= 0:
                    continue

                if remaining_payment >= line_remaining:
                    line.paid_amount += line_remaining
                    line.state = 'paid'
                    remaining_payment -= line_remaining
                else:
                    line.paid_amount += remaining_payment
                    line.state = 'partially_paid'
                    remaining_payment = 0

            paid_now = rec.amount - remaining_payment
            rec.paid_amount += paid_now

            # OVER PAID
            if remaining_payment > 0:
                rec.over_paid_amount += remaining_payment

            rec.amount = 0

            all_paid = all(l.state == 'paid' for l in rec.debt_line_ids) if rec.debt_line_ids else False
            if all_paid:
                rec.state = 'paid'
            elif rec.paid_amount > 0:
                rec.state = 'in_progress'
    
    def action_draft(self):
        for rec in self:
            if rec.state == 'in_progress':
                self._validation_document()
                rec.state = 'draft'
            else:
                raise ValidationError(f"State can only set to Draft while the state is In Progress")
    
    def action_in_progress(self):
        for rec in self:
            if rec.state == 'draft':
                self._validation_document()
                rec.state = 'in_progress'
            else:
                raise ValidationError("State can only set to In Progress while the state is Draft")
    
    def action_paid(self):
        for rec in self:
            if rec.state == 'in_progress':
                self._validation_document()
                rec.state = 'paid'
            else:
                raise ValidationError("State can only set to Paid while the state is In Progress")
    
    # def action_open_wizard_pay(self):
    #     self.ensure_one()
    #     view = self.env.ref('debt_management.view_debt_payment_wizard_form')
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'name': 'Update Pay',
    #         'res_model': 'debt.payment.wizard',
    #         'views': [(view.id, 'form')],
    #         'target': 'new',
    #         'context': {
    #             'default_debt_management_id': self.id,
    #             # 'default_picking_type_id': self.picking_type_id.id,
    #             # 'default_line_ids': [(0, 0, {
    #             #     'backorder_wizard_id': 0,
    #             #     'product_id': line.product_id.id,
    #             #     'qty': line.bag_qty,
    #             #     'product_uom_id': line.uom_bag_id.id,
    #             # }) for line in self.move_ids ],
    #             # 'default_is_quality': True,
    #         }
    #     }