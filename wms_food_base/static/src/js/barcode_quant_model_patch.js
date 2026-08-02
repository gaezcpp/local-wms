/** @odoo-module **/

/**
 * FOOD bypass for wms_inherit_stock_barcode/static/src/js/barcode_quant_model_patch.js.
 *
 * See food_barcode_utils.js for why a plain `super.x()` here cannot reach
 * native BarcodeQuantModel behaviour. Both `_processPackage` and
 * `barcodeInfo` are defined directly as own properties on native
 * BarcodeQuantModel.prototype (odoo/addons/stock_barcode/static/src/models/
 * barcode_quant_model.js), so for a FOOD company their native bodies are
 * reimplemented verbatim below instead of relying on `super`, exactly like
 * wms_food_base/static/src/js/barcode_pickimg_model_patch.js does for
 * BarcodePickingModel.
 */

import { patch } from "@web/core/utils/patch";
import BarcodeQuantModel from "@stock_barcode/models/barcode_quant_model";
import { _t } from "@web/core/l10n/translation";
import { isFoodQuantModel } from "@wms_food_base/js/food_barcode_utils";

patch(BarcodeQuantModel.prototype, {
    // Native own property on BarcodeQuantModel.prototype -> reimplemented
    // verbatim (odoo/addons/stock_barcode/static/src/models/barcode_quant_model.js,
    // `async _processPackage(barcodeData)`). No `super.` calls in the native
    // body; every `this.xxx(...)` it calls (orm, cache, updateLine,
    // _createNewLine, _findLine, _convertDataToFieldsParams, ...) is
    // untouched by FEED's patch, so calling them plainly is safe.
    async _processPackage(barcodeData) {
        if (!isFoodQuantModel(this)) {
            return super._processPackage(...arguments);
        }
        const { packageType, packageName } = barcodeData;
        let recPackage = barcodeData.package;
        this.lastScanned.packageId = false;
        if (!recPackage && !packageType && !packageName) {
            return; // No Package data to process.
        }
        const currentLine = this.selectedLine || this.lastScannedLine;
        if (
            currentLine.package_id &&
            packageType &&
            !recPackage &&
            !packageName &&
            currentLine.package_id.id !== packageType
        ) {
            await this.orm.write("stock.package", [currentLine.package_id.id], {
                package_type_id: packageType.id,
            });
            const message = _t("Package type %(type)s applied to the package %(package)s", {
                type: packageType.name,
                package: currentLine.package_id.name,
            });
            barcodeData.stopped = true;
            return this.notification(message, { type: "success" });
        }
        if (!recPackage) {
            if (currentLine && !currentLine.package_id) {
                const valueList = {};
                if (packageName) {
                    valueList.name = packageName;
                }
                if (packageType) {
                    valueList.package_type_id = packageType.id;
                }
                const newPackageData = await this.orm.call(
                    "stock.package",
                    "action_create_from_barcode",
                    [valueList]
                );
                this.cache.setCache(newPackageData);
                recPackage = newPackageData["stock.package"][0];
            }
        }
        if (!recPackage && packageName) {
            const currentLine2 = this.selectedLine || this.lastScannedLine;
            if (currentLine2 && !currentLine2.package_id) {
                const newPackageData = await this.orm.call(
                    "stock.package",
                    "action_create_from_barcode",
                    [{ name: packageName }]
                );
                this.cache.setCache(newPackageData);
                recPackage = newPackageData["stock.package"][0];
            }
        }
        if (!recPackage || (recPackage.location_id && recPackage.location_id != this.location.id)) {
            return;
        }
        const res = await this.orm.call("stock.quant", "get_stock_barcode_data_records", [
            recPackage.contained_quant_ids,
        ]);
        const quants = res.records["stock.quant"];
        if (!quants.length) {
            const currentLine3 = this.selectedLine || this.lastScannedLine;
            if (currentLine3 && !currentLine3.package_id) {
                const fieldsParams = this._convertDataToFieldsParams({
                    package: recPackage,
                });
                await this.updateLine(currentLine3, fieldsParams);
                barcodeData.stopped = true;
                this.selectedLineVirtualId = false;
                this.lastScanned.packageId = recPackage.id;
                this.trigger("update");
            }
            return;
        }
        this.cache.setCache(res.records);

        let alreadyExisting = 0;
        for (const line of this.pageLines) {
            if (
                line.package_id &&
                line.package_id.id === recPackage.id &&
                this.getQtyDone(line) > 0
            ) {
                alreadyExisting++;
            }
        }
        if (alreadyExisting === quants.length) {
            barcodeData.error = _t("This package is already scanned.");
            return;
        }
        for (const quant of quants) {
            const product = this.cache.getRecord("product.product", quant.product_id);
            const searchLineParams = Object.assign({}, barcodeData, { product });
            const foundLine = this._findLine(searchLineParams);
            if (foundLine) {
                const fieldsParams = this._convertDataToFieldsParams({
                    quantity: quant.quantity,
                    lotName: barcodeData.lotName,
                    lot: barcodeData.lot,
                    package: recPackage,
                    owner: barcodeData.owner,
                });
                await this.updateLine(foundLine, fieldsParams);
            } else {
                const fieldsParams = this._convertDataToFieldsParams({
                    product,
                    quantity: quant.quantity,
                    lot: quant.lot_id,
                    package: quant.package_id,
                    owner: quant.owner_id,
                });
                const newLine = await this._createNewLine({ fieldsParams });
                newLine.inventory_quantity = quant.quantity;
            }
        }
        barcodeData.stopped = true;
        this.selectedLineVirtualId = false;
        this.lastScanned.packageId = recPackage.id;
        this.trigger("update");
    },

    // Native own property on BarcodeQuantModel.prototype -> reimplemented
    // verbatim (odoo/addons/stock_barcode/static/src/models/barcode_quant_model.js,
    // `get barcodeInfo()`). No `super.` calls in the native body.
    get barcodeInfo() {
        if (!isFoodQuantModel(this)) {
            return super.barcodeInfo;
        }
        let line = this._getParentLine(this.selectedLine) || this.selectedLine;
        if (!line && this.lastScanned.packageId) {
            line = this.pageLines.find(
                (l) => l.package_id && l.package_id.id === this.lastScanned.packageId
            );
        }
        const messages = {
            scanProduct: {
                class: "scan_product",
                message: _t("Scan a product"),
                icon: "tags",
            },
            scanLot: {
                class: "scan_lot",
                message: _t(
                    "Scan lot numbers for product %s to change their quantity",
                    line ? line.product_id.display_name : ""
                ),
                icon: "barcode",
            },
            scanSerial: {
                class: "scan_serial",
                message: _t(
                    "Scan serial numbers for product %s to change their quantity",
                    line ? line.product_id.display_name : ""
                ),
                icon: "barcode",
            },
        };

        if (line) {
            const { tracking } = line.product_id;
            const trackingNumber = this.getlotName(line);
            if (this._lineIsNotComplete(line)) {
                if (tracking !== "none") {
                    return tracking === "lot" ? messages.scanLot : messages.scanSerial;
                }
                return messages.scanProduct;
            } else if (tracking !== "none" && !trackingNumber) {
                return tracking === "lot" ? messages.scanLot : messages.scanSerial;
            } else {
                if (
                    this.groups.group_stock_multi_locations &&
                    line.location_id.id === this.location.id
                ) {
                    return {
                        class: "scan_product_or_src",
                        message: _t(
                            "Scan more products in %s or scan another location",
                            this.location.display_name
                        ),
                    };
                }
                return messages.scanProduct;
            }
        }
        if (this.groups.group_stock_multi_locations) {
            if (!this.lastScanned.sourceLocation) {
                return {
                    class: "scan_src",
                    message: _t("Scan a location"),
                    icon: "sign-out",
                };
            }
            return {
                class: "scan_product_or_src",
                message: _t(
                    "Scan a product in %s or scan another location",
                    this.location.display_name
                ),
            };
        }
        return messages.scanProduct;
    },
});
