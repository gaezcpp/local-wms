from odoo import models, fields, api
from odoo.exceptions import ValidationError
import base64
from io import BytesIO
import xlsxwriter

class PidBeritaAcaraWizard(models.TransientModel):
    _name = 'pid.berita.acara.wizard'
    _description = 'PID Berita Acara Wizard'

    sia_id = fields.Many2one(comodel_name='stock.inventory.adjustment', string="PID")
    remark = fields.Text(string="Remarks")
    file_xlsx = fields.Binary(string="Berita Acara File", readonly=True)
    file_name = fields.Char(string="File Name", readonly=True)

    def _generate_berita_acara_xlsx(self):
        self.ensure_one()

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Berita Acara')

        header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'bg_color': '#D9D9D9',
        })
        cell_format = workbook.add_format({'border': 1})
        number_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})

        headers = [
            'Product', 'Stock Type', 'SLOC',
            'On Hand', 'Count', 'Diff',
            'On Hand Bag', 'Pack Count',
        ]
        for col, title in enumerate(headers):
            sheet.write(0, col, title, header_format)

        row = 1
        for line in self.sia_id.summary_line_ids:
            sheet.write(row, 0, line.product_id.display_name or '', cell_format)
            sheet.write(row, 1, line.stock_type or '', cell_format)
            sheet.write(row, 2, line.sloc_name or '', cell_format)
            sheet.write(row, 3, line.quantity, number_format)
            sheet.write(row, 4, line.inventory_quantity, number_format)
            sheet.write(row, 5, line.inventory_diff_quantity, number_format)
            sheet.write(row, 6, line.bag_qty, number_format)
            sheet.write(row, 7, line.bag_count, number_format)
            row += 1

        column_widths = [30, 12, 12, 12, 12, 12, 14, 12]
        for col, width in enumerate(column_widths):
            sheet.set_column(col, col, width)

        workbook.close()
        output.seek(0)
        data = output.read()
        output.close()
        return data

    def create_berita_acara(self):
        self.ensure_one()

        if not self.sia_id.summary_line_ids:
            raise ValidationError("Tidak ada Summary untuk dibuatkan Berita Acara")
        if self.sia_id.state == 'berita_acara':
            raise ValidationError("File Berita Acara sudah diunduh, silahkan cek tab unduhan browser dan refresh halaman ini!")
        
        xlsx_data = self._generate_berita_acara_xlsx()
        file_name = f"Berita_Acara_{self.sia_id.name}.xlsx"

        self.write({
            'file_xlsx': base64.b64encode(xlsx_data),
            'file_name': file_name,
        })

        self.sia_id.write({'state': 'berita_acara'})
        self.sia_id.message_post(
            body=f"Berita Acara telah dibuat.<br/>Remarks: {self.remark or '-'}"
        )

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/pid.berita.acara.wizard/{self.id}/file_xlsx?download=true&filename={file_name}",
            'target': 'self',
        }