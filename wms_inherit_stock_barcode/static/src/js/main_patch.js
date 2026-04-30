/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import MainComponent from "@stock_barcode/components/main";

patch(MainComponent.prototype, {

    setup() {
        super.setup(...arguments);
        console.log("INI MAIN PATCH");

        if (!this.env.model.isSlocFilled) {
            this.env.model.isSlocFilled = () => {
                return Boolean(
                    this.env.model.record?.data?.sloc_filled
                );
            };
        }

        if (!this.env.model.isProductionOnly) {
            this.env.model.isProductionOnly = () => {
                // Gunakan opsional chaining (?) untuk menghindari error jika record sedang kosong
                return Boolean(this.env.model.record?.production_only);
            };
        }

        if (!this.env.model.isCheckerOnly) {
            this.env.model.isCheckerOnly = () => {
                // Gunakan opsional chaining (?) untuk menghindari error jika record sedang kosong
                return Boolean(this.env.model.record?.checker_only);
            };
        }

        // existing
        if (!this.env.model.openQualityBackorder) {
            this.env.model.openQualityBackorder = () => {
                return this.env.model._openQualityBackorder();
            };
        }

        if (!this.env.model.openQuantityBackorder) {
            this.env.model.openQuantityBackorder = () => {
                return this.env.model._openQuantityBackorder();
            };
        }
    },

});