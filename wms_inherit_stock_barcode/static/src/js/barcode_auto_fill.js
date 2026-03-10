/** @odoo-module **/

import MainComponent from "@stock_barcode/components/main";
import { patch } from "@web/core/utils/patch";

patch(MainComponent.prototype, {

    setup() {
        super.setup(...arguments);

        const context = this.props.action.context || {};
        console.log("AAAAAAAAAAAAAAAA", context)

        this._defaultLocationBarcode = context.default_location_barcode || "";
        this._autoSubmitBarcode = context.auto_submit_barcode || false;
    },

    async onWillStart() {
        await super.onWillStart(...arguments);

        if (this._defaultLocationBarcode) {
            this.env.model.lastScanned = this.env.model.lastScanned || {};

            this.state.barcode = this._defaultLocationBarcode;

            if (this._autoSubmitBarcode) {
                setTimeout(() => {
                    try {
                        this.onBarcodeSubmitted(this._defaultLocationBarcode);
                    } catch (e) {
                        console.warn("Auto barcode submit failed", e);
                    }
                }, 500);
            }
        }
    },

});