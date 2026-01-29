/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Digipad } from "@stock_barcode/widgets/digipad";

patch(Digipad.prototype, {
    _isDebugEnabled() {
        const ctx = this.props.record?.evalContext?.context || {};
        if (ctx.digipad_debug) return true;

        try {
            return window.localStorage.getItem("DIGIPAD_DEBUG") === "1";
        } catch (e) {
            return false;
        }
    },

    _dlog(...args) {
        if (!this._isDebugEnabled()) return;
        console.log("[DIGIPAD_DEBUG]", ...args);
    },

    _dgroup(label, fn) {
        if (!this._isDebugEnabled()) return;
        console.groupCollapsed(`[DIGIPAD_DEBUG] ${label}`);
        try {
            fn();
        } finally {
            console.groupEnd();
        }
    },

    _fmtNum(val) {
        const n = Number(val);
        return Number.isFinite(n) ? n : val;
    },

    async _getUomRelativeFactors() {
        if (!this._uomFactorCache) {
            this._uomFactorCache = new Map();
        }

        const record = this.props.record;
        const data = record.data;

        const bagId = data.uom_bag_id?.id || data.uom_bag_id;
        const palletId = data.uom_pallet_id?.id || data.uom_pallet_id;

        if (!bagId || !palletId) {
            this._dlog("Missing UoM IDs", { bagId, palletId, uom_bag_id: data.uom_bag_id, uom_pallet_id: data.uom_pallet_id });
            return { bagId, palletId, bagFactor: 0, palletFactor: 0 };
        }

        const idsToFetch = [];
        if (!this._uomFactorCache.has(bagId)) idsToFetch.push(bagId);
        if (!this._uomFactorCache.has(palletId)) idsToFetch.push(palletId);

        if (idsToFetch.length) {
            this._dlog("Fetching relative_factor for uom ids:", idsToFetch);
            const rows = await this.orm.searchRead(
                "uom.uom",
                [["id", "in", idsToFetch]],
                ["relative_factor", "name"]
            );
            for (const r of rows) {
                this._uomFactorCache.set(r.id, Number(r.relative_factor || 0));
                this._dlog("UoM fetched:", { id: r.id, name: r.name, relative_factor: r.relative_factor });
            }
        }

        const bagFactor = this._uomFactorCache.get(bagId) || 0;
        const palletFactor = this._uomFactorCache.get(palletId) || 0;

        return { bagId, palletId, bagFactor, palletFactor };
    },

    _checkInputValue() {
        const selector = `div[name="${this.props.fieldToEdit}"] input`;
        const input = document.querySelector(selector);
        if (!input) return;

        const inputValue = input.value;
        if (Number(this.value) !== Number(inputValue)) {
            this.value = inputValue;
            this.quantity = Number(this.value || 0);
        }
    },

    async _increment(interval = 1, enforceQuantity = false) {
        if (enforceQuantity) {
            this.quantity = interval;
        } else {
            this._checkInputValue();
            this.quantity = Math.max(this.quantity + interval, 0);
        }

        this.value = this.quantity.toFixed(this.precision);
        if (parseFloat(this.value) % 1 === 0) {
            this.value = String(Math.floor(parseFloat(this.value)));
        }

        await this._syncBagAndPallet({ reason: "_increment", interval, enforceQuantity });
    },

    async erase() {
        this.quantity = 0;
        this.value = "0";
        await this._syncBagAndPallet({ reason: "erase" });
    },

    async fulfill() {
        this._checkInputValue();
        this.quantity = this.fulfillQuantity;
        this.value = String(this.quantity);
        await this._syncBagAndPallet({ reason: "fulfill" });
    },

    async _syncBagAndPallet(meta = {}) {
        const record = this.props.record;
        const field = this.props.fieldToEdit;

        const before = {
            fieldToEdit: field,
            this_quantity: this._fmtNum(this.quantity),
            this_value: this.value,
            qty_done: this._fmtNum(record.data.qty_done),
            quantity: this._fmtNum(record.data.quantity),
            bag_qty: this._fmtNum(record.data.bag_qty),
            pallet_qty: this._fmtNum(record.data.pallet_qty),
            uom_bag_id: record.data.uom_bag_id,
            uom_pallet_id: record.data.uom_pallet_id,
        };

        this._dgroup(`SYNC start (${meta.reason || "?"})`, () => {
            this._dlog("meta:", meta);
            this._dlog("before record.data:", before);
        });

        await record.update({ [field]: this.quantity });

        const data = record.data;

        let qtyDone = 0;
        if (field === "qty_done" || field === "quantity") {
            qtyDone = Number(this.quantity || 0);
        } else {
            qtyDone = Number(data.qty_done ?? data.quantity ?? 0);
        }

        const { bagId, palletId, bagFactor, palletFactor } = await this._getUomRelativeFactors();

        this._dgroup("Factors & qtyDone", () => {
            this._dlog("qtyDone used:", this._fmtNum(qtyDone));
            this._dlog("bagId/palletId:", { bagId, palletId });
            this._dlog("bagFactor/palletFactor:", { bagFactor, palletFactor });
        });

        if (!bagFactor || !palletFactor) {
            this._dlog("Factor missing => forcing bag_qty & pallet_qty = 0");
            await record.update({ bag_qty: 0, pallet_qty: 0 });

            this._dgroup("SYNC end (factor missing)", () => {
                this._dlog("after record.data:", {
                    qty_done: this._fmtNum(record.data.qty_done),
                    quantity: this._fmtNum(record.data.quantity),
                    bag_qty: this._fmtNum(record.data.bag_qty),
                    pallet_qty: this._fmtNum(record.data.pallet_qty),
                });
            });
            return;
        }

        const bagQty = qtyDone / bagFactor;
        const palletQty = qtyDone / palletFactor;

        this._dgroup("Computed values", () => {
            this._dlog("bagQty = qtyDone / bagFactor", this._fmtNum(qtyDone), "/", this._fmtNum(bagFactor), "=", this._fmtNum(bagQty));
            this._dlog("palletQty = qtyDone / palletFactor", this._fmtNum(qtyDone), "/", this._fmtNum(palletFactor), "=", this._fmtNum(palletQty));
        });

        await record.update({
            bag_qty: bagQty,
            pallet_qty: palletQty,
        });

        this._dgroup("SYNC end (updated)", () => {
            this._dlog("after record.data:", {
                fieldToEdit: field,
                edited_value: this._fmtNum(record.data[field]),
                qty_done: this._fmtNum(record.data.qty_done),
                quantity: this._fmtNum(record.data.quantity),
                bag_qty: this._fmtNum(record.data.bag_qty),
                pallet_qty: this._fmtNum(record.data.pallet_qty),
            });
        });
    },
});
