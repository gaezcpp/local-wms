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
        if (Array.isArray(line?.lines) && line.lines.length) {
            const total = line.lines.reduce(
                (sum, subline) => sum + this._computeSingleBagQty(subline),
                0
            );
            console.log("[WMS-SCANNER][bagQty] computedBagQty:group", {
                autofill_pack_qty: this.env.model.record?.autofill_pack_qty,
                sublines: line.lines.map((l) => ({
                    id: l.id,
                    virtual_id: l.virtual_id,
                    bag_qty: l.bag_qty,
                    quantity: l.quantity,
                    qty_done: l.qty_done,
                    reserved_uom_qty: l.reserved_uom_qty,
                    single: this._computeSingleBagQty(l),
                })),
                total,
            });
            return Math.round(total * 100) / 100;
        }

        return Math.round(this._computeSingleBagQty(line) * 100) / 100;
    },

    get bagUomLabel() {
        const line = this.props.line || this.line;
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
        console.log("[WMS-SCANNER][moveLine] _getBulkGroupLines:candidates", {
            packageId,
            productId,
            candidates: candidates.map((l) => ({
                id: l.id,
                virtual_id: l.virtual_id,
                lot: this._getRelationId(l.lot_id) || l.lot_name || null,
                qty_done: l.qty_done,
                reserved_uom_qty: l.reserved_uom_qty,
            })),
        });
        return candidates;
    },

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
        console.log("[WMS-SCANNER][bulkEntry] openBulkEntry:start", {
            line_id: line && line.id,
            virtual_id: line && line.virtual_id,
            product: this._getRelationId(line && line.product_id),
            package_id: this._getRelationId(line && line.package_id),
            picking_type_code: this.env.model.record && this.env.model.record.picking_type_code,
            bulk_pallet_lot: this.env.model.record && this.env.model.record.bulk_pallet_lot,
        });
        const groupLines = this._getBulkGroupLines(line);
        if (groupLines.length < 2) {
            console.log("[WMS-SCANNER][bulkEntry] openBulkEntry:no-group (need >= 2 sibling lines)", {
                groupLinesCount: groupLines.length,
            });
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

    async _applyBulkBagQty(line, bagQty) {
        console.log("[WMS-SCANNER][moveLine] _applyBulkBagQty:start", {
            id: line && line.id,
            virtual_id: line && line.virtual_id,
            product: this._getRelationId(line && line.product_id),
            lot: this._getRelationId(line && line.lot_id),
            package_id: this._getRelationId(line && line.package_id),
            qty_done_before: line && line.qty_done,
            bagQty,
        });
        line.bag_qty = bagQty;
        const bagUomId = this._getRelationId(line.uom_bag_id);
        const bagUom = bagUomId && this.env.model.cache.getRecord("uom.uom", bagUomId);
        if (bagUom && bagUom.factor) {
            const newQty = bagQty * (bagUom.factor / 1000);
            line.qty_done = newQty;
            line.quantity = newQty;
        }
        if (line.id) {
            const vals = { bag_qty: bagQty };
            if (!bagQty) {
                vals.qty_done = 0;
            }
            await this.env.model.orm.write("stock.move.line", [line.id], vals);
        } else {
            this.env.model._markLineAsDirty(line);
        }
    },
});