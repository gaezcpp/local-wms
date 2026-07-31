/** @odoo-module **/

/**
 * FOOD bypass for wms_inherit_stock_barcode/static/src/js/digipad_patch.js.
 *
 * Digipad is rendered as a `view_widgets` field widget inside the barcode
 * line's product-selector FORM VIEW (stock_move_line_product_selector), not
 * under MainComponent's `useSubEnv({model, ...})`, so `env.model` is not
 * reliably reachable here (see food_barcode_utils.js). Its `wms_type`
 * detection instead reads `this.props.record.data.wms_type`, which is
 * already plumbed: Phase 3 added
 * `<field name="wms_type" invisible="1"/>` to that exact view in
 * wms_food_base/views/stock_move_line_barcode_views.xml, and that view
 * ALSO restores this widget's own visibility for FOOD (native digipad is
 * shown only for FOOD; FEED replaces it with its own bag/pallet qty
 * fields+buttons and keeps this div always invisible) -- meaning Digipad
 * genuinely renders, and therefore genuinely runs, for FOOD companies, so
 * its patched methods must be bypassed here.
 *
 * Every method wms_inherit_stock_barcode overrides here IS defined as an
 * own property on native `Digipad.prototype`
 * (odoo/addons/stock_barcode/static/src/widgets/digipad.js), so (per
 * food_barcode_utils.js) `super.x()` from this second patch() call cannot
 * reach it; native bodies are reimplemented verbatim below.
 *
 * NOT bypassed (no `patch()` entry added), with justification:
 *   - `_hasField`, `_getUomRelativeFactors`: FEED-only helpers with no
 *     native equivalent, only ever called from FEED's own
 *     `_syncBagAndPallet`, which itself is only ever called from FEED's own
 *     `_increment`/`erase`/`fulfill` bodies. Since those three entry points
 *     are bypassed to pure native bodies below (which never call
 *     `_syncBagAndPallet`), none of these helpers are reachable anymore for
 *     a FOOD company.
 */

import { patch } from "@web/core/utils/patch";
import { Digipad } from "@stock_barcode/widgets/digipad";
import { isFoodFormRecord } from "@wms_food_base/js/food_barcode_utils";

patch(Digipad.prototype, {
    // Native own property -> reimplemented verbatim.
    _checkInputValue() {
        if (!isFoodFormRecord(this.props.record)) {
            return super._checkInputValue(...arguments);
        }
        const input = document.querySelector(`div[name="${this.props.fieldToEdit}"] input`);
        const inputValue = input.value;
        if (Number(this.value) != Number(inputValue)) {
            this.value = inputValue;
            this.quantity = Number(this.value || 0);
        }
    },

    // Native own property -> reimplemented verbatim.
    async _increment(interval = 1, enforceQuantity = false) {
        if (!isFoodFormRecord(this.props.record)) {
            return super._increment(...arguments);
        }
        if (enforceQuantity) {
            this.quantity = interval;
        } else {
            this._checkInputValue();
            this.quantity = Math.max(this.quantity + interval, 0);
        }
        this.value = this.quantity.toFixed(this.precision);
        if (parseFloat(this.value) % 1 == 0) {
            this.value = String(Math.floor(parseFloat(this.value)));
        }
        await this.props.record.update(this.changes);
    },

    // Native own property -> reimplemented verbatim.
    erase() {
        if (!isFoodFormRecord(this.props.record)) {
            return super.erase(...arguments);
        }
        this._checkInputValue();
        this.quantity = 0;
        this.value = String(this.quantity);
        this.props.record.update(this.changes);
    },

    // Native own property -> reimplemented verbatim.
    fulfill() {
        if (!isFoodFormRecord(this.props.record)) {
            return super.fulfill(...arguments);
        }
        this._checkInputValue();
        this.quantity = this.fulfillQuantity;
        this.value = String(this.quantity);
        this.props.record.update(this.changes);
    },
});
