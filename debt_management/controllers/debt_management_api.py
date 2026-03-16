from odoo import http
from odoo.http import request, content_disposition
from odoo.exceptions import ValidationError
from .handle_response import handle_response
import json

class DebtManagementAPI(http.Controller):
    
    def _show_popup(self, message):
        html = f"""
            <script>
                alert("{message.replace('"', '\\"').replace('\n', ' ')}");
                window.history.back();
            </script>
        """
        return request.make_response(html, headers=[('Content-Type', 'text/html')])
    
    def _redirect_new_tab(self, url):
        html = f"""
            <script>
                window.open("{url}", "_blank");
                window.history.back();
            </script>
        """
        return request.make_response(html, headers=[('Content-Type', 'text/html')])
    
    @http.route('/api/get/debt-line-details', type='http', auth='public', methods=['GET'], csrf=False)
    def get_debt_line_details(self, user=None):
        x_odoo_database = request.httprequest.headers.get('X-Odoo-Database')
        if not x_odoo_database:
            raise ValidationError("X-Odoo-Database needed!")
        if not user:
            raise ValidationError("Parameter User needed!")
        
        data = []
        try:
            with request.env.cr.savepoint():
                debt_list = request.env['debt.management.line'].sudo().search([('create_uid', '=', int(user))])
                for debt in debt_list:
                    data.append({
                        'debt_management_id': debt.debt_management_id.name,
                        'debt_type_id': debt.debt_type_id.name,
                        'start_date': debt.start_date.strftime("%d-%m-%Y"),
                        'end_date': debt.end_date.strftime("%d-%m-%Y"),
                        'due_days': debt.due_days,
                        'amount': debt.amount,
                        'paid_amount': debt.paid_amount,
                        'amount_total': debt.amount_total,
                        'notes': debt.notes,
                        'state': debt.state,
                    })
                
        except Exception as e:
            return handle_response(False, str(e))
        
        return handle_response(
            success=True,
            message="Successfully",
            data=data,
        )
        