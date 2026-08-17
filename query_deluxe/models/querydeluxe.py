import io
import csv
import base64
import xlsxwriter
from odoo import api, fields, models, exceptions, _


class QueryDeluxe(models.Model):
    _name = "querydeluxe"
    _description = "PostgreSQL queries from Odoo interface"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "id desc"

    active = fields.Boolean(string="Active", default=True)

    rowcount = fields.Text(string='Rowcount')
    html = fields.Html(string='HTML')

    name = fields.Text(string='Type a query : ', help="Type the query you want to execute.")
    note = fields.Char(string="Note", help="Optional helpful note about the current query, what it does, the dangers, etc...", translate=True)

    def print_result_pdf(self):
        if self:
            self = self.sudo()
            first = self[0]
            return {
                'name': _("Select orientation of the PDF's result"),
                'view_mode': 'form',
                'res_model': 'pdforientation',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'context': {
                    'default_name': first.name,
                    'default_query_id': first.id
                },
            }

    def _get_result_from_query(self, query):
        self = self.sudo()
        headers = []
        datas = []

        if query:
            try:
                self.env.cr.execute(query)
            except Exception as e:
                raise exceptions.UserError(e)

            try:
                if self.env.cr.description:
                    headers = [d[0] for d in self.env.cr.description]
                    datas = self.env.cr.fetchall()
            except Exception as e:
                raise exceptions.UserError(e)

        return headers, datas

    def execute(self):
        for record in self.sudo():
            vals = {
                "rowcount": False,
                "html": False
            }

            if record.name:
                record.message_post(body=str(record.name))

                headers, datas = self._get_result_from_query(record.name)

                rowcount = record.env.cr.rowcount
                vals["rowcount"] = _("{0} row{1} processed").format(rowcount, 's' if 1 < rowcount else '')

                if headers and datas:
                    header_html = "<tr style='background-color: lightgrey'> <th style='background-color:white'/>"
                    header_html += "".join(["<th style='border: 1px solid black'>"+str(header)+"</th>" for header in headers])
                    header_html += "</tr>"

                    body_html = ""
                    i = 0
                    for data in datas:
                        i += 1
                        body_line = "<tr style='background-color: {0}'> <td style='border-right: 3px double; border-bottom: 1px solid black; background-color: yellow'>{1}</td>".format('cyan' if i%2 == 0 else 'white', i)
                        for value in data:
                            display_value = ''
                            if value is not None:
                                display_value = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                            body_line += "<td style='border: 1px solid black'>{0}</td>".format(display_value)
                        body_line += "</tr>"
                        body_html += body_line

                    vals["html"] = """
                    <table style="text-align: center">
                        <thead">
                            {0}
                        </thead>
                        
                        <tbody>
                            {1}
                        </tbody>
                    </table>
                    """.format(header_html, body_html)
            record.update(vals)

    def action_download_csv(self):
        """
        Fungsi untuk mengeksekusi query dan mengunduh hasilnya dalam format CSV.
        """
        # Pastikan hanya satu record yang diproses
        self.ensure_one() 
        
        if not self.name:
            raise exceptions.UserError(_("Tidak ada query yang dieksekusi."))

        # 1. Ambil data dari fungsi bawaan Anda
        headers, datas = self._get_result_from_query(self.name)

        if not headers and not datas:
            raise exceptions.UserError(_("Query tidak menghasilkan data untuk diunduh."))

        # 2. Buat file CSV di dalam memori
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

        # Tulis Header
        if headers:
            writer.writerow(headers)
            
        # Tulis Data (Baris per Baris)
        for data in datas:
            # Ubah nilai None menjadi string kosong agar format CSV rapi
            row = ['' if val is None else str(val) for val in data]
            writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        # 3. Encode data CSV ke format Base64 yang dibutuhkan Odoo Attachment
        csv_base64 = base64.b64encode(csv_content.encode('utf-8'))

        # 4. Buat Attachment di Odoo
        attachment = self.env['ir.attachment'].create({
            'name': 'query_result.csv',
            'type': 'binary',
            'datas': csv_base64,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'text/csv'
        })

        # 5. Kembalikan action URL untuk memicu unduhan di browser
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
        
    def action_download_xlsx(self):
        """
        Fungsi untuk mengeksekusi query dan mengunduh hasilnya dalam format XLSX (Excel).
        """
        # Pastikan hanya satu record yang diproses
        self.ensure_one() 
        
        if not self.name:
            raise exceptions.UserError(_("Tidak ada query yang dieksekusi."))

        # 1. Ambil data dari fungsi bawaan
        headers, datas = self._get_result_from_query(self.name)

        if not headers and not datas:
            raise exceptions.UserError(_("Query tidak menghasilkan data untuk diunduh."))

        # 2. Buat file XLSX di dalam memori
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Query Result')

        # Format untuk Header
        header_format = workbook.add_format({
            'bold': True, 
            'bg_color': '#D3D3D3', 
            'border': 1
        })
        
        # Format untuk data (opsional, untuk border)
        data_format = workbook.add_format({'border': 1})

        # Tulis Header
        if headers:
            for col_num, header_title in enumerate(headers):
                worksheet.write(0, col_num, header_title, header_format)
            
        # Tulis Data (Baris per Baris)
        for row_num, data in enumerate(datas, start=1):
            for col_num, value in enumerate(data):
                # Ubah nilai None menjadi string kosong, selain itu ubah ke string 
                # (Anda juga bisa membiarkan tipe datanya dinamis jika ingin format angka tetap angka)
                display_value = '' if value is None else str(value)
                worksheet.write(row_num, col_num, display_value, data_format)

        # Tutup workbook agar data tertulis ke output buffer
        workbook.close()
        output.seek(0)
        xlsx_content = output.read()
        output.close()

        # 3. Encode data XLSX ke format Base64 yang dibutuhkan Odoo Attachment
        xlsx_base64 = base64.b64encode(xlsx_content)

        # 4. Buat Attachment di Odoo
        attachment = self.env['ir.attachment'].create({
            'name': 'query_result.xlsx',
            'type': 'binary',
            'datas': xlsx_base64,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        # 5. Kembalikan action URL untuk memicu unduhan di browser
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }