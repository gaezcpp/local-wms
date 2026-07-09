/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, xml } from "@odoo/owl";

export class FullPalletButtonField extends Component {
    static template = xml`
        <button type="button" class="btn btn-primary fw-bold fa fa-cubes" t-on-click.prevent="onClick">
            Full Pallet
        </button>
    `;
    
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.orm = useService("orm");
    }

    async onClick() {
        const record = this.props.record;
        const getM2oId = (val) => {
            if (!val) return false;
            if (Array.isArray(val)) return val[0]; 
            if (typeof val === 'object' && val.id) return val.id; 
            if (val[0]) return val[0]; 
            if (typeof val === 'number') return val; 
            return false;
        };

        const rawBag = record.data.uom_bag_id;
        const rawPallet = record.data.uom_pallet_id;

        const bagUomId = getM2oId(rawBag);
        const palletUomId = getM2oId(rawPallet);

        console.log("Raw Bag UoM:", rawBag, "=> Extracted ID:", bagUomId);
        console.log("Raw Pallet UoM:", rawPallet, "=> Extracted ID:", palletUomId);

        if (bagUomId && palletUomId) {
            try {
                const uoms = await this.orm.read("uom.uom", [bagUomId, palletUomId], ["factor"]);
                const bagUom = uoms.find(u => u.id === bagUomId);
                const palletUom = uoms.find(u => u.id === palletUomId);

                if (bagUom && palletUom && bagUom.factor) {
                    const maxBag = Math.round(palletUom.factor / bagUom.factor);
                    await record.update({ bag_qty: maxBag });
                }
            } catch (error) {
                console.error("Gagal menarik data factor UoM:", error);
            }
        } else {
            console.warn("Validasi Gagal: UoM Bag atau UoM Pallet kosong. Pastikan Master Produk memiliki setting UoM ini!");
        }
    }
}

export const fullPalletButtonFieldDefinition = {
    component: FullPalletButtonField,
    supportedTypes: ["boolean"],
};

registry.category("fields").add("full_pallet_button", fullPalletButtonFieldDefinition);