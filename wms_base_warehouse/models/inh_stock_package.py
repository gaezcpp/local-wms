from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class InhStockPackage(models.Model):
    _inherit = 'stock.package'
    
    pallet_status = fields.Selection([
        ('full_pallet', 'Full Pallet'),
        ('eceran', 'Eceran'),
    ], string="Pallet Status", default=False)
    
    # def write(self, vals):
    #     res = super().write(vals)
    #     for rec in self:
    #         if rec.state in ('UU', 'Blocked'):
    #             if not rec.contained_quant_ids:
    #                 _logger.info(f"State pada {rec.name} otomatis berubah karena tidak ada quants")
    #                 rec.sudo().state = 'QI'
    #     return res
    
    # def _reserved_packages(self):
    #     for rec in self.picking_ids:
    #         if rec.state in ('confirmed', 'assigned'):
    #             raise ValidationError(f"Packages tidak bisa dilakukan perubahan status karena ada Transfer pada {rec.name}")            
    
    # def action_qi(self):
    #     self._reserved_packages()
    #     for rec in self:
    #         if rec.state != 'QI':
    #             rec.state = 'QI'
    
    # def action_blocked(self):
    #     self._reserved_packages()
    #     for rec in self:
    #         if rec.state != 'Blocked':
    #             rec.state = 'Blocked'
    
    # def action_uu(self):
    #     self._reserved_packages()
    #     for rec in self:
    #         if rec.state != 'UU':
    #             rec.state = 'UU'
    
    # def action_unpack_wizard(self):
    #     view = self.env.ref('wms_base_warehouse.unpack_stock_package_view_form')
    #     lines = []
    #     for quant in self.quant_ids:
    #         lines.append((0, 0, {'quant_id': quant.id}))
            
    #     return {
    #         'name': ('Unpack Stock Package'),
    #         'type': 'ir.actions.act_window',
    #         'view_type': 'form',
    #         'view_mode': 'form',
    #         'res_model': 'unpack.stock.package.wizard',
    #         'views': [(view.id, 'form')],
    #         'target': 'new',
    #         'context': {
    #             'default_stock_package_id': self.id,
    #             'default_line_ids': lines,
    #         },
    #     }
    
    # def unpack_by_lines(self, lines, location):
    #     if not lines:
    #         raise ValidationError("Proses unpack gagal, silahkan refresh dan coba lagi!")
    #     if not location:
    #         raise ValidationError("Destination Location belum diisi!")

    #     picking_type = self.env['stock.picking.type'].search([
    #         ('code', '=', 'internal'),
    #         ('sequence_code', '=', 'INT')
    #     ], limit=1)

    #     if not picking_type:
    #         raise ValidationError("Picking type Internal dengan Sequence INT tidak ditemukan")

    #     source_location = self.location_id
    #     if not source_location:
    #         raise ValidationError("Package tidak memiliki location")

    #     picking = self.env['stock.picking'].create({
    #         'partner_id': self.env.user.partner_id.id,
    #         'picking_type_id': picking_type.id,
    #         'location_id': source_location.id,
    #         'location_dest_id': location.id,
    #         'origin': f"UNPACK {self.name}",
    #     })

    #     moves = []
    #     touched_quants = self.env['stock.quant']

    #     for line in lines:
    #         quant = line.quant_id

    #         if quant.package_id != self:
    #             raise ValidationError(f"Quant {quant.display_name} bukan milik package ini")

    #         if line.qty_unpack <= 0:
    #             continue

    #         move_vals = quant._get_inventory_move_values(
    #             line.qty_unpack,
    #             source_location,
    #             location,
    #             quant.package_id,
    #             False,
    #         )

    #         move_vals.update({
    #             'picking_id': picking.id,
    #             'picking_type_id': picking_type.id,
    #             'location_id': source_location.id,
    #             'location_dest_id': location.id,
    #         })

    #         moves.append(move_vals)
    #         touched_quants |= quant

    #     if not moves:
    #         picking.unlink()
    #         return

    #     moves = self.env['stock.move'].create(moves)
    #     picking.action_confirm()
    #     picking.action_assign()
    #     picking.button_validate()
    #     picking.message_post(body=f"Created from Product Packages {self.name or ''} id {self.id or 0}")
    #     touched_quants._quant_tasks()