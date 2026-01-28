/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BarcodeLine } from "@stock_barcode/components/barcode_line/barcode_line";

patch(BarcodeLine.prototype, {
    get palletQty() {
        if (!this.line.qty_done) return 0;
        return this.line.qty_done / 90;
    },

    get bagQty() {
        if (!this.line.qty_done) return 0;
        return this.line.qty_done / 360;
    },
});
