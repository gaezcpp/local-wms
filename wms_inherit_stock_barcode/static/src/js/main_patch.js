/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import MainComponent from "@stock_barcode/components/main";

patch(MainComponent.prototype, {

    setup() {
        super.setup(...arguments);

        if (!this.env.model.openSlocPackaging) {
            this.env.model.openSlocPackaging = () => {
                return this.env.model._openSlocPackaging();
            };
        }

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

        if (!this.env.model.isCheckerOut) {
            this.env.model.isCheckerOut = () => {
                // Gunakan opsional chaining (?) untuk menghindari error jika record sedang kosong
                return Boolean(this.env.model.record?.checker_out);
            };
        }

        if (!this.env.model.isCreateNewPicking) {
            this.env.model.isCreateNewPicking = () => {
                // Gunakan opsional chaining (?) untuk menghindari error jika record sedang kosong
                return Boolean(this.env.model.record?.create_new_picking);
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

        if (!this.env.model.createNewPicking) {
            this.env.model.createNewPicking = () => {
                return this.env.model._createNewPicking();
            };
        }
    },

    /**
     * Core (`stock_barcode/components/main.js`) mencari ulang line yang belum
     * punya `id` lewat `pageLines.find((l) => l.dummy_id === virtualId)`. Kalau
     * line itu -- karena alasan apa pun -- tidak ikut tersimpan pada `save()` di
     * atasnya, `find()` mengembalikan `undefined` dan `getEditedLineParams(line)`
     * langsung melempar "Cannot read properties of undefined (reading 'id')",
     * sehingga seluruh layar barcode mati.
     *
     * Di sini pencarian ditambah fallback ke `virtual_id` (line yang masih murni
     * client-side belum punya `dummy_id`), lalu ke objek line aslinya. Jaring
     * pengaman: tidak boleh ada klik edit line yang berujung crash.
     */
    async onOpenProductPage(line) {
        if (line && !line.id && line.virtual_id) {
            const virtualId = line.virtual_id;
            await this.env.model.save();
            const pageLines = this.env.model.pageLines || [];
            const resolved =
                pageLines.find((l) => l.dummy_id === virtualId) ||
                pageLines.find((l) => l.virtual_id === virtualId) ||
                line;
            if (!resolved.id) {
                console.warn(
                    "[WMS-SCANNER][moveLine] onOpenProductPage: line belum tersimpan",
                    { virtual_id: virtualId, product: resolved.product_id }
                );
            }
            this._editedLineParams = this.env.model.getEditedLineParams(resolved);
            this.changeView("productPage");
            return;
        }
        return super.onOpenProductPage(...arguments);
    },

    async hardRefresh() {
        this.blockUIMessage = _t("Hard refreshing...");
        this.blockUI();
        try {
            await this._revalidateAssets();
        } catch (error) {
            console.warn("Asset revalidation failed, reloading anyway", error);
        }
        browser.location.reload();
    },

    async _revalidateAssets() {
        const origin = browser.location.origin;
        const urls = new Set([browser.location.href]);
        const nodes = document.querySelectorAll("script[src], link[rel='stylesheet'][href]");
        for (const node of nodes) {
            const url = node.src || node.href;
            if (url && url.startsWith(origin)) {
                urls.add(url);
            }
        }
        await Promise.all(
            [...urls].map((url) =>
                browser.fetch(url, { cache: "reload", credentials: "same-origin" })
            )
        );
    },

    async saveFormView(lineRecord) {
        this.blockUI();
        try {
            const lineId =
                (lineRecord && lineRecord.resId) ||
                (this._editedLineParams && this._editedLineParams.currentId);
            const recordId = lineRecord.resModel === this.resModel ? lineId : undefined;
            await this._onRefreshState({ recordId, lineId });
        } finally {
            this.unblockUI();
        }
    },

});