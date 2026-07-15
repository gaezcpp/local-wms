/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import LineComponent from '@stock_barcode/components/line';

patch(LineComponent.prototype, {

    get computedBagQty() {
        const line = this.props.line || this.line;
        if (line?.isPackageLine && Array.isArray(line.lines)) {
            const total = line.lines.reduce(
                (sum, subline) => sum + this._computeSingleBagQty(subline),
                0
            );
            return Math.round(total * 100) / 100;
        }
        return Math.round(this._computeSingleBagQty(line) * 100) / 100;
    },

    _getRelationId(value) {
        if (value && typeof value === "object") {
            return value.id;
        }
        return value || false;
    },

    _computeSingleBagQty(line) {
        const bagUomId = this._getRelationId(line?.uom_bag_id);
        const productUomId = this._getRelationId(line?.product_uom_id);
        if (!bagUomId || !productUomId) {
            return 0;
        }
        if (!this.env.model.record.autofill_pack_qty) {
            return line.bag_qty || 0;
        }
        const sourceUom = this.env.model.cache.getRecord("uom.uom", productUomId);
        const targetUom = this.env.model.cache.getRecord("uom.uom", bagUomId);
        if (!sourceUom?.factor || !targetUom?.factor) {
            return 0;
        }
        const qty = line.quantity ?? line.qty_done ?? 0;

        // qty_bag = (qty * source.factor) / target.factor
        return (qty * sourceUom.factor) / targetUom.factor;
    },

    // Gajadi dipake ini
    async duplicateProductLine(line) {
        const model = this.env.model;

        // 1. BUAT IDENTITAS BARU YANG UNIK
        // Virtual ID harus unik agar Odoo tidak menganggapnya sebagai baris yang sama.
        const newVirtualId = 'DUP-' + Math.random().toString(36).substr(2, 9);

        // 2. CLONE BARIS DARI BARIS ASAL
        // Menggunakan spread operator (...) untuk menyalin relasi move_id, picking_id, dsb.
        const newLine = {
            ...line,
            // Identitas Baru
            id: false,
            virtual_id: newVirtualId,
            dummy_id: newVirtualId,

            // RESET Kuantitas & Bypass Lot
            qty_done: 0,
            quantity: 0,
            lot_id: false,
            lot_name: "AUTO-GENERATE", // Bypass frontend lot

            // Hapus Relasi Package agar baris benar-benar fresh
            package_id: false,
            result_package_id: false,

            // Reset field custom UoM Anda
            bag_qty: 0,
            pallet_qty: 0,
            bag_dummy_qty: 0,
        };

        // 3. SUNTIKKAN KE STATE
        if (model.currentState && model.currentState.lines) {
            model.currentState.lines.push(newLine);
        }

        // 4. MENCEGAH GROUPING (PENTING!)
        // Memaksa model untuk membuang cache grouping lama agar baris baru tidak digabung
        model._groupedLines = null;

        // 5. SET FOKUS & UPDATE UI
        model.nextExpected = 'destination_location';

        if (typeof model.trigger === 'function') {
            model.trigger('update');
        }
    }
});