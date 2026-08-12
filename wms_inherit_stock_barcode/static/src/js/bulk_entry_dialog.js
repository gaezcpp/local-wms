/** @odoo-module **/

// bulk_entry: standalone dialog used by the "Bulk Entry" feature (see
// line_componant_patch.js: openBulkEntry/showBulkEntryButton) to collect a single
// "total Bag Qty" that is then distributed across the sibling move lines (same source
// package/product, different lots) greedily in display order.
import { Component, useState, xml } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

// bulk_entry: shows the product/package context above a large, centered qty input so
// warehouse floor users on handheld scanners can confirm what they're entering a
// quantity for before typing it in.
export class BulkEntryDialog extends Component {
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        maxQty: { type: Number, optional: true },
        productName: { type: String, optional: true },
        packageName: { type: String, optional: true },
        onConfirm: Function,
        close: Function,
    };
    static template = xml`
        <Dialog title="props.title or 'Bulk Entry'" size="'md'" contentClass="'o_bulk_entry_dialog'">
            <div class="d-flex flex-column gap-3">
                <div class="o_bulk_entry_context mb-2 text-center">
                    <div t-if="props.productName" class="o_bulk_entry_product_name fs-4 fw-bold">
                        <i class="fa fa-tag me-1"/><t t-esc="props.productName"/>
                    </div>
                    <div t-if="props.packageName" class="text-success fs-6 o_bulk_entry_package_name">
                        <t t-esc="'[' + props.packageName + ']'"/>
                    </div>
                </div>
                <div class="d-flex flex-column align-items-center gap-2">
                    <input id="o_bulk_entry_qty_input"
                           type="number"
                           min="0"
                           inputmode="decimal"
                           autofocus="autofocus"
                           style="font-size: 44px; padding: 16px; height: auto; width: 100%; max-width: 200px;"
                           class="form-control text-center mx-auto o_bulk_entry_qty_input"
                           t-model.number="state.qty"
                           t-on-keydown="onKeydown"
                           t-on-focus="(ev) => ev.target.select()"/>
                    <span class="text-muted o_bulk_entry_max_hint">Bag <t t-if="props.maxQty" t-esc="props.maxQty"/></span>
                </div>
            </div>
            <t t-set-slot="footer">
                <div class="d-flex justify-content-center w-100">
                    <button class="btn btn-primary btn-lg o_bulk_entry_confirm px-5" t-on-click="onConfirm">Confirm</button>
                    <button class="btn btn-secondary btn-lg o_bulk_entry_cancel flex-fill" t-on-click="onCancel">Cancel</button>
                </div>
            </t>
        </Dialog>
    `;

    setup() {
        this.state = useState({ qty: 0 });
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            this.onConfirm();
        }
    }

    onConfirm() {
        this.props.onConfirm(this.state.qty);
        this.props.close();
    }

    onCancel() {
        this.props.close();
    }
}
