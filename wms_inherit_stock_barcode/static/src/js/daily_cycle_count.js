import MainComponent from "@stock_barcode/components/main";
import { patch } from "@web/core/utils/patch";
import { ApplyQuantDialog } from "@stock_barcode/components/apply_quant_dialog";
import BarcodeModel from "@stock_barcode/models/barcode_model";
import { _t } from "@web/core/l10n/translation";

export default class BarcodeDailyCountModel extends BarcodeModel {
    constructor(params) {
        super(...arguments);
        this.lineModel = this.resModel;
        this.validateMessage = _t("The inventory count has been updated");
        this.validateMethod = "action_validate";
        this.deleteLineMethod = this.validateMethod;
    }

    async validate() {
        return this.apply();
    }

    apply() {
        if (this.checkBeforeApply()) {
            return this._apply();
        }
    }

    checkBeforeApply() {
        if (this.applyOn === 0) {
            const message = _t("There is nothing to apply in this page.");
            this.notification(message, { type: "warning" });
            return false;
        }
        return true;
    }

    async _apply(context = {}) {
        await this.save();
        const recordIds = this.pageLines.map((line) => line.id);
        const action = await this.orm.call("daily.cycle.count", "action_validate", [recordIds]);
        const notifyAndGoAhead = (res) => {
            if (res && res.special) {
                return this.trigger("refresh");
            }
            this.notification(this.validateMessage, { type: "success" });
            this.trigger("history-back");
            // this.action.doAction("wms_inherit_stock_barcode.daily_cycle_count_action", {
            //     clearBreadcrumbs: true, // Opsional: Membersihkan jejak "back" agar rapi
            // });
        };
        if (action && action.res_model) {
            return this.action.doAction(action, { onClose: notifyAndGoAhead });
        }
        notifyAndGoAhead();
    }

    get applyOn() {
        return this.pageLines.filter((line) => line.inventory_quantity_set).length;
    }

    get barcodeInfo() {
        return {
            class: "scan_package",
            message: _t("Scan a package to count"),
            icon: "archive",
        };
    }

    get displayByUnitButton() {
        return true;
    }

    displaySetButton(line) {
        const isSelected = this.selectedLineVirtualId === line.virtual_id;
        return (
            isSelected &&
            (this.showQuantityCount ||
                (line.product_id.tracking === "serial" && this.getlotName(line)))
        );
    }

    setData(data) {
        this.userId = data.data.user_id;
        this.showQuantityCount = data.data.show_quantity_count || true;
        this.countEntireLocation = false;
        super.setData(...arguments);
        const companies = data.data.records["res.company"];
        this.companyIds = companies.map((company) => company.id);
        this.lineFormViewId = data.data.line_view_id;
    }

    get displayApplyButton() {
        return true;
    }

    getQtyDone(line) {
        return line.inventory_quantity_set ? line.inventory_quantity : 0;
    }

    getQtyDemand(line) {
        return this.showQuantityCount ? line.quantity : 0;
    }

    getActionRefresh(newId) {
        const action = super.getActionRefresh(newId);
        action.params.res_id = this.currentState.lines.map((l) => l.id);
        if (newId) {
            action.params.res_id.push(newId);
        }
        return action;
    }

    get highlightValidateButton() {
        return this.applyOn > 0 && this.applyOn === this.pageLines.length;
    }

    IsNotSet(line) {
        return !line.inventory_quantity_set;
    }

    lineCanBeDeleted(line) {
        return line.inventory_quantity_set && this.getQtyDone(line) === 0;
    }

    lineIsFaulty(line) {
        if (this.showQuantityCount) {
            return line.inventory_quantity_set && line.inventory_quantity !== line.quantity;
        }
        return false;
    }

    lineIsTracked(line) {
        const lineIsTracked = super.lineIsTracked(...arguments);
        if (lineIsTracked && line.product_id.tracking === "serial") {
            return (
                this.getlotName(line) ||
                (this.getQtyDone(line) <= 1 && this.getQtyDemand(line) <= 1)
            );
        }
        return lineIsTracked;
    }

    get printButtons() {
        return [
            {
                name: _t("Print Inventory"),
                class: "o_print_inventory",
                action: "stock.action_report_inventory",
            },
        ];
    }
    
    _getPrintOptions() {
        const options = super._getPrintOptions();
        const quantsToPrint = this.pageLines.filter((quant) => quant.inventory_quantity_set);
        if (quantsToPrint.length === 0) {
            return { warning: _t("There is nothing to print in this page.") };
        }
        options.additionalContext = { active_ids: quantsToPrint.map((quant) => quant.id) };
        return options;
    }

