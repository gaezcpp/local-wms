import base64
import io
import logging

import qrcode
from PIL import Image

from odoo import fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class QrPoSap(models.TransientModel):
    _name = 'qr.po.sap'
    _description = 'QR PO SAP Line'

    po_sap_id = fields.Many2one(comodel_name='production.order.sap', string="PO SAP")
    production_line_id = fields.Many2one(comodel_name='production.line', string="Production Line")

    def action_print_qr_line(self):
        self.ensure_one()
        if not self.po_sap_id or not self.production_line_id:
            error_msg = "Data tidak lengkap silahkan refresh halaman!"
            raise ValidationError(error_msg)
        return self.env.ref('wms_production_order_sap.action_report_qr_po_sap_line').report_action(self)

    def _get_qr_image_base64(self):
        self.ensure_one()
        payload = f"{self.po_sap_id.po_number}|{self.production_line_id.code}"
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=16,
            border=2,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")

        logo_data = self.po_sap_id.company_id.logo
        if logo_data:
            try:
                self._paste_logo_on_qr(qr_img, logo_data)
            except Exception:
                _logger.warning("Gagal menempelkan logo company ke QR PO SAP Line", exc_info=True)

        buffer = io.BytesIO()
        qr_img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    @staticmethod
    def _paste_logo_on_qr(qr_img, logo_data):
        logo_img = Image.open(io.BytesIO(base64.b64decode(logo_data))).convert("RGBA")
        qr_width, qr_height = qr_img.size
        logo_size = qr_width // 4
        logo_img.thumbnail((logo_size, logo_size), Image.LANCZOS)
        backing = Image.new("RGBA", (logo_img.width + 12, logo_img.height + 12), "white")
        backing.paste(logo_img, (6, 6), mask=logo_img)
        pos = ((qr_width - backing.width) // 2, (qr_height - backing.height) // 2)
        qr_img.paste(backing, pos, mask=backing)
