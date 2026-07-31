/** @odoo-module **/

/**
 * FOOD bypass for wms_inherit_stock_barcode/static/src/js/barcode_pickimg_model_patch.js.
 *
 * See food_barcode_utils.js for why a plain `super.x()` here cannot reach
 * native BarcodePickingModel behaviour and why native bodies are
 * reimplemented verbatim below for every method/getter that native Odoo
 * itself defines as an own property on BarcodePickingModel.prototype
 * (`pageLines`, `packageLines`, `barcodeInfo`, `_getFieldToWrite`,
 * `_createCommandVals`, `_processPackage`, `_processBarcode`,
 * `_updateLineQty`). For the few keys FEED overrides that native
 * BarcodePickingModel does NOT itself redefine (`_createState`,
 * `groupedLines`, `_getSaveLineCommand` -- all only defined on the
 * `BarcodeModel` ancestor, never patched), we call straight into that
 * untouched ancestor prototype instead of duplicating its body.
 *
 * NOT bypassed here (left running FEED's body unconditionally, i.e. no
 * `patch()` entry added at all), with justification:
 *   - `checkBarcode`: dead code. Nothing in this codebase (native or
 *     custom) ever calls `model.checkBarcode(...)` -- the real native hook
 *     used by MainComponent is `processBarcode(barcode, options)`. Native
 *     Odoo has no `checkBarcode` method anywhere, so FEED's own
 *     `super.checkBarcode(...)` inside it is itself unreachable/would
 *     throw if this method were ever actually invoked. Bypassing it would
 *     be pointless (no native behaviour exists to bypass to) and risks
 *     masking the fact that it's dead code that should probably be removed
 *     from wms_inherit_stock_barcode.
 *   - `_snapshotStockTypeQty`, `_enforceUUStockType`,
 *     `_notifyStockTypeBlocked`, `_getSourceStockType`,
 *     `_getPackageStockType`, `_findProductionLineByCode`,
 *     `_lineAwaitingProductionLine`, `_setProductionLineOnLine`,
 *     `_cleanupPackageSplitRemainder`: these are FEED-only helpers with no
 *     native equivalent, only ever called from within FEED's own bodies of
 *     `_processBarcode`/`_processPackage`/`_updateLineQty`/`barcodeInfo`.
 *     Since those entry points are bypassed to pure native behaviour below,
 *     none of these helpers are reachable anymore for a FOOD company, so
 *     there is nothing left to bypass.
 */

import { patch } from "@web/core/utils/patch";
import BarcodePickingModel from "@stock_barcode/models/barcode_picking_model";
import { _t } from "@web/core/l10n/translation";
import { Deferred } from "@web/core/utils/concurrency";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { isFoodModel, getNativeAncestorPrototype } from "@wms_food_base/js/food_barcode_utils";

// BarcodeModel.prototype: the ancestor class, never patched by
// wms_inherit_stock_barcode, so its methods/getters below are guaranteed
// pristine native Odoo behaviour.
const BASE_PROTO = getNativeAncestorPrototype(BarcodePickingModel);