    get recordIds() {
        return this.currentState.lines.map((l) => l.id);
    }

    toggleAsCounted(line) {
        line.inventory_quantity = 0;
        line.inventory_quantity_set = !line.inventory_quantity_set;
        this._markLineAsDirty(line);
        this.trigger("update");
    }

    updateLineQty(virtualId, qty = 1) {
        this.actionMutex.exec(() => {
            const line = this.pageLines.find((l) => l.virtual_id === virtualId);
            this.updateLine(line, { inventory_quantity: qty });
            this.trigger("update");
        });
    }

    _getCommands() {
        return Object.assign(super._getCommands(), {
            OBTAPPLY: this.apply.bind(this),
        });
    }

    _getMissingRecordsParams() {
        const params = super._getMissingRecordsParams();
        params.fetch_quants = false; 
        return params;
    }

    _getNewLineDefaultContext() {
        return {
            default_company_id: this.companyIds[0],
            default_location_id: this._defaultLocation().id,
            default_inventory_quantity: 1,
            default_user_id: this.userId,
            inventory_mode: true,
            display_default_code: false,
            hide_qty_to_count: !this.showQuantityCount,
        };
    }

    _createCommandVals(line) {
        const values = {
            dummy_id: line.virtual_id,
            company_id: line.company_id,
            quantity: line.inventory_quantity,
            inventory_date: line.inventory_date,
            inventory_quantity: line.inventory_quantity,
            inventory_quantity_set: line.inventory_quantity_set,
            location_id: line.location_id,
            lot_id: line.lot_id,
            lot_name: line.lot_name,
            package_id: line.package_id,
            product_id: line.product_id,
            product_uom_id: line.product_uom_id,
            user_id: this.userId,
            pack_unit_id: line.uom_bag_id,
            pack_qty: line.bag_qty,
            uom_pallet_id: line.uom_pallet_id,
            pallet_qty: line.pallet_qty,
            stock_type: line.stock_type,
            state: line.state || 'draft',
        };
        for (const [key, value] of Object.entries(values)) {
            values[key] = this._fieldToValue(value);
        }
        return values;
    }

    async _createNewLine(params) {
        const product = params.fieldsParams.product_id;
        if (!product.is_storable) {
            const productName =
                (product.default_code ? `[${product.default_code}] ` : "") + product.display_name;
            const message = _t(
                "%s can't be inventoried. Only storable products can be inventoried.",
                productName
            );
            this.notification(message, { type: "warning" });
            return false;
        }
        const location_id = this.location.id;
        const { lot_id, lot_name, package_id } = params.fieldsParams;
        let existingRecords = [];
        
        const cachedDict = this.cache.dbIdCache["daily.cycle.count"] || {};
        for (const id of Object.keys(cachedDict)) {
            const record = this.cache.getRecord("daily.cycle.count", Number(id));
            if (record.product_id.id === product.id && record.location_id.id === location_id) {
                if ((!lot_id || record.lot_id?.id === lot_id) && (!package_id || record.package_id?.id === package_id)) {
                    existingRecords.push(record);
                }
            }
        }

        if (
            existingRecords.length === 1 &&
            (product.tracking === "none" ||
                params.fieldsParams.lot_name ||
                params.fieldsParams.lot_id)
        ) {
            const inventory_quantity =
                product.tracking === "lot"
                    ? existingRecords[0].quantity
                    : params.fieldsParams.inventory_quantity || 1;
            params.fieldsParams = Object.assign({}, params.fieldsParams, { inventory_quantity });
        }
        let newLine = false;
        if (existingRecords.length) {
            const lineIds = this.currentState.lines.map((l) => l.id);
            for (const record of existingRecords) {
                if (lineIds.includes(record.id)) {
                    continue;
                }
                const lineParams = {
                    fieldsParams: Object.assign({}, record, params.fieldsParams),
                };
                const newlyCreatedLine = await super._createNewLine(lineParams);
                this.selectedLineVirtualId = newlyCreatedLine.virtual_id;
                newLine = newLine || newlyCreatedLine;
                const lineWithOriginalValues = Object.assign({}, newlyCreatedLine, {
                    inventory_date: record.inventory_date,
                    inventory_quantity: record.inventory_quantity,
                    inventory_quantity_set: record.inventory_quantity_set,
                    quantity: record.quantity,
                    user_id: record.user_id,
                });
                this.initialState.lines.push(lineWithOriginalValues);
            }
        } else {
            newLine = await super._createNewLine(params);
        }
        return newLine;
    }

