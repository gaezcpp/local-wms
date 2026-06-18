/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import BarcodePickingModel from "@stock_barcode/models/barcode_picking_model";
import { _t } from "@web/core/l10n/translation";

patch(BarcodePickingModel.prototype, {

    /**
     * Override getter barcodeInfo untuk memanipulasi pesan UI.
     */
    // get barcodeInfo() {
    //     // 1. Ambil hasil dari fungsi bawaan asli
    //     let info = super.barcodeInfo;

    //     // Jika tidak ada info, kembalikan apa adanya
    //     if (!info) return info;

    //     // 2. Jika sistem mengembalikan state khusus "scan_lot" atau "scan_serial"
    //     if (info.class === "scan_lot" || info.class === "scan_serial") {
    //         info = {
    //             message: _t("Scan the destination location or enter quantity manually"),
    //             class: "scan_product_or_dest",
    //             icon: "sign-in", // Ubah icon barcode menjadi icon masuk/lokasi
    //         };
    //     }

    //     // 3. Bypass hardcode string "Scan a lot number..." di kondisi gabungan
    //     if (info.message) {
    //         // Gunakan String() untuk menghindari error jika message berupa objek Markup (Lazy translation)
    //         const msgStr = String(info.message).toLowerCase();

    //         if (msgStr.includes("lot number") || msgStr.includes("serial number")) {
    //             info.message = _t("Scan a product, enter quantity, or scan the destination location");
    //             info.class = "scan_product_or_dest";
    //         }
    //     }

    //     return info;
    // },

    async _processPackage(barcodeData) {
        const currentLine = this.selectedLine || this.lastScannedLine;
        console.log("_processPackage Bypass Container", barcodeData);

        // 1. Cek apakah line sudah punya result_package
        if (currentLine?.result_package_id) {
            console.info("Destination Pallet sudah dilakukan Scan, melewatkan Destination Container!");
            return { success: true };
        }

        // 2. Cek can_be_use dari package yang di-scan
        const recPackage = barcodeData.package;
        if (recPackage?.id) {
            const result = await this.orm.read(
                'stock.package',
                [recPackage.id],
                ['can_be_use', 'name']
            );

            if (result.length && result[0].can_be_use === false) {
                // Sesuai pola di source asli: this.notification(msg, {type})
                this.notification(
                    _t(`Package ${result[0].name} tidak dapat digunakan karena Full Pallet.`),
                    { type: 'danger' }
                );
                barcodeData.stopped = true;
                return;
            }
        }

        return super._processPackage(...arguments);
    }
});