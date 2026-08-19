/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import BarcodePickingModel from "@stock_barcode/models/barcode_picking_model";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(BarcodePickingModel.prototype, {
    get validWipProductIds() {
        const lines = this.currentState?.lines || [];
        const line = lines.find((l) => Array.isArray(l.valid_wip_product_ids));
        return line ? line.valid_wip_product_ids : false;
    },

    _checkBarcode(barcodeData) {
        const check = super._checkBarcode(...arguments);
        const product = barcodeData.product;
        if (check.error || !product || !this.record.production_only) {
            return check;
        }
        const validProductIds = this.validWipProductIds;
        if (!validProductIds || validProductIds.includes(product.id)) {
            return check;
        }
        check.title = _t("Scan Ditolak!");
        check.message = validProductIds.length
            ? _t(
                  "Product %s tidak terdaftar pada family SKU",
                  product.display_name
              )
            : _t(
                  "Tidak ada family SKU yang valid untuk transfer ini. Pastikan PO SAP sudah diisi dan product-nya memiliki memiliki family SKU."
              );
        check.error = true;
        this.wipBlockedMessage = check.message;
        return check;
    },

    notification(message, options = {}) {
        if (this.wipBlockedMessage && this.wipBlockedMessage === message) {
            this.wipBlockedMessage = false;
            return this.dialogService.add(AlertDialog, {
                title: options.title,
                body: message,
            });
        }
        return super.notification(...arguments);
    },
});