    _convertDataToFieldsParams(args) {
        const params = {};
        if (args.packaging && args.product.tracking === "serial") {
            params.inventory_quantity = 1;
        } else if (args.quantity) {
            params.inventory_quantity = args.quantity;
        }
        args.lot && (params.lot_id = args.lot);
        args.lotName && (params.lot_name = args.lotName);
        args.package && (params.package_id = args.package);
        args.product && (params.product_id = args.product);
        args.product && args.product.uom_id && (params.product_uom_id = args.product.uom_id);
        args.packaging && (params.packaging = args.packaging);
        return params;
    }

    _getNewLineDefaultValues(fieldsParams) {
        const defaultValues = super._getNewLineDefaultValues(...arguments);
        Object.assign(defaultValues, {
            inventory_date: new Date().toISOString().slice(0, 10),
            inventory_quantity: 0,
            quantity: (fieldsParams && fieldsParams.quantity) || 0,
            user_id: this.userId,
            state: 'draft',
        });
        if (fieldsParams.quantity === undefined || fieldsParams.inventory_quantity) {
            defaultValues.inventory_quantity_set = true;
        }
        return defaultValues;
    }

    _getFieldToWrite() {
        return [
            "inventory_date",
            "inventory_quantity",
            "inventory_quantity_set",
            "user_id",
            "location_id",
            "lot_name",
            "lot_id",
            "package_id",
            "dummy_id",
            "product_id",
            "product_uom_id",
            "uom_bag_id",
            "uom_pallet_id",
            "bag_qty",
            "pallet_qty",
            "bag_dummy_qty",
            "pallet_dummy_qty",
            "stock_type",
            "po_sap_id",
            "company_id",
            "state"
        ];
    }

    _getSaveCommand() {
        const commands = this._getSaveLineCommand();
        if (commands.length) {
            return {
                route: "/stock_barcode/save_barcode_data",
                params: {
                    model: this.resModel,
                    res_id: false,
                    write_field: false,
                    write_vals: commands,
                },
            };
        }
        return {};
    }

    _groupSublines() {
        const groupedLine = super._groupSublines(...arguments);
        const hasAtLeastOneSetSubline = groupedLine.lines.find((l) => l.inventory_quantity_set);
        groupedLine.inventory_quantity = groupedLine.totalQtyDone;
        groupedLine.quantity = groupedLine.totalQtyDemand;
        groupedLine.inventory_quantity_set = hasAtLeastOneSetSubline;
        return groupedLine;
    }

    _lineIsNotComplete(line) {
        return line.inventory_quantity === 0;
    }

    async _processPackage(barcodeData) {
        const { packageType, packageName } = barcodeData;
        let recPackage = barcodeData.package;
        this.lastScanned.packageId = false;
        
        if (!recPackage && !packageType && !packageName) {
            const message = _t("Invalid scan. Please scan a package.");
            this.notification(message, { type: "danger" });
            barcodeData.stopped = true;
            return;
        }

        const currentLine = this.selectedLine || this.lastScannedLine;
        if (
            currentLine && currentLine.package_id &&
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
                if (packageName) { valueList.name = packageName; }
                if (packageType) { valueList.package_type_id = packageType.id; }
                const newPackageData = await this.orm.call(
                    "stock.package", "action_create_from_barcode", [valueList]
                );
                this.cache.setCache(newPackageData);
                recPackage = newPackageData["stock.package"][0];
            }
        }
        
        if (!recPackage && packageName) {
            const currentLine = this.selectedLine || this.lastScannedLine;
            if (currentLine && !currentLine.package_id) {
                const newPackageData = await this.orm.call(
                    "stock.package", "action_create_from_barcode", [{ name: packageName }]
                );
                this.cache.setCache(newPackageData);
                recPackage = newPackageData["stock.package"][0];
            }
        }

        if (!recPackage) {
             return;
        }

        const quantRecordsRaw = await this.orm.searchRead(
            "stock.quant",
            [["package_id", "=", recPackage.id]],
            [
                "product_id", "lot_id", "quantity", "product_uom_id", 
                "uom_bag_id", "uom_pallet_id", "bag_qty", "pallet_qty", 
                "bag_dummy_qty", "pallet_dummy_qty", "stock_type", "po_sap_id",
                "company_id", "location_id",
            ]
        );

