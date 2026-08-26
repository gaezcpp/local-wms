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

const WMS_SCAN_DEBUG = true;
const WMS_GROUPED_LINES_DEBUG = false;

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

function logOperationType(model, where) {
    const record = model.record || {};
    const config = model.config || {};
    console.log(`[WMS-SCANNER][operationType] ${where}`, {
        picking_type_id: getRelId(record.picking_type_id),
        picking_type_code: record.picking_type_code,
        picking_name: record.name,
        // wms_inherit_stock_barcode custom flags related to picking_type_id
        checker_out: record.checker_out,
        production_only: record.production_only,
        picking_type_bypass_entire_packs: record.picking_type_bypass_entire_packs,
        picking_type_entire_packs: record.picking_type_entire_packs,
        autofill_pack_qty: record.autofill_pack_qty,
        hide_zero_qty: record.hide_zero_qty,
        uu_only: record.uu_only,
        split_package: record.split_package,
        check_scan_pallet: record.check_scan_pallet,
        bulk_pallet_lot: record.bulk_pallet_lot,
        // core stock_barcode picking-type config (this.config)
        restrict_scan_source_location: config.restrict_scan_source_location,
        restrict_scan_dest_location: config.restrict_scan_dest_location,
        restrict_put_in_pack: config.restrict_put_in_pack,
        lines_need_to_be_packed: config.lines_need_to_be_packed,
        barcode_allow_extra_product: config.barcode_allow_extra_product,
    });
}

