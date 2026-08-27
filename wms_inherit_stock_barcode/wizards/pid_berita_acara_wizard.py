from odoo import models, fields, api
from odoo.exceptions import ValidationError
import base64
from io import BytesIO
import xlsxwriter

BULAN_ID = [
    'JANUARI', 'FEBRUARI', 'MARET', 'APRIL', 'MEI', 'JUNI',
    'JULI', 'AGUSTUS', 'SEPTEMBER', 'OKTOBER', 'NOVEMBER', 'DESEMBER',
]


class PidBeritaAcaraWizard(models.TransientModel):
    _name = 'pid.berita.acara.wizard'
    _description = 'PID Berita Acara Wizard'

    sia_id = fields.Many2one(comodel_name='stock.inventory.adjustment', string="PID")
    remark = fields.Text(string="Remarks")
    file_xlsx = fields.Binary(string="Berita Acara File", readonly=True)
    file_name = fields.Char(string="File Name", readonly=True)

    def _get_berita_acara_header(self):
        """Nilai-nilai header Berita Acara yang bisa diturunkan dari record PID."""
        self.ensure_one()
        sia = self.sia_id

        tanggal = jam = ''
        periode = ''
        if sia.date_time:
            dt = fields.Datetime.context_timestamp(self, sia.date_time)
            bulan = BULAN_ID[dt.month - 1]
            tanggal = f"{dt.day} {bulan} {dt.year}"
            periode = f"{bulan} {dt.year}"
            jam = f"{dt.strftime('%H.%M')} - SELESAI"

        uom_name = ''
        uom = sia.summary_line_ids.mapped('uom_id')[:1]
        if uom:
            uom_name = (uom.name or '').upper()

        return {
            'name': sia.name,
            'company': (sia.company_id.name or '').upper(),
            'city': (sia.company_id.city or '').upper(),
            'periode': periode,
            'tanggal': tanggal,
            'jam': jam,
            'gudang': (sia.location_id.complete_name or '').upper(),
            'satuan': f"FG {uom_name}".strip(),
            'uom_name': uom_name,
        }

    def _generate_berita_acara_xlsx(self):
        self.ensure_one()

        info = self._get_berita_acara_header()

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Berita Acara')

        # -- Formats -------------------------------------------------------
        fmt_company = workbook.add_format({'bold': True, 'valign': 'vcenter'})
        fmt_title = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter'})
        fmt_info = workbook.add_format({'valign': 'vcenter'})
        fmt_label = workbook.add_format({'bold': True, 'valign': 'vcenter'})
        fmt_group = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 2})
        fmt_head = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 2})
        fmt_code = workbook.add_format({'valign': 'vcenter', 'left': 2, 'right': 1,})
        fmt_num = workbook.add_format({'valign': 'vcenter', 'border': 1, 'num_format': '#,##0;(#,##0)',})
        fmt_num_bag = workbook.add_format({'valign': 'vcenter', 'border': 1, 'num_format': '#,##0.0;(#,##0.0)'})
        fmt_note = workbook.add_format({'valign': 'vcenter', 'left': 1, 'right': 2})
        fmt_total_label = workbook.add_format({
            'bold': True, 'valign': 'vcenter', 'left': 2, 'right': 1,
            'top': 2, 'bottom': 2,
        })
        fmt_total_num = workbook.add_format({
            'bold': True, 'valign': 'vcenter', 'border': 1,
            'top': 2, 'bottom': 2, 'num_format': '#,##0;(#,##0)',
        })
        fmt_total_bag = workbook.add_format({
            'bold': True, 'valign': 'vcenter', 'border': 1,
            'top': 2, 'bottom': 2, 'num_format': '#,##0.0;(#,##0.0)',
        })
        fmt_total_note = workbook.add_format({
            'valign': 'vcenter', 'left': 1, 'right': 2, 'top': 2, 'bottom': 2,
        })
        fmt_blank = workbook.add_format({'left': 2})
        fmt_blank_end = workbook.add_format({'right': 2})

        # -- Column layout (A dipakai sebagai margin kiri) -----------------
        sheet.set_column(0, 0, 2)      # A
        sheet.set_column(1, 1, 40)     # B - KODE
        sheet.set_column(2, 7, 14)     # C..H - STOCK / FISIK / SELISIH
        sheet.set_column(8, 8, 60)     # I - KETERANGAN

        # -- Kop surat -----------------------------------------------------
        sheet.write(0, 1, info['company'], fmt_company)
        sheet.write(1, 1, info['city'], fmt_company)

        sheet.merge_range(2, 1, 2, 8, info['name'], fmt_title)
        sheet.merge_range(3, 1, 3, 8, 'BERITA ACARA PEMERIKSAAN BARANG', fmt_title)
        sheet.merge_range(4, 1, 4, 8, info['periode'], fmt_title)

        sheet.write(5, 8, f"TANGGAL : {info['tanggal']}", fmt_info)
        sheet.write(6, 8, f"JAM : {info['jam']}", fmt_info)

        sheet.write(6, 1, info['gudang'], fmt_label)

        # -- Header tabel (2 baris) ----------------------------------------
        head_row = 7
        sub_row = 8

        sheet.write(head_row, 1, info['satuan'], fmt_label)
        sheet.merge_range(head_row, 2, head_row, 3, 'STOCK', fmt_group)
        sheet.merge_range(head_row, 4, head_row, 5, 'FISIK', fmt_group)
        sheet.merge_range(head_row, 6, head_row, 7, 'SELISIH', fmt_group)
        sheet.write(head_row, 8, 'SATUAN', fmt_info)

        sub_headers = [
            (1, 'KODE'), (2, 'BAG'), (3, 'KG'), (4, 'BAG'),
            (5, 'KG'), (6, 'BAG'), (7, 'KG'), (8, 'KETERANGAN'),
        ]
        for col, title in sub_headers:
            sheet.write(sub_row, col, title, fmt_head)

        # -- Baris data ----------------------------------------------------
        row = sub_row + 1
        first_data_row = row
        total_stock_bag = total_stock_kg = 0.0
        total_fisik_bag = total_fisik_kg = 0.0
        total_selisih_bag = total_selisih_kg = 0.0

        for line in self.sia_id.summary_line_ids:
            selisih_bag = round((line.bag_count or 0.0) - (line.bag_qty or 0.0), 4)

            sheet.write(row, 1, line.product_id.default_code or line.product_id.display_name or '', fmt_code)
            sheet.write_number(row, 2, line.bag_qty or 0.0, fmt_num)
            sheet.write_number(row, 3, line.quantity or 0.0, fmt_num)
            sheet.write_number(row, 4, line.bag_count or 0.0, fmt_num)
            sheet.write_number(row, 5, line.inventory_quantity or 0.0, fmt_num)
            sheet.write_number(row, 6, selisih_bag, fmt_num_bag)
            sheet.write_number(row, 7, line.inventory_diff_quantity or 0.0, fmt_num)
            sheet.write(row, 8, '', fmt_note)

            total_stock_bag += line.bag_qty or 0.0
            total_stock_kg += line.quantity or 0.0
            total_fisik_bag += line.bag_count or 0.0
            total_fisik_kg += line.inventory_quantity or 0.0
            total_selisih_bag += selisih_bag
            total_selisih_kg += line.inventory_diff_quantity or 0.0
            row += 1

        last_data_row = row - 1

        # -- Baris kosong pemisah + TOTAL ----------------------------------
        sheet.write_blank(row, 1, None, fmt_blank)
        sheet.write_blank(row, 8, None, fmt_blank_end)
        row += 1

        sheet.write(row, 1, 'TOTAL', fmt_total_label)
        sheet.write_number(row, 2, total_stock_bag, fmt_total_num)
        sheet.write_number(row, 3, total_stock_kg, fmt_total_num)
        sheet.write_number(row, 4, total_fisik_bag, fmt_total_num)
        sheet.write_number(row, 5, total_fisik_kg, fmt_total_num)
        sheet.write_number(row, 6, round(total_selisih_bag, 4), fmt_total_bag)
        sheet.write_number(row, 7, total_selisih_kg, fmt_total_num)
        sheet.write_blank(row, 8, None, fmt_total_note)

        if last_data_row >= first_data_row:
            sheet.autofilter(sub_row, 1, last_data_row, 8)
        sheet.freeze_panes(first_data_row, 0)

        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(head_row, sub_row)

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