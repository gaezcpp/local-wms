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

    // async _processPackage(barcodeData) {
    //     const currentLine = this.selectedLine || this.lastScannedLine;
    //     console.log("_processPackage Bypass Container", barcodeData);

    //     // 1. Cek apakah line sudah punya result_package
    //     if (currentLine?.result_package_id) {
    //         console.info("Destination Pallet sudah dilakukan Scan, melewatkan Destination Container!");
    //         return { success: true };
    //     }

    //     // 2. Cek can_be_use dari package yang di-scan
    //     const recPackage = barcodeData.package;
    //     if (recPackage?.id) {
    //         const result = await this.orm.read(
    //             'stock.package',
    //             [recPackage.id],
    //             ['can_be_use', 'name']
    //         );

    //         if (result.length && result[0].can_be_use === false) {
    //             // Sesuai pola di source asli: this.notification(msg, {type})
    //             this.notification(
    //                 _t(`Package ${result[0].name} tidak dapat digunakan karena Full Pallet.`),
    //                 { type: 'danger' }
    //             );
    //             barcodeData.stopped = true;
    //             return;
    //         }
    //     }

    //     return super._processPackage(...arguments);
    // }

    async _processBarcode(barcode) {
        console.log("1. _processBarcode Bypass Container Triggered:", barcode);
        
        let lineBeforeScan = this.selectedLine || this.lastScannedLine;
        if (!lineBeforeScan && this.currentState && this.currentState.lines && this.currentState.lines.length > 0) {
            lineBeforeScan = this.currentState.lines[0];
        }

        let oldExpectedLocId = null;
        if (lineBeforeScan && lineBeforeScan.location_dest_id) {
            oldExpectedLocId = typeof lineBeforeScan.location_dest_id === 'object'
                ? (lineBeforeScan.location_dest_id.id || lineBeforeScan.location_dest_id[0])
                : lineBeforeScan.location_dest_id;
        } else if (this.record && this.record.location_dest_id) {
            oldExpectedLocId = typeof this.record.location_dest_id === 'object'
                ? (this.record.location_dest_id.id || this.record.location_dest_id[0])
                : this.record.location_dest_id;
        }

        console.log("-> State AWAL (Sebelum di-update Odoo) - Expected Loc ID:", oldExpectedLocId);

        await super._processBarcode(...arguments);

        const lastScan = this.scanHistory[0];

        if (lastScan && lastScan.destLocation && this.record) {
            const notifLocation = this.record.picking_type_code === 'internal' && this.record.picking_type_entire_packs;

            if (notifLocation) {
                const scannedLocation = lastScan.destLocation;
                
                if (oldExpectedLocId && oldExpectedLocId !== scannedLocation.id) {
                    console.log("6. Kondisi BEDA terpenuhi, memanggil notifikasi dan update suggest_dest_id...");
                    
                    this.notification(
                        _t("Scan lokasi %s tidak sesuai dengan Store To awal. Proses tetap dilanjutkan.", scannedLocation.display_name),
                        {
                            title: _t("Peringatan Lokasi"),
                            type: "warning",
                        }
                    );

                    if (lineBeforeScan && typeof lineBeforeScan.id === 'number') {
                        try {
                            await this.orm.write("stock.move.line", [lineBeforeScan.id], {
                                suggest_dest_id: oldExpectedLocId
                            });
                            console.log("7. Berhasil menyimpan suggest_dest_id:", oldExpectedLocId, "pada Line ID:", lineBeforeScan.id);
                        } catch (error) {
                            console.error("Gagal menyimpan suggest_dest_id ke backend:", error);
                        }
                    } else {
                        console.log("X. Baris belum memiliki ID Real (Virtual ID), lewati update DB.");
                    }
                } else {
                    console.log("6. Kondisi SAMA, tidak ada aksi tambahan.");
                }
            } else {
                console.log("X. Bukan internal atau entire_packs tidak aktif, fungsinya diabaikan.");
            }
        }
    }
});