        if (!quantRecordsRaw.length) {
            const message = _t("No items found in pallet %s.", recPackage.name);
            this.notification(message, { type: "warning" });
            barcodeData.stopped = true;
            return;
        }

        const cleanM2O = (record) => {
            const cleaned = { ...record };
            for (const key in cleaned) {
                if (Array.isArray(cleaned[key]) && cleaned[key].length === 2 && typeof cleaned[key][0] === "number") {
                    cleaned[key] = cleaned[key][0];
                }
            }
            return cleaned;
        };

        const quantRecords = quantRecordsRaw.map(cleanM2O);

        const productIds = [];
        const lotIds = [];
        const locationIds = [];
        const uomIds = new Set();
        
        quantRecords.forEach(q => {
            if (q.product_id) productIds.push(q.product_id);
            if (q.lot_id) lotIds.push(q.lot_id);
            if (q.location_id) locationIds.push(q.location_id);
            if (q.product_uom_id) uomIds.add(q.product_uom_id);
            if (q.uom_bag_id) uomIds.add(q.uom_bag_id);
            if (q.uom_pallet_id) uomIds.add(q.uom_pallet_id);
        });

        if (locationIds.length) {
            const locations = await this.orm.searchRead("stock.location", [["id", "in", [...new Set(locationIds)]]], []);
            this.cache.setCache({ "stock.location": locations.map(cleanM2O) });
        }

        if (productIds.length) {
            const products = await this.orm.searchRead("product.product", [["id", "in", [...new Set(productIds)]]], []);
            const cleanedProducts = products.map(cleanM2O);
            cleanedProducts.forEach(p => {
                if (p.uom_id) uomIds.add(p.uom_id);
            });
            this.cache.setCache({ "product.product": cleanedProducts });
        }
        
        if (uomIds.size) {
            const uoms = await this.orm.searchRead("uom.uom", [["id", "in", [...uomIds]]], []);
            this.cache.setCache({ "uom.uom": uoms.map(cleanM2O) });
        }

        if (lotIds.length) {
            const lots = await this.orm.searchRead("stock.lot", [["id", "in", [...new Set(lotIds)]]], []);
            this.cache.setCache({ "stock.lot": lots.map(cleanM2O) });
        }

        let alreadyExisting = 0;
        for (const line of this.pageLines) {
            if (line.package_id && line.package_id.id === recPackage.id && this.getQtyDone(line) > 0) {
                alreadyExisting++;
            }
        }
        if (alreadyExisting === quantRecords.length) {
            barcodeData.error = _t("This package is already completely scanned.");
            return;
        }
        
