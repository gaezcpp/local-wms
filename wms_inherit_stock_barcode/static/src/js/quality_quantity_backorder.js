/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import BarcodePickingModel from "@stock_barcode/models/barcode_picking_model";

patch(BarcodePickingModel.prototype, {

    async _openQualityBackorder() {
        // Menggunakan 'this.selectedLine' untuk mendapatkan baris yang sedang aktif/dipilih
        // Kita gunakan optional chaining (?.) untuk mencegah error jika tidak ada baris yang terpilih
        const selectedLine = this.selectedLine;
        const lineId = selectedLine ? selectedLine.id : null;

        console.log("Processing Quality Backorder for line:", lineId);
        
        const context = { 
            barcode_view: true,
            active_line_id: lineId // Mengirim ID ke Python melalui context
        };

        console.log(context)

        const result = await this.orm.call(
            this.resModel,
            "action_open_quality_backorder",
            [[this.resId]],
            { context }
        );

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
            "action_create_quantity_backorder",
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