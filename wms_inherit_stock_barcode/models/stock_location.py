from odoo import models, fields, api
from collections import defaultdict


class InheritStockLocation(models.Model):
    _inherit = 'stock.location'
    
    def _get_putaway_strategy(self,product,quantity=0,package=None,packaging=None,additional_qty=None):
        self = self._check_access_putaway()
        products = self.env.context.get('products', self.env['product.product'])
        products |= product
        print("PUTAWAY STRATEGY KEPANGGIL")

        package_type = self.env['stock.package.type']
        if package:
            package_type = package.package_type_id
        elif packaging:
            package_type = packaging.package_type_id

        categ = products.categ_id if len(products.categ_id) == 1 else self.env['product.category']
        categs = categ
        while categ.parent_id:
            categ = categ.parent_id
            categs |= categ

        putaway_rules = self.putaway_rule_ids.filtered(lambda rule:
            (not rule.product_id or rule.product_id in products)
            and (not rule.category_id or rule.category_id in categs)
            and (not rule.package_type_ids or package_type in rule.package_type_ids)
            and (not rule.pallet_status or not package or rule.pallet_status == package.pallet_status)
        )
        print(f"XXXXXXXXXXXXXXXXXXXXXXX {putaway_rules}")

        putaway_rules = putaway_rules.sorted(
            lambda rule: (
                bool(rule.package_type_ids),
                bool(rule.product_id),
                bool(rule.category_id == categs[:1]),
                bool(rule.category_id),
            ),
            reverse=True,
        )
        print(f"DDDDDDDDDDDDDDDDDDDDDD {putaway_rules}")
        putaway_location = None
        locations = self.env.context.get("locations")
        if not locations:
            locations = self.child_internal_location_ids
        # if putaway_rules:
        #     putaway_location = putaway_rules._get_putaway_location(
        #         product,
        #         quantity,
        #         package,
        #         packaging,
        #         {}
        #     )
        if putaway_rules:
            # get current product qty (qty in current quants and future qty on assigned ml) of all child locations
            qty_by_location = defaultdict(lambda: 0)
            if locations.storage_category_id:
                if package and package.package_type_id:
                    move_line_data = self.env['stock.move.line']._read_group([
                        ('id', 'not in', list(self.env.context.get('exclude_sml_ids', set()))),
                        ('result_package_id.package_type_id', '=', package_type.id),
                        ('state', 'not in', ['draft', 'cancel', 'done']),
                    ], ['location_dest_id'], ['result_package_id:count_distinct'])
                    quant_data = self.env['stock.quant']._read_group([
                        ('package_id.package_type_id', '=', package_type.id),
                        ('location_id', 'in', locations.ids),
                    ], ['location_id'], ['package_id:count_distinct'])
                    qty_by_location.update({location_dest.id: count for location_dest, count in move_line_data})
                    for location, count in quant_data:
                        qty_by_location[location.id] += count
                else:
                    move_line_data = self.env['stock.move.line']._read_group([
                        ('id', 'not in', list(self.env.context.get('exclude_sml_ids', set()))),
                        ('product_id', '=', product.id),
                        ('location_dest_id', 'in', locations.ids),
                        ('state', 'not in', ['draft', 'done', 'cancel'])
                    ], ['location_dest_id'], ['quantity:array_agg', 'product_uom_id:recordset'])
                    quant_data = self.env['stock.quant']._read_group([
                        ('product_id', '=', product.id),
                        ('location_id', 'in', locations.ids),
                    ], ['location_id'], ['quantity:sum'])

                    qty_by_location.update({location.id: quantity_sum for location, quantity_sum in quant_data})
                    for location_dest, quantity_list, uoms in move_line_data:
                        current_qty = sum(ml_uom._compute_quantity(float(qty), product.uom_id) for qty, ml_uom in zip(quantity_list, uoms))
                        qty_by_location[location_dest.id] += current_qty

            if additional_qty:
                for location_id, qty in additional_qty.items():
                    qty_by_location[location_id] += qty
            putaway_location = putaway_rules._get_putaway_location(product, quantity, package, packaging, qty_by_location)

        if not putaway_location:
            putaway_location = locations[0] if locations and self.usage == 'view' else self

        return putaway_location