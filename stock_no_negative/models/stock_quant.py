# Copyright 2015-2017 Akretion (http://www.akretion.com)
# @author Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.tools import config, float_compare

_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def _wms_negqty_debug_dump(self, quant):
        """[WMS-NEGQTY] Dump semua move.line non-done yang menyentuh
        product+lot+location quant ini, supaya kelihatan siapa yang
        over-reserve/over-process sebelum quant ini jadi minus."""
        lines = self.env['stock.move.line'].sudo().search([
            ('product_id', '=', quant.product_id.id),
            ('location_id', '=', quant.location_id.id),
            ('lot_id', '=', quant.lot_id.id if quant.lot_id else False),
        ], order='write_date desc', limit=50)

        for line in lines:
            move = line.move_id
            picking = line.picking_id
            _logger.info(
                "[WMS-NEGQTY] TRACE line=%s move=%s state=%s picking=%s(id=%s) "
                "picking_type=%s(id=%s) qty=%s demand=%s bag_qty=%s lot=%s "
                "package=%s result_package=%s sale=%s origin=%s write_date=%s",
                line.id, move.id, line.state,
                picking.name, picking.id,
                picking.picking_type_id.name, picking.picking_type_id.id,
                line.quantity, move.product_uom_qty, line.bag_qty,
                quant.lot_id.name if quant.lot_id else False,
                line.package_id.name if line.package_id else False,
                line.result_package_id.name if line.result_package_id else False,
                move.sale_line_id.order_id.name if move.sale_line_id else False,
                picking.origin,
                line.write_date,
            )

    @api.constrains("product_id", "quantity")
    def check_negative_qty(self):
        # To provide an option to skip the check when necessary.
        if self.env.context.get("skip_negative_qty_check"):
            return

        p = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        check_negative_qty = (
            config["test_enable"] and self.env.context.get("test_stock_no_negative")
        ) or not config["test_enable"]
        if not check_negative_qty:
            return

        for quant in self:
            disallowed_by_product = (
                not quant.product_id.allow_negative_stock
                and not quant.product_id.categ_id.allow_negative_stock
            )
            disallowed_by_location = not quant.location_id.allow_negative_stock
            if (
                float_compare(quant.quantity, 0, precision_digits=p) == -1
                and quant.product_id.is_storable
                and quant.location_id.usage in ["internal", "transit"]
                and disallowed_by_product
                and disallowed_by_location
            ):
                _logger.info(
                    "[WMS-NEGQTY] RAISE product=%s(id=%s) lot=%s location=%s(id=%s) "
                    "quantity=%s reserved_quantity=%s package=%s",
                    quant.product_id.display_name, quant.product_id.id,
                    quant.lot_id.name if quant.lot_id else False,
                    quant.location_id.complete_name, quant.location_id.id,
                    quant.quantity, quant.reserved_quantity,
                    quant.package_id.name if quant.package_id else False,
                )
                self._wms_negqty_debug_dump(quant)

                msg_add = ""
                if quant.lot_id:
                    msg_add = self.env._(
                        " lot %(name)s", name=quant.lot_id.display_name
                    )

                raise ValidationError(
                    self.env._(
                        "You cannot validate this stock operation because the "
                        "stock level of the product '%(name)s' %(name_lot)s would "
                        "become negative (%(q_quantity)s) on the stock location "
                        "'%(complete_name)s' and negative stock is not allowed "
                        "for this product and/or location.",
                        name=quant.product_id.display_name,
                        name_lot=msg_add,
                        q_quantity=quant.quantity,
                        complete_name=quant.location_id.complete_name,
                    )
                )
