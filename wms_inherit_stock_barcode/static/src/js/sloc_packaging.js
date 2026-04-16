/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import BarcodePickingModel from "@stock_barcode/models/barcode_picking_model";

patch(BarcodePickingModel.prototype, {

    async _openSlocPackaging() {
        console.log("INI SLOC PACKAGING");
        const context = { barcode_view: true };

        const result = await this.orm.call(
            this.resModel,
            "action_open_sloc_packaging_wizard",
            [[this.resId]],
            { context }
        );

        // sama kaya putInPack
        if (typeof result === "object" && result.type) {
            return this.trigger("process-action", result);
        }

        this.trigger("refresh");
    },

});