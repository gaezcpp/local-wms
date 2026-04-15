/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import MainComponent from "@stock_barcode/components/main";

patch(MainComponent.prototype, {

    setup() {
        super.setup(...arguments);

        if (!this.env.model.isSlocFilled) {
            this.env.model.isSlocFilled = () => {
                return Boolean(
                    this.env.model.record?.data?.sloc_filled
                );
            };
        }

        // existing
        if (!this.env.model.openSlocPackaging) {
            this.env.model.openSlocPackaging = () => {
                return this.env.model._openSlocPackaging();
            };
        }
    },

});