/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Digipad } from "@stock_barcode/widgets/digipad";

patch(Digipad.prototype, {
    
    _hasField(field) {
        return !!this.props.record?.model?.config?.fields?.[field];
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
            return { bagId, palletId, bagFactor: 0, palletFactor: 0 };
        }

        const idsToFetch = [];
        if (!this._uomFactorCache.has(bagId)) idsToFetch.push(bagId);
        if (!this._uomFactorCache.has(palletId)) idsToFetch.push(palletId);

        if (idsToFetch.length) {
            const rows = await this.orm.searchRead(
                "uom.uom",
                [["id", "in", idsToFetch]],
                ["relative_factor", "name"]
            );
            for (const r of rows) {
                this._uomFactorCache.set(r.id, Number(r.relative_factor || 0));
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
        await record.update({ [field]: this.quantity });

        const data = record.data;

        let baseQty = 0;
        if (field === "qty_done" || field === "quantity" || field === "inventory_quantity") {
            baseQty = Number(this.quantity || 0);
        } else {
            baseQty = Number(
                data.qty_done ??
                data.quantity ??
                data.inventory_quantity ??
                0
            );
        }

        const { bagFactor, palletFactor } = await this._getUomRelativeFactors();

        const hasBagQty = this._hasField("bag_qty");
        const hasPalletQty = this._hasField("pallet_qty");
        const hasBagDummy = this._hasField("bag_dummy_qty");

        if (!bagFactor) {
            const zeroChanges = {};
            if (hasBagQty) zeroChanges.bag_qty = 0;
            if (hasPalletQty) zeroChanges.pallet_qty = 0;
            if (hasBagDummy) zeroChanges.bag_dummy_qty = 0;
            if (Object.keys(zeroChanges).length) {
                await record.update(zeroChanges);
            }
            return;
        }

        const bagQty = baseQty / bagFactor;
        const changes = {};
        if (hasBagQty) {
            changes.bag_qty = bagQty;
        }
        if (hasBagDummy) {
            changes.bag_dummy_qty = bagQty;
        }
        if (palletFactor && hasPalletQty) {
            changes.pallet_qty = baseQty / palletFactor;
        }
        if (Object.keys(changes).length) {
            await record.update(changes);
        }
    },
});

// versi chatgpt
// patch(Digipad.prototype, {
//     _hasField(field) {
//         return !!this.props.record?.model?.config?.fields?.[field];
//     },

//     async _getUomRelativeFactors() {
//         if (!this._uomFactorCache) {
//             this._uomFactorCache = new Map();
//         }

//         const record = this.props.record;
//         const data = record.data;

//         const bagId = data.uom_bag_id?.id || data.uom_bag_id;
//         const palletId = data.uom_pallet_id?.id || data.uom_pallet_id;

//         if (!bagId || !palletId) {
//             return { bagId, palletId, bagFactor: 0, palletFactor: 0 };
//         }

//         const idsToFetch = [];
//         if (!this._uomFactorCache.has(bagId)) idsToFetch.push(bagId);
//         if (!this._uomFactorCache.has(palletId)) idsToFetch.push(palletId);

//         if (idsToFetch.length) {
//             const rows = await this.orm.searchRead(
//                 "uom.uom",
//                 [["id", "in", idsToFetch]],
//                 ["relative_factor"]
//             );
//             for (const r of rows) {
//                 this._uomFactorCache.set(r.id, Number(r.relative_factor || 0));
//             }
//         }

//         const bagFactor = this._uomFactorCache.get(bagId) || 0;
//         const palletFactor = this._uomFactorCache.get(palletId) || 0;

//         return { bagId, palletId, bagFactor, palletFactor };
//     },

//     async _increment(interval = 1, enforceQuantity = false) {
//         if (enforceQuantity) {
//             this.quantity = interval;
//         } else {
//             this.quantity = Math.max((this.quantity || 0) + interval, 0);
//         }

//         this.value = this.quantity.toFixed(this.precision);
//         if (parseFloat(this.value) % 1 === 0) {
//             this.value = String(Math.floor(parseFloat(this.value)));
//         }

//         await this._syncBagAndPallet();
//     },

//     async erase() {
//         this.quantity = 0;
//         this.value = "0";
//         await this._syncBagAndPallet();
//     },

//     async fulfill() {
//         this.quantity = this.fulfillQuantity;
//         this.value = String(this.quantity);
//         await this._syncBagAndPallet();
//     },

//     async _syncBagAndPallet() {
//         const record = this.props.record;
//         const field = this.props.fieldToEdit;

//         await record.update({ [field]: this.quantity });

//         const data = record.data;

//         let baseQty = 0;
//         if (field === "qty_done" || field === "quantity" || field === "inventory_quantity") {
//             baseQty = Number(this.quantity || 0);
//         } else {
//             baseQty = Number(
//                 data.qty_done ??
//                 data.quantity ??
//                 data.inventory_quantity ??
//                 0
//             );
//         }

//         const { bagFactor, palletFactor } = await this._getUomRelativeFactors();

//         const hasBagQty = this._hasField("bag_qty");
//         const hasPalletQty = this._hasField("pallet_qty");
//         const hasBagDummy = this._hasField("bag_dummy_qty");

//         if (!bagFactor) {
//             const zeroChanges = {};
//             if (hasBagQty) zeroChanges.bag_qty = 0;
//             if (hasPalletQty) zeroChanges.pallet_qty = 0;
//             if (hasBagDummy) zeroChanges.bag_dummy_qty = 0;
//             if (Object.keys(zeroChanges).length) {
//                 await record.update(zeroChanges);
//             }
//             return;
//         }

//         const bagQty = baseQty / bagFactor;
//         const changes = {};

//         if (hasBagQty) {
//             changes.bag_qty = bagQty;
//         }
//         if (hasBagDummy) {
//             changes.bag_dummy_qty = bagQty;
//         }
//         if (palletFactor && hasPalletQty) {
//             changes.pallet_qty = baseQty / palletFactor;
//         }

//         if (Object.keys(changes).length) {
//             await record.update(changes);
//         }
//     },
// });