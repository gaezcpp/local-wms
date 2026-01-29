from odoo import models, fields, api


class InheritStockMove(models.Model):
    _inherit = 'stock.move'

    bag_qty = fields.Float(string="Bag Qty", compute="_compute_bag_pallet_from_lines", store=True, tracking=True)
    pallet_qty = fields.Float(string="Pallet Qty", compute="_compute_bag_pallet_from_lines", store=True, tracking=True)
    uom_bag_id = fields.Many2one('uom.uom', compute="_compute_bag_pallet_from_lines", store=True, tracking=True)
    uom_pallet_id = fields.Many2one('uom.uom', compute="_compute_bag_pallet_from_lines", store=True, tracking=True)

    def _get_fields_stock_barcode(self):
        res = super()._get_fields_stock_barcode()
        return res + [
            'bag_qty',
            'pallet_qty',
            'uom_bag_id',
            'uom_pallet_id',
        ]

    @api.depends('move_line_ids.bag_qty', 'move_line_ids.pallet_qty', 'move_line_ids.uom_bag_id', 'move_line_ids.uom_pallet_id', 'move_line_ids.quantity', 'move_line_ids.picked',)
    def _compute_bag_pallet_from_lines(self):
        for move in self:
            bag = 0.0
            pallet = 0.0
            uom_bag = False
            uom_pallet = False

            for line in move.move_line_ids:
                if not line.picked:
                    continue

                bag += line.bag_qty or 0.0
                pallet += line.pallet_qty or 0.0

                if not uom_bag and line.uom_bag_id:
                    uom_bag = line.uom_bag_id
                if not uom_pallet and line.uom_pallet_id:
                    uom_pallet = line.uom_pallet_id

            move.bag_qty = bag
            move.pallet_qty = pallet
            move.uom_bag_id = uom_bag
            move.uom_pallet_id = uom_pallet
