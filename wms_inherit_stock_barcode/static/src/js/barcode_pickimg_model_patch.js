/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import BarcodePickingModel from "@stock_barcode/models/barcode_picking_model";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(BarcodePickingModel.prototype, {

    _displayEntirePackage() {
        return (
            this.record.picking_type_entire_packs ||
            this.record.picking_type_bypass_entire_packs
        );
    },

    get packageLines() {
        if (!this._displayEntirePackage() || !this.currentState.lines.length) {
            return [];
        }
        return this._getPackageLines();
    },

    get pageLines() {
        let lines = super.pageLines;
        if (this._displayEntirePackage()) {
            lines = lines.filter(
                (line) => !(line.package_id && line.result_package_id && line.is_entire_pack)
            );
        }
        return this._sortLine(lines);
    },

    get barcodeInfo() {
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

        // SCAN PRODUCTION LINE
        if (this.record.production_only && this._lineAwaitingProductionLine) {
            return {
                message: _t("Scan the production line"),
                class: "scan_production_line",
                icon: "industry",
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
            pressValidateBtn: {
                message: _t("Press Validate or scan another product"),
                class: "scan_validate",
                icon: "check-square",
            },
        };
        let barcodeInfo = { message: _t("Scan a product"), class: "scan_product", icon: "tags" };
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
        // GANTI di sini: this._moveEntirePackage() -> this._displayEntirePackage()
        if (!line && this._displayEntirePackage()) {
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
                    return { message: _t("Scan a package"), class: "scan_package", icon: "archive" };
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
                    lines.every((line) => !this._lineIsNotComplete(line)) &&
                    lines.some((line) => this._lineNeedsToBePacked(line))
                ) {
                    return infos.scanPackage;
                }
            }
            return barcodeInfo;
        }
        const product = line.product_id;

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


    // UNTUK SCAN PRODUCTION LINE
    _getFieldToWrite() {
        const fields = super._getFieldToWrite();
        if (!fields.includes("production_line_id")) {
            fields.push("production_line_id");
        }
        return fields;
    },

    _createCommandVals(line) {
        const values = super._createCommandVals(line);
        values.production_line_id = this._fieldToValue(line.production_line_id);
        return values;
    },

    _findProductionLineByCode(barcode) {
        const productionLineCache = this.cache.dbIdCache?.["production.line"] || {};
        console.log("productionLineCache", productionLineCache)
        return Object.values(productionLineCache).find((pl) => pl.code === barcode);
    },

    get _lineAwaitingProductionLine() {
        if (!this.record.production_only) {
            return null;
        }
        const line = this.selectedLine;
        if (line && line.result_package_id && !line.production_line_id) {
            return line;
        }
        return null;
    },

    async _processBarcode(barcode) {
        console.log("_processBarcode Override Triggered:", barcode);

        let lineBeforeScan = this.selectedLine || this.lastScannedLine;
        if (!lineBeforeScan && this.currentState && this.currentState.lines && this.currentState.lines.length > 0) {
            lineBeforeScan = this.currentState.lines[0];
        }

        const isProductionOnly = this.record && this.record.production_only;
        console.log("isProductionOnly", isProductionOnly)

        if (isProductionOnly) {
            const line = this._lineAwaitingProductionLine;
            if (line) {
                const productionLine = this._findProductionLineByCode(barcode);
                if (productionLine) {
                    return this._setProductionLineOnLine(line, productionLine);
                }
                const message = _t("No production line found for barcode %s", barcode);
                return this.notification(message, { type: "danger" });
            }

            try {
                const scannedPackages = await this.orm.searchRead(
                    "stock.package",
                    [["name", "=", barcode]],
                    ["location_id", "name"]
                );
                console.log("scannedPackages", scannedPackages)

                if (scannedPackages.length > 0) {
                    const pkg = scannedPackages[0];
                    if (pkg.location_id && pkg.location_id.length > 0) {
                        console.warn(`Scan Ditolak: Package ${pkg.name} sudah memiliki lokasi:`, pkg.location_id);
                        this.dialogService.add(ConfirmationDialog, {
                            title: _t("Scan Ditolak!"),
                            body: `Lokasi pada Pallet ${pkg.name} sudah terisi (${pkg.location_id[1]}), silahkan gunakan Pallet lain.`,
                            confirmLabel: _t("OK"),
                            confirm: () => { },
                            cancel: () => { }
                        });
                        return;
                    }
                }
            } catch (error) {
                console.error("Gagal melakukan pengecekan status package via ORM:", error);
            }
        }

        let oldExpectedLocId = null;
        if (lineBeforeScan && lineBeforeScan.location_dest_id) {
            oldExpectedLocId = typeof lineBeforeScan.location_dest_id === 'object'
                ? (lineBeforeScan.location_dest_id.id || lineBeforeScan.location_dest_id[0])
                : lineBeforeScan.location_dest_id;
        } else if (this.record && this.record.location_dest_id) {
            oldExpectedLocId = typeof this.record.location_dest_id === 'object'
                ? (this.record.location_dest_id.id || this.record.location_dest_id[0])
                : this.record.location_dest_id;
        }

        await super._processBarcode(...arguments);

        const lastScan = this.scanHistory[0];

        if (lastScan && lastScan.destLocation && this.record) {
            const notifLocation = this.record.picking_type_code === 'internal' && this.record.picking_type_entire_packs;

            if (notifLocation) {
                const scannedLocation = lastScan.destLocation;

                if (oldExpectedLocId && oldExpectedLocId !== scannedLocation.id) {
                    console.log("Kondisi SCAN LOKASI BEDA");

                    this.dialogService.add(ConfirmationDialog, {
                        title: _t("Peringatan: Lokasi Berbeda!"),
                        body: _t("Anda melakukan scan pada lokasi %s, yang mana tidak sesuai dengan Store To awal. Apakah Anda yakin ingin melanjutkan?", scannedLocation.display_name),

                        confirm: async () => {
                            console.log("User mengkonfirmasi perubahan lokasi.");
                            if (lineBeforeScan && typeof lineBeforeScan.id === 'number') {
                                try {
                                    await this.orm.write("stock.move.line", [lineBeforeScan.id], {
                                        suggest_dest_id: oldExpectedLocId
                                    });
                                } catch (error) {
                                    console.error("Gagal menyimpan suggest_dest_id ke backend:", error);
                                }
                            }
                        },
                        cancel: () => {
                            console.log("User membatalkan peringatan.");
                        }
                    });
                }
            }
        }
    },

    async _setProductionLineOnLine(line, productionLine) {
        line.production_line_id = { id: productionLine.id, display_name: productionLine.name };

        if (line.id) {
            await this.save();
            await this.orm.write("stock.move.line", [line.id], { production_line_id: productionLine.id });
        } else {
            this._markLineAsDirty(line);
        }

        this.trigger("update");
    },
});