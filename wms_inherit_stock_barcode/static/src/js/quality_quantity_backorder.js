/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
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
        // Konfirmasi dulu sebelum menjalankan aksi (atribut `confirm` pada template OWL
        // tidak berfungsi — itu hanya untuk button form view backend).
        const confirmed = await new Promise((resolve) => {
            this.dialogService.add(
                ConfirmationDialog,
                {
                    title: _t("Check Quantity"),
                    body: _t("Yakin ingin melakukan Check Quantity?"),
                    confirmLabel: _t("Ya"),
                    cancelLabel: _t("Batal"),
                    confirm: () => resolve(true),
                    cancel: () => resolve(false),
                },
                { onClose: () => resolve(false) }
            );
        });
        if (!confirmed) {
            return;
        }

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

    async _createNewPicking() {
        const selectedLine = this.selectedLine;
        const lineId = selectedLine ? selectedLine.id : null;
        console.log("Processing Create New Picking for line:", lineId);

        const context = {
            barcode_view: true,
            active_line_id: lineId
        };

        const result = await this.orm.call(
            this.resModel,
            "action_open_new_create_picking",
            [[this.resId]],
            { context }
        );

        if (typeof result === "object" && result.type) {
            return this.trigger("process-action", result);
        }

        this.trigger("refresh");
    },

});