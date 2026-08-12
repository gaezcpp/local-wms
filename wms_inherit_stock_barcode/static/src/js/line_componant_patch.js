/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import LineComponent from '@stock_barcode/components/line';
// bulk_entry
import { BulkEntryDialog } from "./bulk_entry_dialog";

patch(LineComponent.prototype, {

    get packagingLabel() {
        const line = this.props.line || this.line;
        const packagingUom = line?.packaging_uom_id;
        const packagingUomId = this._getRelationId(packagingUom);
        const productUomId = this._getRelationId(line?.product_uom_id);
        if (!packagingUomId || packagingUomId === productUomId) {
            return "";
        }
        const kind = line?.order_selection === "gratis" ? _t("Product Gratis") : _t("Order Qty");
        const uomName = (packagingUom && typeof packagingUom === "object") ? packagingUom.name : "";
        return `${kind}: ${line.packaging_uom_qty} ${uomName}`;
    },

    get computedBagQty() {
        const line = this.props.line || this.line;

        // Berlaku untuk package line MAUPUN grouped line (produk+lot sama),
        // keduanya sama-sama punya struktur `.lines` berisi sublines asli.
        if (Array.isArray(line?.lines) && line.lines.length) {
            const total = line.lines.reduce(
                (sum, subline) => sum + this._computeSingleBagQty(subline),
                0
            );
            return Math.round(total * 100) / 100;
        }

        return Math.round(this._computeSingleBagQty(line) * 100) / 100;
    },

    get bagUomLabel() {
        const line = this.props.line || this.line;
        // Kalau grouped/package line, ambil uom_bag_id dari subline pertama
        // (karena parent object sendiri tidak membawa field ini).
        const sourceLine =
            Array.isArray(line?.lines) && line.lines.length ? line.lines[0] : line;
        const bagUomId = this._getRelationId(sourceLine?.uom_bag_id);
        if (!bagUomId) {
            return "";
        }
        const targetUom = this.env.model.cache.getRecord("uom.uom", bagUomId);
        return targetUom?.sap_name || "";
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
        return (qty * sourceUom.factor) / targetUom.factor;
    },

    /** Konversi qty produk (dalam UoM produk) menjadi jumlah bag untuk `line`. */
    _computeBagFromQty(line, qty) {
        const bagUomId = this._getRelationId(line?.uom_bag_id);
        const productUomId = this._getRelationId(line?.product_uom_id);
        if (!bagUomId || !productUomId || !qty) {
            return 0;
        }
        const sourceUom = this.env.model.cache.getRecord("uom.uom", productUomId);
        const targetUom = this.env.model.cache.getRecord("uom.uom", bagUomId);
        if (!sourceUom?.factor || !targetUom?.factor) {
            return 0;
        }
        return (qty * sourceUom.factor) / targetUom.factor;
    },

    _computeSingleBagDemand(line) {
        return this._computeBagFromQty(line, line?.reserved_uom_qty ?? 0);
    },

    get computedBagDemand() {
        const line = this.props.line || this.line;
        if (Array.isArray(line?.lines) && line.lines.length) {
            const total = line.lines.reduce(
                (sum, subline) => sum + this._computeSingleBagDemand(subline),
                0
            );
            return Math.round(total * 100) / 100;
        }
        return Math.round(this._computeSingleBagDemand(line) * 100) / 100;
    },

    get hasBagUom() {
        const line = this.props.line || this.line;
        const sourceLine =
            Array.isArray(line?.lines) && line.lines.length ? line.lines[0] : line;
        return !!this._getRelationId(sourceLine?.uom_bag_id);
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
    },

    // bulk_entry
    get showBulkEntryButton() {
        if (this.props.subline) {
            return false;
        }
        const line = this.props.line || this.line;
        if (!this.env.model.record.bulk_pallet_lot) {
            return false;
        }
        return this._getBulkGroupLines(line).length >= 2;
    },

    /**
     * Returns the sibling move lines sharing the same source package and product as
     * `line` but with different lots (the group the "Bulk Entry" button distributes
     * a total Bag Qty over). Returns an empty array if there is no such group.
     *
     * `line` can either be:
     * - an already-grouped line (native grouping by product_id+location_id put its
     *   sublines into `line.lines`), in which case we just narrow those sublines down
     *   to the ones sharing the same source package;
     * - a plain, ungrouped move line (e.g. grouping disabled for this picking type),
     *   in which case we search `pageLines` for siblings by package_id/product_id.
     *
     * bulk_entry
     */
    _getBulkGroupLines(line) {
        if (!line) {
            return [];
        }
        const packageId = this._getRelationId(line.package_id);
        const productId = this._getRelationId(line.product_id);
        if (!productId) {
            return [];
        }
        let candidates;
        if (Array.isArray(line.lines) && line.lines.length) {
            candidates = line.lines.filter(
                (l) => this._getRelationId(l.package_id) === packageId
            );
        } else {
            if (!packageId) {
                return [];
            }
            candidates = (this.env.model.pageLines || []).filter(
                (l) =>
                    this._getRelationId(l.package_id) === packageId &&
                    this._getRelationId(l.product_id) === productId
            );
        }
        const distinctLots = new Set(
            candidates.map((l) => this._getRelationId(l.lot_id) || l.lot_name || false)
        );
        if (distinctLots.size < 2) {
            return [];
        }
        return candidates;
    },

    /**
     * Batas jumlah bag per line untuk Bulk Entry.
     *
     * Normalnya batasnya adalah demand line (`reserved_uom_qty`). Tapi line hasil
     * scan pallet tidak punya reservasi (`reserved_uom_qty` 0), sehingga totalnya
     * jadi 0 dan angka berapa pun selalu ditolak. Untuk line seperti itu batasnya
     * diambil dari qty fisik quant-nya.
     *
     * Sengaja memakai qty quant, bukan `line.quantity`: kalau memakai qty line,
     * batasnya ikut menyusut setiap kali Bulk Entry dipakai untuk mengurangi qty.
     *
     * bulk_entry
     */
    async _getBulkCapacities(groupLines) {
        let quantByLot = null;
        if (groupLines.some((l) => !l.reserved_uom_qty)) {
            const packageId = this._getRelationId(groupLines[0].package_id);
            const productId = this._getRelationId(groupLines[0].product_id);
            if (packageId && productId) {
                try {
                    const quants = await this.env.model.orm.searchRead(
                        "stock.quant",
                        [
                            ["package_id", "=", packageId],
                            ["product_id", "=", productId],
                        ],
                        ["lot_id", "quantity"]
                    );
                    quantByLot = new Map(
                        quants.map((q) => [q.lot_id ? q.lot_id[0] : false, q.quantity])
                    );
                } catch (error) {
                    console.error("[bulk_entry] gagal membaca quant untuk kapasitas:", error);
                }
            }
        }

        return groupLines.map((l) => {
            let maxBag = Math.floor(this._computeSingleBagDemand(l));
            if (!maxBag && quantByLot) {
                const quantQty = quantByLot.get(this._getRelationId(l.lot_id) || false);
                maxBag = Math.floor(this._computeBagFromQty(l, quantQty));
            }
            return { line: l, maxBag };
        });
    },

    // bulk_entry
    async openBulkEntry(line) {
        const groupLines = this._getBulkGroupLines(line);
        if (groupLines.length < 2) {
            return;
        }
        const capacities = await this._getBulkCapacities(groupLines);
        const totalCapacity = capacities.reduce((sum, c) => sum + c.maxBag, 0);
        console.log(
            "[bulk_entry] kapasitas ::",
            JSON.stringify(
                capacities.map((c) => ({
                    line_id: c.line.id,
                    lot: this._getRelationId(c.line.lot_id),
                    reserved: c.line.reserved_uom_qty,
                    quantity: c.line.quantity,
                    maxBag: c.maxBag,
                }))
            ),
            "total:",
            totalCapacity
        );

        if (!totalCapacity) {
            this.env.model.dialogService.add(ConfirmationDialog, {
                title: _t("Bulk Entry tidak tersedia"),
                body: _t("Tidak ada quantity yang bisa dibagikan pada pallet ini."),
                confirmLabel: _t("OK"),
                confirm: () => {},
                cancel: () => {},
            });
            return;
        }

        this.env.model.dialogService.add(BulkEntryDialog, {
            title: _t("Bulk Entry - Isi Total Bag Qty"),
            maxQty: totalCapacity,
            productName: groupLines[0]?.product_id?.display_name || "",
            packageName: groupLines[0]?.package_id?.name || "",
            onConfirm: async (totalBagQty) => {
                const qty = Math.floor(Number(totalBagQty) || 0);
                if (qty <= 0) {
                    return;
                }
                // if (qty > totalCapacity) {
                //     this.env.model.dialogService.add(ConfirmationDialog, {
                //         title: _t("Quantity Melebihi Batas"),
                //         body: _t(
                //             "Total Bag Qty (%s) melebihi total Quantity yang tersedia (%s) pada package ini.",
                //             qty,
                //             totalCapacity
                //         ),
                //         confirmLabel: _t("OK"),
                //         confirm: () => {},
                //         cancel: () => {},
                //     });
                //     return;
                // }
                let remaining = qty;
                for (const c of capacities) {
                    const assign = Math.min(remaining, c.maxBag);
                    remaining -= assign;
                    await this._applyBulkBagQty(c.line, assign);
                }
                this.env.model.trigger("update");
            },
        });
    },

    /**
     * Writes `bag_qty` (and locally mirrors the resulting `qty_done`, using the same
     * `bag_qty * (uom_bag.factor / 1000)` formula as the server's `_sync_qty_from_bag`)
     * on a single sibling line as part of a Bulk Entry distribution.
     *
     * bulk_entry
     */
    async _applyBulkBagQty(line, bagQty) {
        line.bag_qty = bagQty;
        const bagUomId = this._getRelationId(line.uom_bag_id);
        const bagUom = bagUomId && this.env.model.cache.getRecord("uom.uom", bagUomId);
        if (bagUom && bagUom.factor) {
            const newQty = bagQty * (bagUom.factor / 1000);
            line.qty_done = newQty;
            // `quantity` wajib ikut diperbarui: `_computeSingleBagQty()` membaca
            // `line.quantity ?? line.qty_done`, jadi begitu line sudah tersimpan
            // (punya `quantity`), memperbarui `qty_done` saja tidak mengubah
            // angka BAG yang tampil. Di server nilainya juga selaras — inverse
            // `qty_done` menulis `quantity` lewat `_sync_qty_from_bag()`.
            line.quantity = newQty;
        }
        if (line.id) {
            // Persist directly (no `save()` first): calling `save()` would flush any
            // other pending dirty lines via `refreshCache()`/`_createState()`, which
            // rebuilds `currentState.lines` with brand-new objects and would detach
            // the `line` reference captured above from the live state.
            const vals = { bag_qty: bagQty };
            if (!bagQty) {
                // `_sync_qty_from_bag()` berhenti pada `if not bag_qty: return`,
                // sehingga bag_qty 0 tidak pernah menurunkan qty di server. Kirim
                // `qty_done` eksplisit supaya line yang tidak kebagian jatah benar-
                // benar menjadi 0, bukan hanya di layar. (`qty_done` adalah dummy
                // field ber-inverse, yang menulis `quantity`.)
                vals.qty_done = 0;
            }
            await this.env.model.orm.write("stock.move.line", [line.id], vals);
        } else {
            this.env.model._markLineAsDirty(line);
        }
    },
});