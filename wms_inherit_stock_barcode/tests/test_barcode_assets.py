from pathlib import Path

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wms_barcode_assets')
class TestBarcodeAssets(TransactionCase):

    def test_bag_demand_supports_non_picking_barcode_models(self):
        source = (
            Path(__file__).parents[1]
            / 'static'
            / 'src'
            / 'js'
            / 'line_componant_patch.js'
        ).read_text(encoding='utf-8')

        self.assertIn('getScannedPackageQty?.(line)', source)
