from odoo import fields, models

class SapCoreApiLog(models.Model):
    _name = "sap.coreapi.log"
    _description = "SAP CoreAPI Request Log"
    _order = "create_date desc"

    request_id = fields.Char(index=True)
    remote_addr = fields.Char(string="Remote Address")
    encrypted_in = fields.Text(string="Encrypted In")
    plaintext_in = fields.Text(string="Plaintext In")
    payload_type = fields.Char(string="Payload Type")
    callback = fields.Char(string="Callback")
    sql_text = fields.Text(string="SQL")
    success = fields.Boolean(default=False)
    error_message = fields.Text()
    response_plaintext = fields.Text(string="Response Plaintext")
    response_encrypted = fields.Text(string="Response Encrypted")

    _sql_constraints = [
        ("unique_request_id", "unique(request_id)", "Request ID must be unique."),
    ]