        // Memasukkan data ke UI Line
        for (const quant of quantRecords) {
            const product = this.cache.getRecord("product.product", quant.product_id);
            const searchLineParams = Object.assign({}, barcodeData, { product });
            if (quant.lot_id) {
                searchLineParams.lot = quant.lot_id;
            }
            
            const currentLine = this._findLine(searchLineParams);
            
            // Objek data kustom yang ingin disuplai ke model daily.cycle.count
            const customFieldsData = {
                location_id: quant.location_id || false,
                product_uom_id: quant.product_uom_id || false,
                uom_bag_id: quant.uom_bag_id || false,
                uom_pallet_id: quant.uom_pallet_id || false,
                bag_qty: quant.bag_qty || 0,
                pallet_qty: quant.pallet_qty || 0,
                bag_dummy_qty: quant.bag_dummy_qty || 0,
                pallet_dummy_qty: quant.pallet_dummy_qty || 0,
                stock_type: quant.stock_type || false,
                po_sap_id: quant.po_sap_id || false,
                company_id: quant.company_id || false,
                state: 'draft'
            };

            if (currentLine) {
                const fieldsParams = this._convertDataToFieldsParams({
                    quantity: quant.quantity,
                    lot: quant.lot_id || false,
                    package: recPackage,
                });
                Object.assign(fieldsParams, customFieldsData);
                await this.updateLine(currentLine, fieldsParams);
            } else {
                const fieldsParams = this._convertDataToFieldsParams({
                    product: product,
                    quantity: quant.quantity,
                    lot: quant.lot_id || false,
                    package: recPackage,
                });
                Object.assign(fieldsParams, customFieldsData);
                const newLine = await this._createNewLine({ fieldsParams });
                
                if (newLine) {
                    newLine.inventory_quantity = quant.quantity; 
                    newLine.inventory_quantity_set = true;
                    // Inject langsung ke UI record agar terbaca saat disimpan
                    Object.assign(newLine, customFieldsData);
                }
            }
        }
        barcodeData.stopped = true;
        this.selectedLineVirtualId = false;
        this.lastScanned.packageId = recPackage.id;
        this.trigger("update");
    }

    _updateLineQty(line, args) {
        if (args.quantity) {
            line.quantity = args.quantity;
        }
        if (args.inventory_quantity) {
            if (args.uom) {
                const lineUOM = line.product_uom_id;
                if (args.uom.factor !== lineUOM.factor) {
                    const factor = args.uom.factor / lineUOM.factor;
                    args.inventory_quantity = args.inventory_quantity * factor;
                    args.uom = lineUOM;
                }
            }
            line.inventory_quantity += args.inventory_quantity;
            if (line.inventory_quantity > 0) {
                args.inventory_quantity_set = true;
            }
            line.inventory_quantity_set = this.countEntireLocation
                ? args.inventory_quantity_set
                : true;
            if (line.product_id.tracking === "serial" && (line.lot_name || line.lot_id)) {
                line.inventory_quantity = Math.max(0, Math.min(1, line.inventory_quantity));
            }
        }
    }

    async _updateLotName(line, lotName) {
        if (line.lot_name === lotName) {
            return Promise.resolve();
        }
        line.lot_name = lotName;
        const cachedDict = this.cache.dbIdCache["daily.cycle.count"] || {};
        let existingRecord = false;
        
        for (const id of Object.keys(cachedDict)) {
            const record = this.cache.getRecord("daily.cycle.count", Number(id));
            if (record.product_id.id === line.product_id.id && record.location_id.id === line.location_id.id && record.lot_name === lotName) {
                existingRecord = record;
                break;
            }
        }
        
        if (existingRecord) {
            Object.assign(line, existingRecord);
            if (line.lot_id) {
                line.lot_id = await this.cache.getRecordByBarcode(lotName, "stock.lot");
            }
        }
    }

    _canOverrideTrackingNumber(line, newLotName) {
        return super._canOverrideTrackingNumber(...arguments) && (!line.id || line.lot_id);
    }

    _createLinesState() {
        const today = new Date().toISOString().slice(0, 10);
        const lines = [];
        
        const cachedDict = this.cache.dbIdCache["daily.cycle.count"] || {};
        for (const id of Object.keys(cachedDict).map((id) => Number(id))) {
            const record = this.cache.getRecord("daily.cycle.count", id);
            if (
                (record.user_id && record.user_id !== this.userId) || 
                record.inventory_date > today || 
                record.state === 'done' // <-- TAMBAHKAN INI
            ) {
                continue;
            }
            
            const prevLine = this.currentState && this.currentState.lines.find((l) => l.id === id);
            const previousVirtualId = prevLine && prevLine.virtual_id;
            record.dummy_id = record.dummy_id && Number(record.dummy_id);
            record.virtual_id = record.dummy_id || previousVirtualId || this._uniqueVirtualId;
            record.product_id = this.cache.getRecord("product.product", record.product_id);
            
            record.product_uom_id = record.product_uom_id && this.cache.getRecord("uom.uom", record.product_uom_id);
            
            record.location_id = this.cache.getRecord("stock.location", record.location_id);
            record.lot_id = record.lot_id && this.cache.getRecord("stock.lot", record.lot_id);
            record.package_id = record.package_id && this.cache.getRecord("stock.package", record.package_id);
            
            lines.push(Object.assign({}, record));
        }
        return lines;
    }

    _getName() {
        return _t("Daily Cycle Count");
    }

    _selectLine(line) {
        if (this.selectedLineVirtualId !== line.virtual_id) {
            this.unfoldLineKey = this.groupKey(line);
        }
        super._selectLine(...arguments);
    }

    zeroQtyClass(line) {
        return this.IsNotSet(line) ? super.zeroQtyClass(...arguments) : "text-danger";
    }

    _getCompanyId() {
        return this.companyIds[0];
    }

    _shouldBeExpressedInPackagingUom() {
        return false;
    }
}

patch(MainComponent.prototype, {
    _getBarcodeModel() {
        if (this.resModel === "daily.cycle.count") {
            return BarcodeDailyCountModel;
        }
        return super._getBarcodeModel(...arguments);
    }
});