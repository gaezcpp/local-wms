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

// #fix minus quant scan — tracing sementara. Set true untuk menyalakan seluruh
// log [WMS-SCAN], termasuk pembacaan ulang stock.quant di override `save()`.
const WMS_SCAN_DEBUG = false;

// Log isi setiap subline pada getter `groupedLines`. Berat karena getter itu
// dipanggil pada SETIAP render, jadi biarkan false kecuali sedang dibutuhkan.
const WMS_GROUPED_LINES_DEBUG = false;

/** JSON aman-circular, supaya isi log bisa langsung di-copy sebagai teks. */
function wmsJson(payload) {
    const seen = new WeakSet();
    try {
        return JSON.stringify(payload, (key, value) => {
            if (typeof value === "object" && value !== null) {
                if (seen.has(value)) {
                    return "[circular]";
                }
                seen.add(value);
            }
            return value;
        });
    } catch (error) {
        return `[tidak bisa di-serialize: ${error}]`;
    }
}

function wmsLog(tag, payload) {
    if (!WMS_SCAN_DEBUG) {
        return;
    }
    if (payload === undefined) {
        console.log(`[WMS-SCAN] ${tag}`);
    } else {
        console.log(`[WMS-SCAN] ${tag} :: ${wmsJson(payload)}`, payload);
    }
}

/** Ringkasan satu move line untuk dibaca di console. */
function dbgLine(line) {
    if (!line) {
        return null;
    }
    const lotId = getRelId(line.lot_id);
    return {
        id: line.id || null,
        virtual_id: line.virtual_id,
        move: getRelId(line.move_id),
        order_selection: line.order_selection || null,
        gratis_locked: line.gratis_locked || null,
        product: getRelId(line.product_id),
        lot: lotId ? `${lotId}:${(line.lot_id && line.lot_id.name) || ""}` : line.lot_name || null,
        pkg: getRelId(line.package_id),
        result_pkg: getRelId(line.result_package_id),
        entire_pack: Boolean(line.is_entire_pack),
        qty_done: line.qty_done,
        reserved: line.reserved_uom_qty,
        loc: getRelId(line.location_id),
        surplus_skip: Boolean(line.__isSurplusSkip),
    };
}

