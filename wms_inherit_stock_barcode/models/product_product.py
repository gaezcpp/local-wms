from odoo import api, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _get_fields_stock_barcode(self):
        """Kirim UoM bag/pallet produk ke client Barcode.

        `stock.move.line.uom_bag_id` / `uom_pallet_id` adalah field related ke
        produk, jadi nilainya baru ada setelah line tersimpan di server. Line
        yang dibentuk sepenuhnya di client oleh `_createNewLine()` -- yang
        terjadi pada setiap scan pallet di dokumen yang belum punya
        `stock.move.line` sama sekali, mis. Split QTY Pallet (P2P) yang
        picking-nya dibuat kosong -- karena itu tidak punya keduanya sampai
        operasi ditutup (save lewat `beforeQuit()`) dan dibuka lagi.

        Dengan kedua field ini ikut di record produk, client bisa mengisinya
        sendiri saat line dibentuk (lihat `_getNewLineDefaultValues()` di
        static/src/js/barcode_pickimg_model_patch.js), sehingga qty langsung
        tampil dalam UoM bag dan Bulk Entry bisa menghitung kapasitasnya.
        """
        res = super()._get_fields_stock_barcode()
        for field in ('uom_bag_id', 'uom_pallet_id'):
            if field not in res:
                res.append(field)
        return res
