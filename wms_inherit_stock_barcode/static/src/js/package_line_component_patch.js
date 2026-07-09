/** @odoo-module **/
import PackageLineComponent from "@stock_barcode/components/package_line";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";

patch(PackageLineComponent, {
    props: [...PackageLineComponent.props, "editLine?"],
});

patch(PackageLineComponent.prototype, {
    setup() {
        super.setup();
        this.state = useState({ opened: false });
    },

    get sublinesToDisplay() {
        return this.line.lines || [];
    },

    get displayEditToggle() {
        // Hanya relevan saat tampilan dipaksa "entire pack"
        // padahal setting aslinya bukan entire pack (butuh edit per produk).
        return (
            this.env.model.record.picking_type_bypass_entire_packs &&
            this.sublinesToDisplay.length > 0
        );
    },

    toggleSublines(ev) {
        if (ev) ev.stopPropagation();
        this.state.opened = !this.state.opened;
    },

    editSublineQty(subline, ev) {
        if (ev) ev.stopPropagation();
        if (subline && this.props.editLine) {
            this.props.editLine(subline);
        } else {
            console.warn("editLine prop tidak tersedia atau subline kosong.");
        }
    },
});