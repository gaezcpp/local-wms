/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import BarcodeQuantModel from "@stock_barcode/models/barcode_quant_model";
import { _t } from "@web/core/l10n/translation";

patch(BarcodeQuantModel.prototype, {
    async _processPackage(barcodeData) {
        const recPackage = barcodeData && barcodeData.package;
        if (
            recPackage &&
            recPackage.location_id &&
            (!this.lastScanned.sourceLocation || recPackage.location_id !== this.location.id)
        ) {
            const packageLocation = await this._getOrFetchLocation(recPackage.location_id);
            if (packageLocation) {
                this.location = packageLocation;
            }
        }
        return super._processPackage(...arguments);
    },

    async _getOrFetchLocation(locationId) {
        let location = this.cache.getRecord("stock.location", locationId, false);
        if (location) {
            return location;
        }
        const records = await this.orm.read("stock.location", [locationId], [
            "barcode",
            "display_name",
            "name",
            "parent_path",
            "usage",
        ]);
        if (records && records.length) {
            this.cache.setCache({ "stock.location": records });
            location = this.cache.getRecord("stock.location", locationId, false);
        }
        return location;
    },

    _convertDataToFieldsParams(args) {
        const params = super._convertDataToFieldsParams(...arguments);
        args.product && args.product.uom_bag_id && (params.uom_bag_id = args.product.uom_bag_id);
        return params;
    },

    async updateLine(line, args) {
        await super.updateLine(...arguments);
        if (args.uom_bag_id && !line.uom_bag_id) {
            line.uom_bag_id =
                typeof args.uom_bag_id === "number"
                    ? this.cache.getRecord("uom.uom", args.uom_bag_id, false)
                    : args.uom_bag_id;
        }
    },

    get barcodeInfo() {
        const info = super.barcodeInfo;
        if (
            info.class === "scan_src" &&
            this.groups.group_stock_multi_locations &&
            !this.lastScanned.sourceLocation
        ) {
            return {
                ...info,
                message: this.groups.group_tracking_lot
                    ? _t("Scan a product, a package or a location")
                    : _t("Scan a product or a location"),
            };
        }
        return info;
    },
});
