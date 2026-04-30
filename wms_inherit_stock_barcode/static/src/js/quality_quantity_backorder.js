/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import BarcodePickingModel from "@stock_barcode/models/barcode_picking_model";

patch(BarcodePickingModel.prototype, {

    async _openQualityBackorder() {
        console.log("INI openQualityBackorder");
        const context = { barcode_view: true };

        const result = await this.orm.call(
            this.resModel,
            "action_open_quality_backorder",
            [[this.resId]],
            { context }
        );

        // sama kaya putInPack
        if (typeof result === "object" && result.type) {
            return this.trigger("process-action", result);
        }

        this.trigger("refresh");
    },

    async _openQuantityBackorder() {
        console.log("INI openQuantityBackorder");
        const context = { barcode_view: true };

        const result = await this.orm.call(
            this.resModel,
            "action_open_quantity_backorder",
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