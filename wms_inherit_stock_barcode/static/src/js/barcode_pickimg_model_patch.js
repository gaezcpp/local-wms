/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import BarcodePickingModel from "@stock_barcode/models/barcode_picking_model";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Deferred } from "@web/core/utils/concurrency";

function getRelId(val) {
    return val && typeof val === "object" ? val.id : val || false;
}

function isUnreservedSurplusLine(line, debugLabel) {
    const result = Boolean(
        line &&
        !line.id &&
        !line.reserved_uom_qty &&
        line.package_id &&
        line.qty_done > 0
    );
    if (debugLabel) {
        console.log(
            `[DEBUG isUnreservedSurplusLine@${debugLabel}] id:${line && line.id} ` +
            `virtual_id:${line && line.virtual_id} ` +
            `package_id:${line && line.package_id ? (line.package_id.id ?? line.package_id) : null} ` +
            `qty_done:${line && line.qty_done} reserved_uom_qty:${line && line.reserved_uom_qty} ` +
            `-> isSurplus:${result}`
        );
    }
    return result;
}

patch(BarcodePickingModel.prototype, {

    _createState() {
        super._createState();
        if (this.record.picking_type_bypass_entire_packs) {
            this.groupingLinesEnabled = false;
        }
    },

    _snapshotStockTypeQty() {
        const snapshot = new Map();
        for (const line of this.currentState.lines) {
            snapshot.set(line.virtual_id, line.qty_done || 0);
        }
        return snapshot;
    },

    async _enforceUUStockType(snapshot) {
        const lines = this.currentState.lines;
        const linesToRemove = [];
        let blockedStockType = null;

        for (const line of lines) {
            const existedBefore = snapshot.has(line.virtual_id);
            const prevQty = existedBefore ? snapshot.get(line.virtual_id) : 0;
            const currQty = line.qty_done || 0;
            if (currQty <= prevQty) {
                continue; // Tidak ada penambahan qty pada line ini di scan kali ini.
            }

            const stockType = await this._getSourceStockType(line, {});
            if (stockType && stockType !== "UU") {
                blockedStockType = stockType;
                if (existedBefore) {
                    line.qty_done = prevQty;
                    this._markLineAsDirty(line);
                } else {
                    linesToRemove.push(line);
                }
            }
        }

        for (const line of linesToRemove) {
            const idx = this.currentState.lines.indexOf(line);
            if (idx !== -1) {
                this.currentState.lines.splice(idx, 1);
            }
            if (this.selectedLineVirtualId === line.virtual_id) {
                this.selectedLineVirtualId = false;
            }
            if (this.lastScanned && this.lastScanned.packageId && line.package_id) {
                const pkgId =
                    line.package_id && typeof line.package_id === "object"
                        ? line.package_id.id
                        : line.package_id;
                if (this.lastScanned.packageId === pkgId) {
                    this.lastScanned.packageId = false;
                }
            }
        }

        if (blockedStockType) {
            this._notifyStockTypeBlocked(blockedStockType);
        }
        return Boolean(blockedStockType);
    },

    _notifyStockTypeBlocked(stockType) {
        this.notification(
            _t(
                "Cannot scan: stock status is '%s', only 'UU' (Unrestricted Use) stock can be scanned.",
                stockType
            ),
            { type: "danger" }
        );
        this.trigger("update");
    },

    async _getSourceStockType(line, args) {
        line = line || {};
        args = args || {};
        if (line.id && typeof line.stock_type !== "undefined") {
            return line.stock_type;
        }
        if (typeof line.__scannedStockType !== "undefined") {
            return line.__scannedStockType;
        }

        const getId = (val) => (val && typeof val === "object" ? val.id : val || false);
        const productId = getId(args.product_id) || getId(line.product_id);
        if (!productId) {
            return false;
        }
        const locationId =
            getId(args.location_id) ||
            getId(line.location_id) ||
            (this.location && this.location.id);
        if (!locationId) {
            return false;
        }
        const lotId = getId(args.lot_id) || getId(line.lot_id);
        const packageId = getId(args.package_id) || getId(line.package_id);

        const domain = [
            ["product_id", "=", productId],
            ["location_id", "=", locationId],
        ];
        if (lotId) {
            domain.push(["lot_id", "=", lotId]);
        }
        if (packageId) {
            domain.push(["package_id", "=", packageId]);
        }

        let stockType = false;
        try {
            const quants = await this.orm.searchRead("stock.quant", domain, ["stock_type"], {
                limit: 1,
            });
            stockType = quants.length ? quants[0].stock_type : false;
        } catch (error) {
            console.error("[DEBUG] Gagal mengecek stock_type quant sumber:", error);
            return false;
        }
        line.__scannedStockType = stockType;
        return stockType;
    },

    get packageLines() {
        const shouldGroup =
            this.record.picking_type_entire_packs &&
            !this.record.picking_type_bypass_entire_packs;
        if (!shouldGroup || !this.currentState.lines.length) {
            return [];
        }
        return this._getPackageLines();
    },

    get pageLines() {
        let lines = super.pageLines;

        const shouldGroup =
            this.record.picking_type_entire_packs &&
            !this.record.picking_type_bypass_entire_packs;
        if (shouldGroup) {
            lines = lines.filter(
                (line) => !(line.package_id && line.result_package_id && line.is_entire_pack)
            );
        }

        if (this.record.hide_zero_qty) {
            lines = lines.filter((line) => !line.__isSurplusSkip);
        }

        return this._sortLine(lines);
    },

    get groupedLines() {
        const originalGroups = super.groupedLines;
        originalGroups.forEach((group, groupIndex) => {
            if (Array.isArray(group.lines)) {
                group.lines.forEach((subLine, subIndex) => {
                    console.log(
                        `[DEBUG]   >> Group#${groupIndex} SubLine#${subIndex}`,
                        JSON.stringify({
                            id: subLine.id,
                            virtual_id: subLine.virtual_id,
                            package_id: subLine.package_id ? subLine.package_id.id || subLine.package_id : null,
                            qty_done: subLine.qty_done,
                            quantity: subLine.quantity,
                            reserved_uom_qty: subLine.reserved_uom_qty,
                        }, null, 2)
                    );
                });
            }
        });
        return originalGroups;
    },

    async checkBarcode(barcode) {
        const result = await super.checkBarcode(...arguments);
        await this._cleanupPackageSplitRemainder();
        return result;
    },

    _updateLineQty(id, args) {
        const result = super._updateLineQty(...arguments);
        this._cleanupPackageSplitRemainder(); // fire-and-forget, tidak blocking UI
        return result;
    },

    async _cleanupPackageSplitRemainder() {
        if (!this.record.hide_zero_qty) {
            return;
        }
        if (!this.currentState || !this.currentState.lines) {
            return;
        }
        const lines = this.currentState.lines;
        const surplusLines = lines.filter(
            (line) => !line.__isSurplusSkip && isUnreservedSurplusLine(line, "cleanup")
        );

        let didMerge = false;

        for (const surplus of surplusLines) {
            const getId = (val) => (val && typeof val === "object" ? val.id : val);
            const surplusPackageId = getId(surplus.package_id);
            const surplusProductId = getId(surplus.product_id);
            const surplusLotId = getId(surplus.lot_id) || false;

            const sibling = lines.find((other) => {
                if (other === surplus || other.__isSurplusSkip) return false;
                return (
                    getId(other.package_id) === surplusPackageId &&
                    getId(other.product_id) === surplusProductId &&
                    (getId(other.lot_id) || false) === surplusLotId &&
                    other.reserved_uom_qty > 0
                );
            });

            if (sibling) {
                const before = sibling.qty_done || 0;
                sibling.qty_done = before + (surplus.qty_done || 0);
                this._markLineAsDirty(sibling);
                didMerge = true;

                surplus.qty_done = 0;
                surplus.reserved_uom_qty = 0;
                surplus.__isSurplusSkip = true;
            }
        }

        if (didMerge) {
            await this.save();
        }
    },

    _getSaveLineCommand(...args) {
        const line = args.find(
            (a) => a && typeof a === "object" && ("virtual_id" in a || "package_id" in a)
        );

        if (this.record.hide_zero_qty && line && line.__isSurplusSkip) {
            return null;
        }
        return super._getSaveLineCommand(...args);
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
        const shouldGroupPackage =
            this.record.picking_type_entire_packs && !this.record.picking_type_bypass_entire_packs;

        if (!line && shouldGroupPackage) {
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
        const normalizedBarcode = (barcode || "").trim().toUpperCase();
        return Object.values(productionLineCache).find(
            (pl) => (pl.code || "").trim().toUpperCase() === normalizedBarcode
        );
    },

    get _lineAwaitingProductionLine() {
        if (!this.record.production_only) {
            return null;
        }
        const isPending = (l) => Boolean(l && l.result_package_id && !l.production_line_id);
        // Normally the packed line stays selected, but when its demand isn't fully done,
        // core's _assignEmptyPackage() splits it and moves selection to the new remainder
        // line (which has no package yet). lastScannedLine still points at the line that
        // was actually just packed in that case, so check it before falling back to a full
        // scan of the page's lines.
        if (isPending(this.selectedLine)) {
            return this.selectedLine;
        }
        if (isPending(this.lastScannedLine)) {
            return this.lastScannedLine;
        }
        const lines = (this.currentState && this.currentState.lines) || [];
        return lines.find(isPending) || null;
    },

    async _getPackageStockType(packageId) {
        if (!packageId) {
            return false;
        }
        try {
            const quants = await this.orm.searchRead(
                "stock.quant",
                [
                    ["package_id", "=", packageId],
                    ["quantity", "!=", 0],
                ],
                ["stock_type"],
                { limit: 1 }
            );
            return quants.length ? quants[0].stock_type : false;
        } catch (error) {
            console.error("[DEBUG] Gagal mengecek stock_type package tujuan:", error);
            return false;
        }
    },

    async _processPackage(barcodeData) {
        const recPackage = barcodeData && barcodeData.package;
        if (
            this.record &&
            this.record.check_scan_pallet &&
            recPackage &&
            Array.isArray(recPackage.contained_quant_ids) &&
            recPackage.contained_quant_ids.length
        ) {
            const isExpectedSource = (this.currentState.lines || []).some(
                (line) => getRelId(line.package_id) === recPackage.id
            );
            if (!isExpectedSource) {
                const userConfirmation = new Deferred();
                this.dialogService.add(ConfirmationDialog, {
                    title: _t("Peringatan: Pallet Tidak Terdaftar!"),
                    body: _t(
                        "Pallet %s tidak terdaftar sebagai Source Package pada transfer ini. Apakah Anda yakin ingin melanjutkan?",
                        recPackage.name
                    ),
                    confirm: () => userConfirmation.resolve(true),
                    cancel: () => userConfirmation.resolve(false),
                    close: () => userConfirmation.resolve(false),
                });
                const confirmed = await userConfirmation;
                if (!confirmed) {
                    barcodeData.stopped = true;
                    this.trigger("update");
                    return;
                }
            }
        }

        const isSplitPackage = Boolean(this.record && this.record.split_package);
        if (isSplitPackage && recPackage) {
            const currentLine = this.selectedLine || this.lastScannedLine;
            if (
                currentLine &&
                currentLine.package_id &&
                !currentLine.result_package_id &&
                getRelId(currentLine.package_id) !== recPackage.id
            ) {
                const sourceStockType = await this._getSourceStockType(currentLine, {});
                const destStockType = await this._getPackageStockType(recPackage.id);
                if (sourceStockType && destStockType && sourceStockType !== destStockType) {
                    this._notifyStockTypeBlocked(destStockType);
                    barcodeData.stopped = true;
                    return;
                }

                await this._assignEmptyPackage(currentLine, recPackage);
                barcodeData.stopped = true;
                this.lastScanned.packageId = recPackage.id;
                this.trigger("update");
                return;
            }
        }
        return super._processPackage(...arguments);
    },

    async _processBarcode(barcode) {
        let lineBeforeScan = this.selectedLine || this.lastScannedLine;
        if (!lineBeforeScan && this.currentState && this.currentState.lines && this.currentState.lines.length > 0) {
            lineBeforeScan = this.currentState.lines[0];
        }
        const isProductionOnly = this.record && this.record.production_only;

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
                if (scannedPackages.length > 0) {
                    const pkg = scannedPackages[0];
                    if (pkg.location_id && pkg.location_id.length > 0) {
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
                console.error("[DEBUG] Gagal melakukan pengecekan status package via ORM:", error);
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

        const isUUOnly = Boolean(this.record && this.record.uu_only);
        const stockTypeSnapshot = isUUOnly ? this._snapshotStockTypeQty() : null;

        await super._processBarcode(...arguments);

        if (isUUOnly) {
            const wasBlocked = await this._enforceUUStockType(stockTypeSnapshot);
            if (wasBlocked) {
                this.trigger("update");
                return;
            }
        }

        const isSplitPackage = Boolean(this.record && this.record.split_package);
        if (isSplitPackage) {
            const getId = getRelId;
            const linesToReset = (this.currentState.lines || []).filter((line) => {
                const resultPkgId = getId(line.result_package_id);
                const sourcePkgId = getId(line.package_id);
                return resultPkgId && sourcePkgId && resultPkgId === sourcePkgId;
            });

            if (linesToReset.length) {
                for (const line of linesToReset) {
                    line.result_package_id = false;
                    this._markLineAsDirty(line);
                }
                const currentSelection = this.selectedLine;
                const lineToSelect =
                    (currentSelection &&
                        linesToReset.some((l) => l.virtual_id === currentSelection.virtual_id) &&
                        currentSelection) ||
                    linesToReset[linesToReset.length - 1];
                this._selectLine(lineToSelect);
            }
        }

        await this._cleanupPackageSplitRemainder();

        const lastScan = this.scanHistory[0];
        if (lastScan && lastScan.destLocation && this.record) {
            const notifLocation = this.record.picking_type_code === 'internal' && this.record.picking_type_entire_packs;
            if (notifLocation) {
                const scannedLocation = lastScan.destLocation;
                if (oldExpectedLocId && oldExpectedLocId !== scannedLocation.id) {
                    this.dialogService.add(ConfirmationDialog, {
                        title: _t("Peringatan: Lokasi Berbeda!"),
                        body: _t("Anda melakukan scan pada lokasi %s, yang mana tidak sesuai dengan Store To awal. Apakah Anda yakin ingin melanjutkan?", scannedLocation.display_name),
                        confirm: async () => {
                            if (lineBeforeScan && typeof lineBeforeScan.id === 'number') {
                                try {
                                    await this.orm.write("stock.move.line", [lineBeforeScan.id], {
                                        suggest_dest_id: oldExpectedLocId
                                    });
                                } catch (error) {
                                    console.error("[DEBUG] Gagal menyimpan suggest_dest_id ke backend:", error);
                                }
                            }
                        },
                        cancel: () => {
                            console.log("[DEBUG] User membatalkan peringatan.");
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