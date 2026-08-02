/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
const { Component, onMounted } = owl;

export class QRScannerGrFgAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        const focusInput = () => {
            const input = document.querySelector('.o_barcode_input');
            if (input) input.focus();
        };

        onMounted(() => {
            focusInput();
            document.addEventListener('click', focusInput);
            const input = document.querySelector('.o_barcode_input');
            input.addEventListener('keypress', async (e) => {
                if (e.key === 'Enter') {
                    this.handleScan(e.target.value);
                    e.target.value = '';
                }
            });
        });
    }

    async handleScan(value) {
        const raw = value.trim();
        const [po_number, production_line_code] = raw.split('|');
        if (!po_number || !production_line_code) {
            alert("Format QR tidak valid");
            return;
        }
        try {
            const result = await this.orm.call(
                "production.order.sap", "action_picking_po_sap_from_qr",
                [po_number, production_line_code]
            );
            this.action.doAction(result);
        } catch (error) {
            alert(error.data?.message || "Gagal memproses QR");
        }
    }
}
QRScannerGrFgAction.template = "QRScannerGrFgTemplate";
registry.category("actions").add("qr_scanner_gr_fg_action", QRScannerGrFgAction);