patch(BarcodePickingModel.prototype, {

    /**
     * Untuk picking type ber-`bypass_entire_packs`, baris dikelompokkan per
     * product + package — bukan product + lokasi asal + lokasi tujuan seperti
     * bawaan core. Satu pallet jadi satu baris ringkasan, dan isi dropdown-nya
     * otomatis menjadi per lot karena setiap move line dalam grup tersebut
     * membawa lot yang berbeda.
     *
     * Sebelumnya flag ini mematikan grouping sepenuhnya (`groupingLinesEnabled`
     * di-set false), sehingga tampilannya rata satu baris per lot.
     *
     * Baris tanpa package tetap memakai kunci core. Produk tanpa tracking juga
     * tidak ikut dikelompokkan — core sudah menyaringnya lewat
     * `lineCannotBeGrouped()`, dan itu memang konsisten karena detailnya per lot.
     */
    groupKey(line) {
        if (this.record.picking_type_bypass_entire_packs) {
            const packageId = getRelId(line.package_id);
            if (packageId) {
                // Prefiks `pkg` menjaga kunci ini tidak pernah bentrok dengan
                // kunci core yang seluruhnya berupa angka (`product_loc_dest`).
                return `${getRelId(line.product_id)}_pkg_${packageId}`;
            }
        }
        return super.groupKey(...arguments);
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

    async _enforceGratisLocked(snapshot) {
        const lines = this.currentState.lines;
        const linesToRemove = [];
        let blocked = false;

        for (const line of lines) {
            const existedBefore = snapshot.has(line.virtual_id);
            const prevQty = existedBefore ? snapshot.get(line.virtual_id) : 0;
            const currQty = line.qty_done || 0;
            if (currQty <= prevQty) {
                continue; // Tidak ada penambahan qty pada line ini di scan kali ini.
            }

            if (line.order_selection === "gratis" && line.gratis_locked) {
                blocked = true;
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
        }

        if (blocked) {
            this._notifyGratisLockedBlocked();
        }
        return blocked;
    },

    _notifyGratisLockedBlocked() {
        this.notification(
            _t("Order belum terpenuhi, produk gratis belum bisa diproses"),
            { type: "danger" }
        );
        this.trigger("update");
    },

    _notifyStockTypeBlocked(stockType) {
        this.notification(
            _t(
                "Tidak bisa scan: Stock Type '%s', hanya 'UU' (Unrestricted Use) yang bisa dilakukan scan!.",
                stockType
            ),
            { type: "danger" }
        );
        this.trigger("update");
    },

    _notifyYellowTagBlocked(packageName) {
        this.dialogService.add(ConfirmationDialog, {
            title: _t("Scan Ditolak!"),
            body: _t(
                "Pallet %s berstatus Hold tidak dapat digunakan untuk transaksi!",
                packageName
            ),
            confirmLabel: _t("OK"),
            confirm: () => { },
            cancel: () => { }
        });
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
        if (WMS_GROUPED_LINES_DEBUG) {
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
        }
        return originalGroups;
    },

    async checkBarcode(barcode) {
        const result = await super.checkBarcode(...arguments);
        await this._cleanupPackageSplitRemainder();
        return result;
    },

    /**
     * #ai_fixed — jangan panggil `_cleanupPackageSplitRemainder()` dari sini.
     *
     * Core memanggil `_updateLineQty()` TANPA await (barcode_model.js:568), jadi
     * versi `async` sebelumnya melepas promise yang berjalan bebas di tengah loop
     * scan package. Di dalamnya ada `await this.save()`, yang bisa tumpang tindih
     * dengan `save()` lain dan menggandakan move line.
     *
     * Cleanup tetap berjalan lewat `checkBarcode()` dan `_processBarcode()`, yang
     * keduanya di-await, jadi tidak ada perilaku merge yang hilang — hanya
     * waktunya bergeser ke akhir scan, bukan di tengah loop.
     */
    _updateLineQty(line, args) {
        if (args && args.qty_done && line && line.order_selection === "gratis" && line.gratis_locked) {
            this._notifyGratisLockedBlocked();
            return;
        }
        return super._updateLineQty(...arguments);
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
            (line) =>
                !line.__isSurplusSkip &&
                isUnreservedSurplusLine(line, WMS_SCAN_DEBUG ? "cleanup" : false)
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
                // this.dialogService.add(ConfirmationDialog, {
                //     title: _t("Peringatan: Pallet Tidak Terdaftar!"),
                //     body: _t(
                //         "Pallet %s tidak terdaftar sebagai Source Package pada transfer ini. Apakah Anda yakin ingin melanjutkan?",
                //         recPackage.name
                //     ),
                //     confirm: () => userConfirmation.resolve(true),
                //     cancel: () => userConfirmation.resolve(false),
                //     close: () => userConfirmation.resolve(false),
                // });
                this.dialogService.add(ConfirmationDialog, {
                    title: _t("Peringatan: Pallet Tidak Terdaftar!"),
                    body: _t(
                        "Pallet %s tidak terdaftar pada DO yang sedang diproses!",
                        recPackage.name
                    ),
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

        // #fix minus quant scan
        wmsLog("processPackage:START", {
            package: recPackage
                ? {
                      id: recPackage.id,
                      name: recPackage.name,
                      location_id: recPackage.location_id,
                      quant_ids: recPackage.contained_quant_ids,
                  }
                : null,
            config: {
                hide_zero_qty: this.record.hide_zero_qty,
                uu_only: this.record.uu_only,
                split_package: this.record.split_package,
                entire_packs: this.record.picking_type_entire_packs,
                bypass_entire_packs: this.record.picking_type_bypass_entire_packs,
                allow_extra_product: this.config.barcode_allow_extra_product,
            },
            currentLocation: getRelId(this.location),
            selectedLine: dbgLine(this.selectedLine),
            packageLines: this.packageLines.map(dbgLine),
            linesBefore: this.currentState.lines.map(dbgLine),
        });

        await this._resetScannedPackageSourceLines(recPackage);

        // Line baru bikinan core tidak membawa field kustom (`uom_bag_id`,
        // `order_selection`, dst) karena dirakit di client, bukan dibaca dari
        // server. Tandai supaya `_processBarcode()` menyimpannya setelah semua
        // guard selesai — `save()` memicu `refreshCache()` yang mengisi ulang
        // seluruh field dari server.
        //
        // Dibatasi ke picking type `checker_out` saja: di sanalah tampilan UoM BAG
        // dan Bulk Entry dipakai, sehingga tambahan satu RPC per scan sepadan.
        this.__wmsPendingScanSave = Boolean(
            this.record.checker_out &&
                recPackage &&
                Array.isArray(recPackage.contained_quant_ids) &&
                recPackage.contained_quant_ids.length
        );

        this.__wmsScanDebug = true;
        this.__wmsScannedPackageId = recPackage ? recPackage.id : false;
        try {
            return await super._processPackage(...arguments);
        } finally {
            this.__wmsScanDebug = false;
            wmsLog("processPackage:END", {
                quants: this._debugPackageQuants(recPackage),
                linesAfter: this.currentState.lines.map(dbgLine),
                linesToSave: this.linesToSave,
            });
        }
    },

    /** #fix minus quant scan — isi quant pallet yang di-scan, urut sesuai yang diproses core. */
    _debugPackageQuants(recPackage) {
        if (!recPackage || !Array.isArray(recPackage.contained_quant_ids)) {
            return [];
        }
        return recPackage.contained_quant_ids.map((quantId) => {
            try {
                const quant = this.cache.getRecord("stock.quant", quantId);
                if (!quant) {
                    return { id: quantId, missing: true };
                }
                const lot = quant.lot_id && this.cache.getRecord("stock.lot", quant.lot_id);
                return {
                    id: quant.id,
                    lot: quant.lot_id ? `${quant.lot_id}:${(lot && lot.name) || "?"}` : null,
                    qty: quant.quantity,
                    pkg: quant.package_id,
                };
            } catch (error) {
                return { id: quantId, error: String(error) };
            }
        });
    },

    /**
     * #fix minus quant scan
     *
     * Barcode sebuah package tidak membawa lot, sehingga di dalam core
     * `_processPackage()` pencocokan line lewat `_findLine()` hanya memakai
     * product + package — `_canOverrideTrackingNumber()` selalu meloloskan line
     * yang lot-nya berbeda. Akibatnya qty milik quant lot A bisa mengisi line
     * reservasi lot B; lalu saat giliran quant lot B diproses, line tadi sudah
     * penuh dan line lama pun tidak bisa dipakai lagi
     * (`_lineCannotBeTaken()` menolak line hasil scan package karena
     * `result_package_id` terisi tanpa `reserved_uom_qty`), sehingga core membuat
     * line BARU untuk lot B. Jadilah satu quant punya dua move line dan
     * `reserved_quantity`-nya melebihi `quantity` — `available_quantity` negatif.
     *
     * Mengikuti proses manual yang sudah terbukti benar: reservasi lama untuk
     * pallet yang di-scan dilepas dulu (move line-nya di-unlink, sama seperti
     * tombol Unreserve), lalu scan dilanjutkan seperti semula sehingga core
     * membuat line baru per quant dengan lot masing-masing.
     *
     * Line yang dilepas juga harus dibuang dari state client — kalau tidak,
     * `_findLine()` masih melihatnya sebagai kandidat dan qty quant lot lain akan
     * ditumpahkan ke situ lagi.
     *
     * Yang dilepas hanya line yang belum di-scan (`qty_done` 0) dan bukan
     * entire-pack line, supaya flow package line bawaan core tidak ikut terganggu.
     *
     * @param {Object} recPackage package yang barusan di-scan
     */
    async _resetScannedPackageSourceLines(recPackage) {
        // Hint `move_id` dari scan sebelumnya tidak boleh bocor ke pallet lain.
        this.__wmsMoveHint = null;
        if (
            !recPackage ||
            !Array.isArray(recPackage.contained_quant_ids) ||
            !recPackage.contained_quant_ids.length
        ) {
            wmsLog("reset:SKIP", "package tanpa quant -> dipakai sebagai result package");
            return;
        }

        const packLocation = recPackage.location_id
            ? this.cache.dbIdCache["stock.location"][recPackage.location_id]
            : false;
        if (packLocation && packLocation.id === this._defaultDestLocation().id) {
            wmsLog("reset:SKIP", "pallet ada di lokasi tujuan -> dipakai sebagai result package");
            return;
        }

        // Kalau pallet ini memang ditangani core lewat jalur entire-pack line,
        // jangan diutak-atik — core sudah punya alurnya sendiri.
        if (
            this.packageLines.some((packageLine) =>
                this._isPackageInPackage(packageLine.package_id, recPackage)
            )
        ) {
            wmsLog("reset:SKIP", "pallet ditangani core sebagai entire-pack line");
            return;
        }

        // Catatan: JANGAN pakai `result_package_id` sebagai penanda entire-pack di
        // repo ini — `_autofill_result_package()` (wms_base_warehouse/stock_move.py)
        // mengisinya pada line reservasi biasa, sehingga semua line ikut terlewat.
        const candidates = this.currentState.lines.filter(
            (line) => getRelId(line.package_id) === recPackage.id
        );
        const linesToReset = candidates.filter(
            (line) => !line.is_entire_pack && !this.getQtyDone(line)
        );
        wmsLog("reset:CANDIDATES", {
            semuaLineDenganPalletIni: candidates.map(dbgLine),
            akanDireset: linesToReset.map(dbgLine),
            dilewati: candidates
                .filter((line) => !linesToReset.includes(line))
                .map((line) => ({
                    line: dbgLine(line),
                    alasan: line.is_entire_pack
                        ? "is_entire_pack (ditangani core)"
                        : "qty_done > 0 (sudah di-scan)",
                })),
        });
        if (!linesToReset.length) {
            wmsLog("reset:SKIP", "tidak ada line yang perlu dikosongkan");
            return;
        }

        // Line yang dikosongkan membawa `move_id` yang benar. Line baru bikinan core
        // dikirim TANPA `move_id` (`_createCommandVals()` tidak menyertakannya),
        // sehingga server menebak sendiri lewat `_get_linkable_moves()` dan bisa
        // salah jatuh ke move lain (mis. move 'gratis'). Jadi move-nya kita ingat
        // di sini dan pasang kembali pada line baru untuk pallet yang sama.
        const moveByProduct = new Map();
        for (const line of linesToReset) {
            const productId = getRelId(line.product_id);
            const moveId = getRelId(line.move_id);
            if (productId && moveId && !moveByProduct.has(productId)) {
                moveByProduct.set(productId, moveId);
            }
        }
        this.__wmsMoveHint = moveByProduct.size
            ? { packageId: recPackage.id, moveByProduct }
            : null;
        wmsLog("reset:MOVE-HINT", {
            packageId: recPackage.id,
            moveByProduct: Array.from(moveByProduct.entries()),
        });

        // Line-nya dihapus, bukan sekadar di-nol-kan. `stock.move.line.unlink()`
        // tetap melepas `reserved_quantity` pada quant (core stock_move_line.py:565)
        // — persis yang dilakukan tombol Unreserve lewat `_do_unreserve()`. Kalau
        // hanya di-set quantity 0, barisnya tetap ada di DB dan akan muncul kembali
        // sebagai baris kosong begitu state di-refresh, karena `_createLinesState()`
        // membangun ulang dari `picking.move_line_ids`.
        const idsToReset = linesToReset.map((line) => line.id).filter(Boolean);
        if (idsToReset.length) {
            wmsLog("reset:UNLINK", { model: "stock.move.line", ids: idsToReset });
            await this.orm.unlink("stock.move.line", idsToReset);
        }

        for (const line of linesToReset) {
            const index = this.currentState.lines.indexOf(line);
            if (index !== -1) {
                this.currentState.lines.splice(index, 1);
            }
            this.linesToSave = this.linesToSave.filter((vId) => vId !== line.virtual_id);
            this.scannedLinesVirtualId = this.scannedLinesVirtualId.filter(
                (vId) => vId !== line.virtual_id
            );
            if (this.selectedLineVirtualId === line.virtual_id) {
                this.selectedLineVirtualId = false;
            }
        }
        wmsLog("reset:DONE", {
            dikosongkan: linesToReset.length,
            sisaLineDiState: this.currentState.lines.map(dbgLine),
        });
    },

    // ---------------------------------------------------------------------
    // #fix minus quant scan — blok tracing. Aman dihapus kalau sudah tidak
    // dibutuhkan; semuanya hanya console.log dan meneruskan return value core.
    // ---------------------------------------------------------------------

    _findLine(barcodeData) {
        const found = super._findLine(...arguments);
        if (this.__wmsScanDebug) {
            const searchLot = barcodeData && barcodeData.lot;
            wmsLog("findLine", {
                cari: {
                    product: getRelId(barcodeData && barcodeData.product),
                    pkg: getRelId(
                        (barcodeData && (barcodeData.quantPackage || barcodeData.package)) || false
                    ),
                    lot: searchLot
                        ? `${getRelId(searchLot)}:${searchLot.name || ""}`
                        : (barcodeData && barcodeData.lotName) || null,
                },
                ketemu: dbgLine(found),
                kandidat: this.pageLines.map(dbgLine),
            });
        }
        return found;
    },

    async updateLine(line, args) {
        const before = this.__wmsScanDebug ? dbgLine(line) : null;
        const res = await super.updateLine(...arguments);
        if (this.__wmsScanDebug) {
            wmsLog("updateLine", {
                sebelum: before,
                qtyDitambah: args && args.qty_done,
                sesudah: dbgLine(line),
            });
        }
        return res;
    },

    async _createNewLine(params) {
        const newLine = await super._createNewLine(...arguments);

        // #fix minus quant scan — kembalikan `move_id` line yang tadi dikosongkan,
        // supaya server tidak menebak move lewat `_get_linkable_moves()`.
        const hint = this.__wmsMoveHint;
        if (hint && newLine && !getRelId(newLine.move_id)) {
            const productId = getRelId(newLine.product_id);
            if (
                getRelId(newLine.package_id) === hint.packageId &&
                hint.moveByProduct.has(productId)
            ) {
                newLine.move_id = hint.moveByProduct.get(productId);
                wmsLog("createNewLine:MOVE-HINT-DIPASANG", {
                    virtual_id: newLine.virtual_id,
                    product: productId,
                    move_id: newLine.move_id,
                });
            }
        }

        if (this.__wmsScanDebug) {
            const fp = (params && params.fieldsParams) || {};
            wmsLog("createNewLine", {
                diminta: {
                    qty_done: fp.qty_done,
                    lot_id: getRelId(fp.lot_id),
                    package_id: getRelId(fp.package_id),
                    result_package_id: getRelId(fp.result_package_id),
                    is_entire_pack: fp.is_entire_pack,
                },
                dibuat: dbgLine(newLine),
            });
        }
        return newLine;
    },

    /**
     * #fix minus quant scan
     *
     * Core tidak mengirim `move_id` saat membuat move line baru, sehingga server
     * memilih move sendiri lewat `_get_linkable_moves()` — yang hanya menyaring
     * berdasarkan product dan bisa salah jatuh ke move 'gratis'. Kalau line-nya
     * sudah membawa `move_id` (dipasang dari hint saat reset), ikutkan.
     */
    _createCommandVals(line) {
        const vals = super._createCommandVals(...arguments);
        const moveId = getRelId(line && line.move_id);
        if (moveId && vals && vals.move_id === undefined) {
            vals.move_id = moveId;
        }
        return vals;
    },

    _getSaveCommand() {
        const command = super._getSaveCommand();
        wmsLog(
            "saveCommand",
            command && command.params ? command.params.write_vals : "(tidak ada yang disimpan)"
        );
        return command;
    },

    /**
     * #ai_fixed — cegah move line ganda.
     *
     * Core `save()` (barcode_model.js:481-488) baru mengosongkan `linesToSave`
     * SETELAH RPC-nya selesai:
     *
     *     const { route, params } = this._getSaveCommand();   // baca linesToSave
     *     if (route) { await rpc(route, params); await this.refreshCache(...); }
     *     this.linesToSave = [];                              // baru dibersihkan
     *
     * Artinya dua pemanggilan `save()` yang saling tumpang tindih sama-sama
     * membaca `linesToSave` yang belum kosong, lalu mengirim perintah
     * `[0, 0, {dummy_id: N, ...}]` yang identik. Controller `save_barcode_data`
     * hanya melakukan `write({move_line_ids: vals})` tanpa idempotensi, sehingga
     * server membuat move line DUA KALI untuk satu line hasil scan.
     *
     * Di sini pemanggilan `save()` diserialkan: yang kedua menunggu yang pertama
     * selesai, sehingga saat gilirannya tiba `linesToSave` sudah bersih dan ia
     * menjadi no-op — bukan create kedua.
     */
    save() {
        const previous = this.__wmsSaveChain || Promise.resolve();
        const current = previous.catch(() => {}).then(() => this.__wmsSaveOnce());
        this.__wmsSaveChain = current;
        return current;
    },

    async __wmsSaveOnce() {
        const res = await super.save();
        if (WMS_SCAN_DEBUG && this.__wmsScannedPackageId) {
            try {
                const quants = await this.orm.searchRead(
                    "stock.quant",
                    [["package_id", "=", this.__wmsScannedPackageId]],
                    ["lot_id", "location_id", "quantity", "reserved_quantity", "available_quantity"]
                );
                wmsLog("quantSetelahSave", quants);
                const minus = quants.filter((q) => q.available_quantity < 0);
                if (minus.length) {
                    console.warn("[WMS-SCAN] QUANT MINUS TERDETEKSI", minus);
                }
            } catch (error) {
                console.warn("[WMS-SCAN] gagal membaca quant setelah save:", error);
            }
        }
        return res;
    },

    async _processBarcode(barcode) {
        // #fix minus quant scan — hanya benar kalau di-set oleh scan kali ini.
        this.__wmsPendingScanSave = false;
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
        if (isUUOnly) {
            try {
                const scannedPackages = await this.orm.searchRead(
                    "stock.package",
                    [["name", "=", barcode]],
                    ["yellow_tag"]
                );
                if (scannedPackages.length && scannedPackages[0].yellow_tag !== "ready") {
                    this._notifyYellowTagBlocked(barcode);
                    return;
                }
            } catch (error) {
                console.error("[DEBUG] Gagal mengecek yellow_tag package:", error);
            }
        }
        const stockTypeSnapshot = isUUOnly ? this._snapshotStockTypeQty() : null;
        const gratisSnapshot = this._snapshotStockTypeQty();

        await super._processBarcode(...arguments);

        if (isUUOnly) {
            const wasBlocked = await this._enforceUUStockType(stockTypeSnapshot);
            if (wasBlocked) {
                this.trigger("update");
                return;
            }
        }

        const wasGratisBlocked = await this._enforceGratisLocked(gratisSnapshot);
        if (wasGratisBlocked) {
            this.trigger("update");
            return;
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

        // #fix minus quant scan — simpan hasil scan pallet sekarang juga.
        //
        // Dijalankan setelah `_enforceUUStockType()`/`_enforceGratisLocked()`
        // supaya line yang ditolak guard dibuang selagi masih di client saja; kalau
        // disimpan lebih dulu, line yang kemudian dibuang akan tertinggal di DB.
        //
        // Menyimpan di sini juga membuat operasinya utuh: reservasi lama sudah
        // di-unlink di server, jadi kalau line barunya tidak ikut tersimpan,
        // pallet berakhir tanpa reservasi sama sekali.
        if (this.__wmsPendingScanSave) {
            this.__wmsPendingScanSave = false;
            if (this.linesToSave.length) {
                await this.save();
                wmsLog("scan:SAVED", { lines: this.currentState.lines.map(dbgLine) });
                this.trigger("update");
            }
        }

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