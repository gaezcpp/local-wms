/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
const { Component, onMounted, onPatched } = owl;

export class QRScannerAction extends Component {
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

    async handleScan(po_number) {
        const records = await this.orm.searchRead("production.order.sap", [['po_number', '=', po_number.trim()]], ['id']);
        if (records.length > 0) {
            this.action.doAction({
                type: 'ir.actions.act_window',
                res_model: 'production.order.sap',
                res_id: records[0].id,
                views: [[false, 'form']],
                target: 'current',
            });
        } else {
            alert("PO Tidak Ditemukan");
        }
    }
}
QRScannerAction.template = "QRScannerTemplate";
registry.category("actions").add("qr_scanner_action", QRScannerAction);