patch(BarcodePickingModel.prototype, {
    // Only defined on BarcodeModel.prototype natively -> ancestor call.
    _createState() {
        if (isFoodModel(this)) {
            return BASE_PROTO._createState.call(this);
        }
        return super._createState();
    },

    // Native own property on BarcodePickingModel.prototype -> reimplemented.
    get pageLines() {
        if (isFoodModel(this)) {
            let lines = Reflect.get(BASE_PROTO, "pageLines", this);
            if (this._moveEntirePackage()) {
                lines = lines.filter(
                    (line) => !(line.package_id && line.result_package_id && line.is_entire_pack)
                );
            }
            return this._sortLine(lines);
        }
        return super.pageLines;
    },

    // Only defined on BarcodeModel.prototype natively -> ancestor call.
    get groupedLines() {
        if (isFoodModel(this)) {
            return Reflect.get(BASE_PROTO, "groupedLines", this);
        }
        return super.groupedLines;
    },

    // Native own property on BarcodePickingModel.prototype -> reimplemented.
    get packageLines() {
        if (isFoodModel(this)) {
            if (!this._moveEntirePackage() || !this.currentState.lines.length) {
                return [];
            }
            return this._getPackageLines();
        }
        return super.packageLines;
    },

    // Native own property on BarcodePickingModel.prototype -> reimplemented
    // verbatim (odoo/addons/stock_barcode/static/src/models/barcode_picking_model.js,
    // `get barcodeInfo()`). No `super.` calls in the native body.
    get barcodeInfo() {
        if (!isFoodModel(this)) {
            return super.barcodeInfo;
        }
        if (this.isCancelled || this.isDone) {
            return {
                class: this.isDone ? "picking_already_done" : "picking_already_cancelled",
                message: this.isDone
                    ? _t("This picking is already done")
                    : _t("This picking is cancelled"),
                icon: "exclamation-triangle",
                warning: true,
            };
        }
        const parentLine = this._getParentLine(this.selectedLine);
        const line = parentLine && this.getQtyDemand(parentLine) ? parentLine : this.selectedLine;
        const infos = {
            scanScrLoc: {
                message:
                    this.considerPackageLines && !this.config.restrict_scan_source_location
                        ? _t("Scan the source location or a package")
                        : _t("Scan the source location"),
                class: "scan_src",
                icon: "sign-out",
            },
            scanDestLoc: {
                message: _t("Scan the destination location"),
                class: "scan_dest",
                icon: "sign-in",
            },
            scanProductOrDestLoc: {
                message: this.considerPackageLines
                    ? _t("Scan a product, a package or the destination location.")
                    : _t("Scan a product or the destination location."),
                class: "scan_product_or_dest",
            },
            scanPackage: {
                message: this._getScanPackageMessage(line),
                class: "scan_package",
                icon: "archive",
            },
            scanLot: {
                message: _t("Scan a lot number"),
                class: "scan_lot",
                icon: "barcode",
            },
            scanSerial: {
                message: _t("Scan a serial number"),
                class: "scan_serial",
                icon: "barcode",
            },
            pressValidateBtn: {
                message: _t("Press Validate or scan another product"),
                class: "scan_validate",
                icon: "check-square",
            },
        };
        let barcodeInfo = {
            message: _t("Scan a product"),
            class: "scan_product",
            icon: "tags",
        };
        if ((line || this.lastScanned.packageId) && this.groups.group_stock_multi_locations) {
            if (this.record.picking_type_code === "outgoing" && this.useScanSourceLocation) {
                barcodeInfo = {
                    message: _t("Scan more products, or scan a new source location"),
                    class: "scan_product_or_src",
                };
            } else if (this.config.restrict_scan_dest_location != "no") {
                barcodeInfo = infos.scanProductOrDestLoc;
            }
        }

        if (!line && this._moveEntirePackage()) {
            const packageLine = this.selectedPackageLine;
            if (packageLine) {
                if (this._lineIsComplete(packageLine)) {
                    if (
                        this.config.restrict_scan_source_location &&
                        !this.lastScanned.sourceLocation
                    ) {
                        return infos.scanScrLoc;
                    } else if (
                        this.config.restrict_scan_dest_location != "no" &&
                        !this.lastScanned.destLocation
                    ) {
                        return this.config.restrict_scan_dest_location == "mandatory"
                            ? infos.scanDestLoc
                            : infos.scanProductOrDestLoc;
                    } else if (this.pageIsDone) {
                        return infos.pressValidateBtn;
                    } else {
                        barcodeInfo.message = _t("Scan a product or another package");
                        barcodeInfo.class = "scan_product_or_package";
                    }
                } else {
                    barcodeInfo.message = _t(
                        "Scan the package %s",
                        packageLine.result_package_id.name
                    );
                    barcodeInfo.icon = "archive";
                }
                return barcodeInfo;
            } else if (this.considerPackageLines && barcodeInfo.class == "scan_product") {
                barcodeInfo.message = _t("Scan a product or a package");
                barcodeInfo.class = "scan_product_or_package";
            }
        }
        if (
            barcodeInfo.class === "scan_product" &&
            !(line || this.lastScanned.packageId) &&
            this.config.restrict_scan_source_location &&
            this.lastScanned.sourceLocation
        ) {
            barcodeInfo.message = _t(
                "Scan a product from %s",
                this.lastScanned.sourceLocation.name
            );
        }

        if (this.useScanSourceLocation) {
            if (!this.lastScanned.sourceLocation && !this.pageIsDone) {
                return infos.scanScrLoc;
            } else if (
                this.lastScanned.sourceLocation &&
                this.lastScanned.destLocation == "no" &&
                line &&
                this._lineIsComplete(line)
            ) {
                if (this.config.restrict_put_in_pack === "mandatory" && !line.result_package_id) {
                    return {
                        message: _t("Scan a package"),
                        class: "scan_package",
                        icon: "archive",
                    };
                }
                return infos.scanScrLoc;
            }
        }

        if (!line) {
            if (this.pageIsDone) {
                return infos.pressValidateBtn;
            } else if (this.config.lines_need_to_be_packed) {
                const lines = new Array(...this.pageLines, ...this.packageLines);
                if (
                    lines.every((l) => !this._lineIsNotComplete(l)) &&
                    lines.some((l) => this._lineNeedsToBePacked(l))
                ) {
                    return infos.scanPackage;
                }
            }
            return barcodeInfo;
        }
        const product = line.product_id;

        if (
            product.tracking !== "none" &&
            (this.record.picking_type_id.use_create_lots ||
                this.record.picking_type_id.use_existing_lots)
        ) {
            const isLot = product.tracking === "lot";
            if (this.getQtyDemand(line) && (line.lot_id || line.lot_name)) {
                if (this.getQtyDone(line) === 0) {
                    return isLot ? infos.scanLot : infos.scanSerial;
                } else if (this.getQtyDone(line) < this.getQtyDemand(line)) {
                    barcodeInfo = isLot ? infos.scanLot : infos.scanSerial;
                    barcodeInfo.message = isLot
                        ? _t("Scan more lot numbers")
                        : _t("Scan another serial number");
                    return barcodeInfo;
                }
            } else if (!(line.lot_id || line.lot_name)) {
                return isLot ? infos.scanLot : infos.scanSerial;
            }
        }

        if (this._lineNeedsToBePacked(line)) {
            if (this._lineIsComplete(line)) {
                return infos.scanPackage;
            }
            if (product.tracking == "serial") {
                barcodeInfo.message = _t("Scan a serial number or a package");
            } else if (product.tracking == "lot") {
                barcodeInfo.message =
                    line.qty_done == 0
                        ? _t("Scan a lot number")
                        : _t("Scan more lot numbers or a package");
                barcodeInfo.class = "scan_lot";
            } else {
                barcodeInfo.message = _t("Scan more products or a package");
            }
            return barcodeInfo;
        }

        if (this.pageIsDone) {
            barcodeInfo = infos.pressValidateBtn;
        }

        const lineWaitingPackage =
            this.groups.group_tracking_lot &&
            this.config.restrict_put_in_pack != "no" &&
            !line.result_package_id;
        if (this.config.restrict_scan_dest_location != "no" && line.qty_done) {
            if (this.pageIsDone) {
                if (this.lastScanned.destLocation) {
                    return infos.pressValidateBtn;
                } else {
                    return this.config.restrict_scan_dest_location == "mandatory" &&
                        this._lineIsComplete(line)
                        ? infos.scanDestLoc
                        : infos.scanProductOrDestLoc;
                }
            } else if (this._lineIsComplete(line)) {
                if (lineWaitingPackage) {
                    barcodeInfo.message =
                        this.config.restrict_scan_dest_location == "mandatory"
                            ? _t("Scan a package or the destination location")
                            : _t("Scan a package, the destination location or another product");
                } else {
                    return this.config.restrict_scan_dest_location == "mandatory"
                        ? infos.scanDestLoc
                        : infos.scanProductOrDestLoc;
                }
            } else {
                barcodeInfo = infos.scanProductOrDestLoc;
                if (product.tracking == "serial") {
                    barcodeInfo.message = lineWaitingPackage
                        ? _t("Scan a serial number or a package then the destination location")
                        : _t("Scan a serial number then the destination location");
                } else if (product.tracking == "lot") {
                    barcodeInfo.message = lineWaitingPackage
                        ? _t("Scan a lot number or a packages then the destination location")
                        : _t("Scan a lot number then the destination location");
                } else {
                    barcodeInfo.message = lineWaitingPackage
                        ? _t("Scan a product, a package or the destination location")
                        : _t("Scan a product then the destination location");
                }
            }
        }

        return barcodeInfo;
    },

    // Native own property on BarcodePickingModel.prototype -> reimplemented.
    _getFieldToWrite() {
        if (isFoodModel(this)) {
            return [
                "is_entire_pack",
                "location_id",
                "location_dest_id",
                "lot_id",
                "lot_name",
                "package_id",
                "outermost_result_package_id",
                "owner_id",
                "qty_done",
                "result_package_id",
            ];
        }
        return super._getFieldToWrite();
    },

    // Native own property on BarcodePickingModel.prototype -> reimplemented.
    _createCommandVals(line) {
        if (isFoodModel(this)) {
            const values = {
                dummy_id: line.virtual_id,
                is_entire_pack: line.is_entire_pack,
                location_id: line.location_id,
                location_dest_id: line.location_dest_id,
                lot_name: line.lot_name,
                lot_id: line.lot_id,
                package_id: line.package_id,
                picking_id: line.picking_id,
                picked: true,
                product_id: line.product_id,
                product_uom_id: line.product_uom_id,
                owner_id: line.owner_id,
                quantity: line.qty_done,
                result_package_id: line.result_package_id,
                state: "assigned",
            };
            for (const [key, value] of Object.entries(values)) {
                values[key] = this._fieldToValue(value);
            }
            return values;
        }
        return super._createCommandVals(line);
    },

    // Only defined on BarcodeModel.prototype natively -> ancestor call.
    _getSaveLineCommand(...args) {
        if (isFoodModel(this)) {
            return BASE_PROTO._getSaveLineCommand.call(this, ...args);
        }
        return super._getSaveLineCommand(...args);
    },

    // Native own property on BarcodePickingModel.prototype -> reimplemented.
    _updateLineQty(line, args) {
        if (!isFoodModel(this)) {
            return super._updateLineQty(...arguments);
        }
        if (args.qty_done) {
            if (line.product_id.tracking === "serial") {
                const nextQty = line.qty_done + args.qty_done;
                if (nextQty > 1 && (this.record.use_create_lots || this.record.use_existing_lots)) {
                    return; // Can't have more than 1 qty by serial number.
                }
            }
            line.qty_done += args.qty_done;
            this._setUser();
        }
    },

    // Native own property on BarcodePickingModel.prototype -> reimplemented
    // (its native body itself calls `super._processBarcode(barcode)`, i.e.
    // BarcodeModel.prototype._processBarcode, reached here via BASE_PROTO).
    async _processBarcode(barcode) {
        if (!isFoodModel(this)) {
            return super._processBarcode(...arguments);
        }
        if (this.isDone && !this.commands[barcode]) {
            return this.notification(_t("This picking is already done"), { type: "danger" });
        }
        return BASE_PROTO._processBarcode.call(this, barcode);
    },

    // Native own property on BarcodePickingModel.prototype -> reimplemented
    // verbatim (odoo/addons/stock_barcode/static/src/models/barcode_picking_model.js,
    // `async _processPackage(barcodeData)`). No `super.` calls in the native
    // body; every `this.xxx(...)` it calls (orm, cache, _isPackageInPackage,
    // _assignEmptyPackage, _putPackInPack, _convertDataToFieldsParams,
    // updateLine, _createNewLine, _findLine, _markLineAsDirty, ...) is
    // untouched by FEED's patch, so calling them plainly is safe.
    async _processPackage(barcodeData) {
        if (!isFoodModel(this)) {
            return super._processPackage(...arguments);
        }
        const { packageName } = barcodeData;
        const recPackage = barcodeData.package;
        if (barcodeData.packageType && !recPackage) {
            barcodeData.stopped = true;
            return await this._processPackageType(barcodeData);
        } else if (packageName && !recPackage) {
            this.lastScanned.packageId = false;
            barcodeData.stopped = true;
            return await this._putInPack({ default_name: packageName });
        } else if (!recPackage) {
            return;
        }
        const packLocation = recPackage.location_id
            ? this.cache.dbIdCache["stock.location"][recPackage.location_id]
            : false;
        if (recPackage.location_id && !packLocation) {
            return;
        }
        if (
            packLocation &&
            packLocation.id !== this._defaultDestLocation().id &&
            ((this.config.restrict_scan_source_location && packLocation.id !== this.location.id) ||
                (!this.config.restrict_scan_source_location &&
                    !this._isSublocation(packLocation, this.location)))
        ) {
            return;
        }

        let alreadyDonePackId;
        let scannedPackages = false;
        for (const packageLine of this.packageLines) {
            if (!this._isPackageInPackage(packageLine.package_id, recPackage)) {
                continue;
            }
            if (packageLine.qty_done) {
                alreadyDonePackId = recPackage.id;
                continue;
            }
            for (const line of packageLine.lines) {
                this.selectedLineVirtualId = line.virtual_id;
                await this._updateLineQty(line, { qty_done: line.reserved_uom_qty });
                this._markLineAsDirty(line);
                scannedPackages = true;
            }
        }
        if (alreadyDonePackId) {
            this.lastScanned.packageId = alreadyDonePackId;
            this.notification(_t("This package is already scanned."), { type: "danger" });
        }
        if (scannedPackages || alreadyDonePackId) {
            this.lastScanned.packageId = recPackage.id;
            barcodeData.stopped = true;
            return this.trigger("update");
        }

        this.lastScanned.packageId = false;
        const res = await this.orm.call("stock.quant", "get_stock_barcode_data_records", [
            recPackage.contained_quant_ids,
        ]);
        this.cache.setCache(res.records);
        const quants = res.records["stock.quant"];
        if (!this.config.barcode_allow_extra_product) {
            const allowedProductIds = new Set(
                this.currentState.lines.map((line) => line.product_id.id)
            );
            if (quants.some((quant) => !allowedProductIds.has(quant.product_id))) {
                barcodeData.error = _t(
                    "This package contains extra products and extra products are not allowed on this operation."
                );
                return;
            }
        }
        const currentLine = this.selectedLine || this.lastScannedLine;
        if (
            currentLine &&
            (!quants.length || recPackage.location_id === currentLine.location_dest_id.id)
        ) {
            const linesToUpdate = [currentLine];
            if (this.config.restrict_put_in_pack === "optional") {
                const filterFunction = !currentLine.result_package_id
                    ? (line) => !line.result_package_id
                    : (line) => line.result_package_id && !line.result_package_id.package_dest_id;
                linesToUpdate.push(
                    ...this.previousScannedLines.filter(
                        (line) =>
                            line.qty_done &&
                            line.virtual_id !== currentLine.virtual_id &&
                            filterFunction(line)
                    )
                );
            }
            if (!currentLine.result_package_id) {
                for (const line of linesToUpdate) {
                    await this._assignEmptyPackage(line, recPackage);
                }
            } else {
                const packageIds = linesToUpdate.map((l) => l.result_package_id?.id);
                await this._putPackInPack(packageIds, {
                    default_package_id: recPackage.id,
                });
            }
            barcodeData.stopped = true;
            this.lastScanned.packageId = recPackage.id;
            this.trigger("update");
            return;
        }

        if (this.location && (!packLocation || !this._isSublocation(packLocation, this.location))) {
            return;
        }
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
        if (alreadyExisting >= quants.length) {
            barcodeData.error = _t("This package is already scanned.");
            return;
        }

        if (alreadyExisting) {
            const userConfirmation = new Deferred();
            this.dialogService.add(ConfirmationDialog, {
                body: _t(
                    "You have already scanned %s items of this package. Do you want to scan the whole package?",
                    alreadyExisting
                ),
                title: _t("Scanning package"),
                cancel: () => userConfirmation.resolve(false),
                confirm: () => userConfirmation.resolve(true),
                close: () => userConfirmation.resolve(false),
            });
            if (!(await userConfirmation)) {
                barcodeData.stopped = true;
                return;
            }
        }

        for (const quant of quants) {
            const quantUoM = this.cache.getRecord("uom.uom", quant.product_uom_id);
            const product = this.cache.getRecord("product.product", quant.product_id);
            const searchLineParams = Object.assign({}, barcodeData, {
                product,
                quantPackage: this.cache.getRecord("stock.package", quant.package_id),
            });
            let remaining_qty = quant.quantity;
            let qty_used = 0;
            while (remaining_qty > 0) {
                const currentSearchLine = this._findLine(searchLineParams);
                if (currentSearchLine) {
                    const uomFactor = quantUoM.factor / currentSearchLine.product_uom_id.factor;
                    const lineQtyDiff =
                        currentSearchLine.reserved_uom_qty - currentSearchLine.qty_done;
                    const qtyNeeded = Math.max(lineQtyDiff, 0) / uomFactor;
                    qty_used = qtyNeeded ? Math.min(qtyNeeded, remaining_qty) : remaining_qty;
                    const fieldsParams = this._convertDataToFieldsParams({
                        quantity: qty_used * uomFactor,
                        lotName: barcodeData.lotName,
                        lot: barcodeData.lot,
                        package: quant.package_id,
                        owner: barcodeData.owner,
                    });
                    await this.updateLine(currentSearchLine, fieldsParams);
                } else {
                    qty_used = remaining_qty;
                    const isEntirePack = qty_used === quant.quantity;
                    const fieldsParams = this._convertDataToFieldsParams({
                        product,
                        quantity: qty_used,
                        lot: quant.lot_id,
                        package: quant.package_id,
                        resultPackage: quant.package_id,
                        owner: quant.owner_id,
                        srcLocation: quant.location_id,
                        isEntirePack,
                    });
                    if (quant.package_id !== recPackage.id) {
                        fieldsParams.outermost_result_package_id = recPackage.id;
                    }
                    const newLine = await this._createNewLine({ fieldsParams });
                    if (isEntirePack) {
                        newLine.packedQuantity = qty_used;
                    }
                }
                remaining_qty -= qty_used;
            }
        }
        barcodeData.stopped = true;
        this.selectedLineVirtualId = false;
        this.lastScanned.packageId = recPackage.id;
        this.trigger("update");
    },
});