patch(BarcodePickingModel.prototype, {

    groupKey(line) {
        if (this.record.picking_type_bypass_entire_packs) {
            const packageId = getRelId(line.package_id);
            if (packageId) {
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
        console.log("[WMS-SCANNER][quant] _getSourceStockType", {
            domain,
            stockType,
        });
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

    // Dulu ada override `checkBarcode()` di sini. Core stock_barcode tidak
    // punya method bernama `checkBarcode` sama sekali (yang ada
    // `_checkBarcode(barcodeData)`, sinkron, dipanggil dari `_processBarcode`),
    // jadi override itu dead code: tidak pernah terpanggil, dan `super.checkBarcode`
    // di dalamnya akan melempar TypeError kalau sampai terpanggil.
    // `_cleanupPackageSplitRemainder()` tetap dijalankan dari `_processBarcode()`.

    _updateLineQty(line, args) {
        console.log("[WMS-SCANNER][moveLine] _updateLineQty", {
            id: line && line.id,
            virtual_id: line && line.virtual_id,
            move: getRelId(line && line.move_id),
            product: getRelId(line && line.product_id),
            qty_done_before: line && line.qty_done,
            args_qty_done: args && args.qty_done,
        });
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

    /**
     * Membuang line "surplus" hasil `_cleanupPackageSplitRemainder()` dari
     * daftar yang akan disimpan.
     *
     * BUG LAMA: method ini ditulis seolah menerima sebuah line dan
     * mengembalikan satu command. Signature core-nya `_getSaveLineCommand()`
     * TANPA argumen dan mengembalikan ARRAY command untuk seluruh
     * `linesToSave` (barcode_model.js). Akibatnya `args` selalu kosong, filter
     * `__isSurplusSkip` tidak pernah aktif, dan kalau sampai aktif ia
     * mengembalikan `null` -- lalu core `_getSaveCommand()` membaca
     * `commands.length` dan melempar TypeError, sehingga save gagal diam-diam.
     *
     * Penyaringan yang benar dilakukan di `linesToSave`, sama seperti
     * `_dropEmptySplitRemainders()`.
     */
    _getSaveLineCommand() {
        if (this.record.hide_zero_qty && this.linesToSave && this.linesToSave.length) {
            const skipped = this.linesToSave.filter((virtualId) => {
                const line = this.currentState.lines.find((l) => l.virtual_id === virtualId);
                // Line surplus selalu belum punya id (lihat isUnreservedSurplusLine),
                // jadi membuangnya tidak pernah meninggalkan qty basi di DB.
                return line && line.__isSurplusSkip && !line.id;
            });
            if (skipped.length) {
                wmsLog("saveCommand:SKIP-SURPLUS", { virtualIds: skipped });
                this.linesToSave = this.linesToSave.filter(
                    (virtualId) => !skipped.includes(virtualId)
                );
            }
        }
        return super._getSaveLineCommand(...arguments);
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

    /**
     * BUG LAMA: `_createCommandVals` dideklarasikan DUA KALI di object literal
     * patch ini. Kunci kedua menimpa yang pertama tanpa error, sehingga
     * `production_line_id` tidak pernah ikut terkirim saat create walaupun
     * `_getFieldToWrite()` menambahkannya. Kedua versi digabung di sini.
     */
    _createCommandVals(line) {
        const values = super._createCommandVals(...arguments);
        if (!values) {
            return values;
        }
        values.production_line_id = this._fieldToValue(line.production_line_id) || false;

        // `move_id` hanya dikirim kalau memang sengaja dipasang lewat
        // `__wmsMoveHint` (jalur _resetScannedPackageSourceLines). Untuk scan
        // biasa, core sengaja TIDAK mengirim move_id supaya server yang memilih
        // move lewat `_get_linkable_moves()` -- di situlah guard `gratis_locked`
        // milik wms_base_warehouse bekerja. Memaksa move_id untuk semua line
        // mem-bypass guard itu dan bisa menempelkan qty ke move gratis terkunci,
        // yang kemudian di-`_do_unreserve()` oleh `_action_assign()`.
        if (line && line.__wmsForcedMoveId && values.move_id === undefined) {
            values.move_id = line.__wmsForcedMoveId;
        }
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
            const stockType = quants.length ? quants[0].stock_type : false;
            console.log("[WMS-SCANNER][quant] _getPackageStockType", { packageId, stockType });
            return stockType;
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
                let lastDoLabel = _t("tidak ditemukan");
                try {
                    const lastDo = await this.orm.call(
                        "stock.package",
                        "get_last_do_sap",
                        [recPackage.id]
                    );
                    if (lastDo && lastDo.do_sap) {
                        lastDoLabel = `${lastDo.do_sap} (${lastDo.picking_name})`;
                    }
                } catch (error) {
                    console.error("[DEBUG] Gagal mengambil DO terakhir pallet:", error);
                }
                const userConfirmation = new Deferred();
                this.dialogService.add(ConfirmationDialog, {
                    title: _t("Peringatan: Pallet Tidak Terdaftar!"),
                    body: _t(
                        "Pallet %s tidak terdaftar di dokumen ini, transaksi pallet terakhir berada di DO %s",
                        recPackage.name,
                        lastDoLabel
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

        // #fix minus quant scan
        logOperationType(this, "_processPackage:start");
        console.log("[WMS-SCANNER][package] _processPackage:package", {
            id: recPackage && recPackage.id,
            name: recPackage && recPackage.name,
            location_id: recPackage && recPackage.location_id,
            contained_quant_ids: recPackage && recPackage.contained_quant_ids,
        });
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

        // await this._resetScannedPackageSourceLines(recPackage);

        this.__wmsPendingScanSave = Boolean(
            this.record.checker_out &&
                recPackage &&
                Array.isArray(recPackage.contained_quant_ids) &&
                recPackage.contained_quant_ids.length
        );

        this.__wmsScanDebug = true;
        this.__wmsScannedPackageId = recPackage ? recPackage.id : false;
        try {
            const res = await super._processPackage(...arguments);
            this._settleScannedPackageReset(recPackage);
            await this._rebalanceScannedPackageLots(recPackage);
            return res;
        } catch (error) {
            // Core berhenti di tengah jalan: batalkan antrian hapus supaya
            // line lama tidak ikut hilang bersama scan yang gagal.
            this._restoreResetLines();
            throw error;
        } finally {
            this.__wmsScanDebug = false;
            wmsLog("processPackage:END", {
                quants: this._debugPackageQuants(recPackage),
                linesAfter: this.currentState.lines.map(dbgLine),
                linesToSave: this.linesToSave,
                pendingUnlink: this.__wmsPendingUnlinkIds || [],
            });
        }
    },

    /**
     * Menentukan nasib antrian hapus yang dibuat `_resetScannedPackageSourceLines()`,
     * setelah core selesai memproses pallet.
     *
     * Core `_processPackage()` punya beberapa early-return yang tidak membentuk
     * line sama sekali (produk ekstra tidak diizinkan, pallet bukan sublokasi
     * source, pallet sudah ter-scan penuh, user membatalkan dialog). Kalau itu
     * yang terjadi, line lama TIDAK boleh dihapus -- kalau tidak, picking
     * ditinggal tanpa stock.move.line.
     */
    _settleScannedPackageReset(recPackage) {
        if (!(this.__wmsPendingUnlinkIds || []).length) {
            return;
        }
        const packageId = recPackage && recPackage.id;
        const replacements = (this.currentState.lines || []).filter(
            (line) => getRelId(line.package_id) === packageId && this.getQtyDone(line) > 0
        );
        if (!replacements.length) {
            wmsLog("reset:ROLLBACK", {
                alasan: "core tidak membentuk line pengganti -> pembatalan penghapusan",
                ids: this.__wmsPendingUnlinkIds,
            });
            this._restoreResetLines();
            return;
        }
        // Ada pengganti: wajib tersimpan pada scan ini juga, berapa pun nilai
        // `checker_out`, supaya DB tidak pernah berada dalam keadaan kosong.
        this.__wmsPendingScanSave = true;
    },

    /**
     * Membetulkan pembagian qty per LOT setelah core memproses satu pallet.
     *
     * BUG: `_processPackage()` core memutar tiap quant pallet dan mencari line
     * yang cocok lewat `_findLine()` -- yang saat scan pallet TIDAK membawa lot
     * (`barcodeData.lot` kosong), sehingga `_canOverrideTrackingNumber()` selalu
     * lolos dan pencocokan jatuh ke product + package saja. Pada pallet campur
     * lot, qty quant lot A karena itu bisa nyangkut di line lot B; cabang update
     * juga tidak mengirim lot quant-nya (`_convertDataToFieldsParams()` hanya
     * mengisi `lot_id` kalau `args.lot` ada), jadi lot line tidak ikut berubah.
     * Total scan kelihatan benar, reservasi per quant kacau, dan errornya baru
     * muncul saat validate sebagai stok negatif.
     *
     * Selain itu core memakai `quant.quantity` mentah, tanpa memperhitungkan
     * bagian pallet yang sudah dibooking dokumen lain, jadi scan bisa merebut
     * qty milik picking lain dan membuat move melebihi demand-nya.
     *
     * Method ini tidak menduplikasi alur core: ia hanya memeriksa hasil akhir
     * dan membagi ulang HANYA kalau ada lot yang melebihi kapasitasnya, dengan
     * kapasitas = isi quant - reservasi dokumen lain. Kalau core sudah benar,
     * method ini tidak melakukan apa-apa.
     */
    async _rebalanceScannedPackageLots(recPackage) {
        if (
            !recPackage ||
            !Array.isArray(recPackage.contained_quant_ids) ||
            !recPackage.contained_quant_ids.length
        ) {
            return;
        }
        // Pallet yang ditangani core sebagai entire-pack line memakai jalur lain
        // (`_updateLineQty()` per line dengan reservasinya sendiri) yang memang
        // sudah lot-aware -- jangan diutak-atik.
        if (
            this.packageLines.some((packageLine) =>
                this._isPackageInPackage(packageLine.package_id, recPackage)
            )
        ) {
            return;
        }

        const quants = [];
        for (const quantId of recPackage.contained_quant_ids) {
            let quant = false;
            try {
                quant = this.cache.getRecord("stock.quant", quantId);
            } catch (error) {
                quant = false;
            }
            if (quant && quant.lot_id) {
                quants.push(quant);
            }
        }
        if (!quants.length) {
            return; // pallet tanpa lot: tidak ada yang bisa tertukar
        }

        for (const productId of new Set(quants.map((quant) => quant.product_id))) {
            await this._rebalancePackageProductLots(recPackage, productId, quants);
        }
    },

    async _rebalancePackageProductLots(recPackage, productId, allQuants) {
        const quants = allQuants.filter((quant) => quant.product_id === productId);
        if (new Set(quants.map((quant) => quant.lot_id)).size < 2) {
            return; // satu lot saja -> tidak mungkin tertukar
        }

        const rounding = 0.0000001;
        const lines = this.currentState.lines
            .filter(
                (line) =>
                    getRelId(line.package_id) === recPackage.id &&
                    getRelId(line.product_id) === productId
            )
            // Line yang sudah punya id (suggestion dari server) didahulukan.
            .sort((a, b) => (b.id ? 1 : 0) - (a.id ? 1 : 0));
        if (!lines.length) {
            return;
        }

        // Aturannya: scan pallet mengambil SELURUH isi pallet, tapi tiap lot
        // dibatasi qty lot itu sendiri di pallet ini.
        const targetByLot = new Map();
        for (const quant of quants) {
            targetByLot.set(quant.lot_id, (targetByLot.get(quant.lot_id) || 0) + quant.quantity);
        }

        const assignedByLot = new Map();
        for (const line of lines) {
            const lotId = getRelId(line.lot_id);
            assignedByLot.set(lotId, (assignedByLot.get(lotId) || 0) + (this.getQtyDone(line) || 0));
        }
        const alreadyCorrect = [...targetByLot.entries()].every(
            ([lotId, target]) => Math.abs((assignedByLot.get(lotId) || 0) - target) < rounding
        );
        if (alreadyCorrect && assignedByLot.size === targetByLot.size) {
            return; // pembagian core sudah sesuai isi pallet
        }

        wmsLog("rebalanceLot", {
            pallet: recPackage.name,
            product: productId,
            sebelum: [...assignedByLot.entries()],
            sesudah: [...targetByLot.entries()],
        });

        // Terapkan: satu line per lot sebesar isi lot itu, line lain dinolkan.
        for (const [lotId, target] of targetByLot.entries()) {
            const lotLines = lines.filter((line) => getRelId(line.lot_id) === lotId);
            if (lotLines.length) {
                lotLines[0].qty_done = target;
                this._markLineAsDirty(lotLines[0]);
                for (const extra of lotLines.slice(1)) {
                    extra.qty_done = 0;
                    this._markLineAsDirty(extra);
                }
            } else if (target > rounding) {
                const quant = quants.find((q) => q.lot_id === lotId);
                const fieldsParams = this._convertDataToFieldsParams({
                    product: this.cache.getRecord("product.product", productId),
                    quantity: target,
                    lot: this.cache.getRecord("stock.lot", lotId),
                    package: quant.package_id,
                    resultPackage: quant.package_id,
                    owner: quant.owner_id,
                    srcLocation: quant.location_id,
                });
                await this._createNewLine({ fieldsParams });
            }
        }
        // Line dengan lot yang sudah tidak ada isinya di pallet ini.
        for (const line of lines) {
            if (!targetByLot.has(getRelId(line.lot_id))) {
                line.qty_done = 0;
                this._markLineAsDirty(line);
            }
        }

        // Informasi saja -- qty tetap diambil sesuai isi pallet, tapi operator
        // perlu tahu kalau sebagian pallet ini masih dipegang dokumen lain.
        const bookedElsewhere = quants.reduce((sum, quant) => {
            if (typeof quant.reserved_quantity !== "number") {
                return sum;
            }
            const own = lines
                .filter((line) => getRelId(line.lot_id) === quant.lot_id)
                .reduce((total, line) => total + (line.reserved_uom_qty || 0), 0);
            return sum + Math.max(0, quant.reserved_quantity - own);
        }, 0);
        if (bookedElsewhere > rounding) {
            this.notification(
                _t(
                    "Pallet %s: %s dari isinya masih ter-reserve di dokumen lain dan akan dilepas saat transfer ini divalidasi.",
                    recPackage.name,
                    bookedElsewhere
                ),
                { type: "warning" }
            );
        }
        this.trigger("update");
    },

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
     * Melepas line reservasi lama milik pallet yang di-scan supaya core bisa
     * membentuk ulang line-nya dari quant (#fix minus quant scan).
     *
     * BUG LAMA: method ini memanggil `this.orm.unlink("stock.move.line", ...)`
     * secara langsung, SEBELUM line pengganti ada di mana pun selain memori
     * browser, dan tanpa transaksi apa pun yang mengikat keduanya. Begitu core
     * `_processPackage()` berhenti lewat salah satu early-return-nya, atau
     * `save()` tidak pernah jalan (dulu hanya dijadwalkan kalau `checker_out`
     * true), picking ditinggal TANPA stock.move.line sama sekali -- line lama
     * sudah terhapus permanen, line baru tidak pernah tersimpan.
     *
     * Sekarang penghapusan ditunda: id-nya diantrikan di `__wmsPendingUnlinkIds`
     * beserta snapshot line-nya, dan baru benar-benar di-unlink oleh
     * `_flushPendingLineUnlink()` tepat sebelum RPC save yang membawa line
     * pengganti. Kalau ternyata tidak ada pengganti, `_restoreResetLines()`
     * mengembalikan line lama ke state dan tidak ada yang terhapus.
     */
    async _resetScannedPackageSourceLines(recPackage) {
        this.__wmsMoveHint = null;
        this.__wmsResetSnapshot = null;
        this.__wmsPendingUnlinkIds = [];
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

        if (
            this.packageLines.some((packageLine) =>
                this._isPackageInPackage(packageLine.package_id, recPackage)
            )
        ) {
            wmsLog("reset:SKIP", "pallet ditangani core sebagai entire-pack line");
            return;
        }

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

        // Core menyusun daftar produk yang boleh masuk dari `currentState.lines`
        // (`barcode_allow_extra_product`, barcode_picking_model.js). Kalau line
        // ini dilepas duluan, produknya bisa hilang dari daftar itu dan core
        // menolak SELURUH pallet dengan "This package contains extra products"
        // -- padahal line lama sudah terlanjur diantrikan untuk dihapus.
        // Untuk konfigurasi itu, biarkan core memakai line lama apa adanya.
        if (!this.config.barcode_allow_extra_product) {
            const keptProductIds = new Set(
                this.currentState.lines
                    .filter((line) => !linesToReset.includes(line))
                    .map((line) => getRelId(line.product_id))
            );
            const droppedProductIds = [
                ...new Set(linesToReset.map((line) => getRelId(line.product_id))),
            ].filter((productId) => productId && !keptProductIds.has(productId));
            if (droppedProductIds.length) {
                wmsLog("reset:SKIP", {
                    alasan:
                        "barcode_allow_extra_product=false dan reset akan " +
                        "menghapus satu-satunya line untuk produk ini",
                    droppedProductIds,
                });
                return;
            }
        }

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

        // Tidak ada `orm.unlink()` di sini -- lihat docstring. Yang dilakukan
        // hanyalah melepas line dari state client dan mengantrikan id-nya.
        const idsToReset = linesToReset.map((line) => line.id).filter(Boolean);
        this.__wmsResetSnapshot = {
            lines: linesToReset.slice(),
            selectedLineVirtualId: this.selectedLineVirtualId,
        };
        this.__wmsPendingUnlinkIds = idsToReset;
        wmsLog("reset:QUEUE-UNLINK", {
            model: "stock.move.line",
            ids: idsToReset,
            catatan: "penghapusan ditunda sampai line pengganti siap disimpan",
        });

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

    /**
     * Mengembalikan line yang sudah dilepas `_resetScannedPackageSourceLines()`
     * ke `currentState` dan membatalkan antrian hapus. Dipakai ketika ternyata
     * tidak ada line pengganti yang terbentuk. Karena penghapusan ditunda,
     * pembatalan ini murni operasi di client -- data di DB tidak pernah hilang.
     */
    _restoreResetLines() {
        const snapshot = this.__wmsResetSnapshot;
        this.__wmsResetSnapshot = null;
        this.__wmsPendingUnlinkIds = [];
        this.__wmsMoveHint = null;
        if (!snapshot || !this.currentState) {
            return false;
        }
        for (const line of snapshot.lines) {
            if (!this.currentState.lines.includes(line)) {
                this.currentState.lines.push(line);
            }
        }
        if (!this.selectedLineVirtualId && snapshot.selectedLineVirtualId) {
            this.selectedLineVirtualId = snapshot.selectedLineVirtualId;
        }
        wmsLog("reset:RESTORED", { dikembalikan: snapshot.lines.map(dbgLine) });
        return true;
    },

    /**
     * Benar-benar menghapus line lama yang sudah diantrikan. Sengaja dipanggil
     * tepat sebelum RPC save yang membawa line penggantinya (lihat
     * `__wmsSaveOnce()`), sehingga jendela waktu "DB tanpa line" mengecil
     * menjadi satu pasang RPC, dan penghapusan tidak pernah terjadi kalau tidak
     * ada yang akan disimpan.
     */
    async _flushPendingLineUnlink() {
        const ids = this.__wmsPendingUnlinkIds || [];
        if (!ids.length) {
            return;
        }
        this.__wmsPendingUnlinkIds = [];
        this.__wmsResetSnapshot = null;
        wmsLog("reset:UNLINK", { model: "stock.move.line", ids });
        await this.orm.unlink("stock.move.line", ids);
    },

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
        console.log("[WMS-SCANNER][moveLine] updateLine:start", {
            id: line && line.id,
            virtual_id: line && line.virtual_id,
            move: getRelId(line && line.move_id),
            product: getRelId(line && line.product_id),
            qty_done: line && line.qty_done,
            reserved_uom_qty: line && line.reserved_uom_qty,
            lot: getRelId(line && line.lot_id),
            package_id: getRelId(line && line.package_id),
            result_package_id: getRelId(line && line.result_package_id),
            location_id: getRelId(line && line.location_id),
            state: line && line.state,
            args,
        });
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
        console.log("[WMS-SCANNER][moveLine] _createNewLine:start", {
            fieldsParams: (params && params.fieldsParams) || null,
        });
        const newLine = await super._createNewLine(...arguments);
        console.log("[WMS-SCANNER][moveLine] _createNewLine:created", {
            id: newLine && newLine.id,
            virtual_id: newLine && newLine.virtual_id,
            move: getRelId(newLine && newLine.move_id),
            product: getRelId(newLine && newLine.product_id),
            qty_done: newLine && newLine.qty_done,
            lot: getRelId(newLine && newLine.lot_id),
            package_id: getRelId(newLine && newLine.package_id),
            result_package_id: getRelId(newLine && newLine.result_package_id),
        });
        const hint = this.__wmsMoveHint;
        if (hint && newLine && !getRelId(newLine.move_id)) {
            const productId = getRelId(newLine.product_id);
            if (
                getRelId(newLine.package_id) === hint.packageId &&
                hint.moveByProduct.has(productId)
            ) {
                newLine.move_id = hint.moveByProduct.get(productId);
                // Penanda eksplisit: hanya line inilah yang boleh mengirim
                // `move_id` ke server (lihat `_createCommandVals`).
                newLine.__wmsForcedMoveId = newLine.move_id;
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

    async splitLine(line) {
        const newLine = await super.splitLine(...arguments);
        if (newLine) {
            // Penanda: HANYA line hasil split inilah yang boleh dibuang oleh
            // `_dropEmptySplitRemainders()`. Tanpa penanda ini, setiap line baru
            // yang qty_done-nya masih 0 -- termasuk line produk baru yang sah,
            // yang menunggu scan lot pada operasi dengan use_existing_lots /
            // use_create_lots (`_incrementTrackedLine()` = false) -- ikut
            // dibuang, tidak pernah tersimpan, tidak pernah dapat `id`, dan
            // `MainComponent.onOpenProductPage()` crash saat membuka line itu.
            newLine.__wmsSplitRemainder = true;
            if ("bag_qty" in newLine) {
                newLine.bag_qty = 0;
            }
            if ("pallet_qty" in newLine) {
                newLine.pallet_qty = 0;
            }
            console.log("[WMS-SCANNER][moveLine] splitLine:reset-pack-qty", {
                virtual_id: newLine.virtual_id,
                bag_qty: newLine.bag_qty,
                pallet_qty: newLine.pallet_qty,
                reserved_uom_qty: newLine.reserved_uom_qty,
            });
        }
        return newLine;
    },

    _getSaveCommand() {
        const command = super._getSaveCommand();
        wmsLog(
            "saveCommand",
            command && command.params ? command.params.write_vals : "(tidak ada yang disimpan)"
        );
        return command;
    },

    save() {
        const previous = this.__wmsSaveChain || Promise.resolve();
        const current = previous.catch(() => {}).then(() => this.__wmsSaveOnce());
        this.__wmsSaveChain = current;
        return current;
    },

    /**
     * Core's `splitLine()` marks BOTH the original line and the new "remainder" line
     * dirty (see splitLine() override above). If the remainder line never received any
     * physical qty (`qty_done` still 0 — nothing was scanned into it, it only carries
     * the leftover `reserved_uom_qty`), saving it anyway creates an empty
     * `stock.move.line` with no lot/package, which then fails server-side validation
     * (e.g. "Destination Package belum diisi"). Such a line has nothing worth
     * persisting yet, so drop it from `linesToSave` — it stays in `currentState.lines`
     * as a client-side placeholder for the remaining demand, and will be saved for
     * real once the user actually scans something into it.
     *
     * PENTING: filternya HARUS dibatasi pada line bertanda `__wmsSplitRemainder`
     * (dipasang di `splitLine()`). Sebelumnya filter ini mengenai SEMUA line baru
     * ber-qty 0, sehingga line produk baru hasil scan pada operasi bertracking lot
     * (qty_done sengaja 0 sampai lot di-scan, lihat `_incrementTrackedLine()`)
     * ikut dibuang dari `linesToSave`. Line itu jadi tidak pernah tersimpan,
     * `line.id` tetap undefined, dan core `onOpenProductPage()` melempar
     * "Cannot read properties of undefined (reading 'id')".
     */
    _dropEmptySplitRemainders() {
        if (!this.linesToSave || !this.linesToSave.length || !this.currentState) {
            return;
        }
        const emptyVirtualIds = this.linesToSave.filter((virtualId) => {
            const line = this.currentState.lines.find((l) => l.virtual_id === virtualId);
            return line && line.__wmsSplitRemainder && !line.id && !line.qty_done;
        });
        if (emptyVirtualIds.length) {
            console.log("[WMS-SCANNER][moveLine] dropEmptySplitRemainders", {
                virtualIds: emptyVirtualIds,
            });
            this.linesToSave = this.linesToSave.filter(
                (vId) => !emptyVirtualIds.includes(vId)
            );
        }
    },

    async __wmsSaveOnce() {
        this._dropEmptySplitRemainders();
        // Baru di sini line lama benar-benar dihapus, dan hanya kalau ada line
        // pengganti yang ikut terkirim pada RPC save berikutnya. Kalau tidak ada
        // yang perlu disimpan, antrian dibiarkan utuh -- tidak ada yang hilang.
        if (this.linesToSave && this.linesToSave.length) {
            await this._flushPendingLineUnlink();
        }
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
        console.log("[WMS-SCANNER][scan] _processBarcode:start", { barcode });
        logOperationType(this, "_processBarcode:start");
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
                // Scan ditolak -> line pengganti sudah dibuang lagi, jadi line
                // lama tidak boleh ikut terhapus.
                this._restoreResetLines();
                this.trigger("update");
                return;
            }
        }

        const wasGratisBlocked = await this._enforceGratisLocked(gratisSnapshot);
        if (wasGratisBlocked) {
            this._restoreResetLines();
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

        if (this.__wmsPendingScanSave) {
            this.__wmsPendingScanSave = false;
            if (this.linesToSave.length) {
                await this.save();
                wmsLog("scan:SAVED", { lines: this.currentState.lines.map(dbgLine) });
                this.trigger("update");
            }
        }

        // Jaring pengaman: antrian hapus tidak boleh menyeberang ke scan
        // berikutnya. Kalau sampai sini masih ada isinya, berarti tidak ada save
        // yang membawa line pengganti -> batalkan, jangan hapus apa pun.
        if ((this.__wmsPendingUnlinkIds || []).length) {
            wmsLog("reset:ROLLBACK", {
                alasan: "scan selesai tanpa save yang membawa line pengganti",
                ids: this.__wmsPendingUnlinkIds,
            });
            this._restoreResetLines();
            this.trigger("update");
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