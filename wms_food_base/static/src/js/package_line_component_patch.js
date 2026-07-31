/** @odoo-module **/

/**
 * FOOD bypass for
 * wms_inherit_stock_barcode/static/src/js/package_line_component_patch.js.
 *
 * PackageLineComponent is rendered natively (unconditionally, for any
 * company) whenever a line is grouped as an entire pack
 * (`<PackageLineComponent t-if="line.isPackageLine" .../>` in
 * stock_barcode.MainComponent, and `packageLines`/`considerPackageLines`
 * are bypassed to native behaviour for FOOD in
 * barcode_pickimg_model_patch.js), so it is reachable for FOOD.
 *
 * Only `setup()` needs a bypass here. Native `PackageLineComponent` does
 * NOT define its own `setup()` (it inherits `LineComponent.prototype.setup`,
 * see odoo/addons/stock_barcode/static/src/components/package_line.js and
 * line.js), and `line_componant_patch.js` (wms_food_base's FEED
 * counterpart) never patches `LineComponent.prototype.setup` either. So
 * `LineComponent.prototype.setup` is a genuinely untouched ancestor method
 * we can call directly (see food_barcode_utils.js for why this ancestor
 * technique is valid here specifically because native PackageLineComponent
 * itself never redefines `setup`).
 *
 * NOT bypassed (no `patch()` entries added), with justification:
 *   - `sublinesToDisplay`, `displayEditToggle`, `toggleSublines`,
 *     `editSublineQty`: brand new methods/getters with no native
 *     equivalent. Both QWeb blocks in wms_inherit_stock_barcode's
 *     barcode_line_component_views.xml that would call them (the two
 *     `t-inherit="stock_barcode.PackageLineComponent"` blocks) are entirely
 *     commented out, so none of these are ever invoked by any active
 *     template, for either company. Confirmed via a repo-wide grep: they
 *     are referenced nowhere else.
 *   - the static `patch(PackageLineComponent, {props: [...]})` call only
 *     widens the props schema with an optional `"editLine?"` prop; it does
 *     not force any value and is harmless either way.
 *   - `computedBagQty`/`bagUomLabel`/`hasBagUom`/`computedBagDemand` and the
 *     other getters added by `line_componant_patch.js` on
 *     `LineComponent.prototype` (which `PackageLineComponent` inherits) are
 *     bypassed at the QWeb template level instead (see
 *     static/src/xml/barcode_line_component_views.xml in this module): for
 *     FOOD, the restored `stock_barcode.LineQuantity` template no longer
 *     references any of them, so they become unreachable without needing a
 *     JS-level patch of `line_componant_patch.js` at all.
 */

import { patch } from "@web/core/utils/patch";
import PackageLineComponent from "@stock_barcode/components/package_line";
import { isFoodModel, getNativeAncestorPrototype } from "@wms_food_base/js/food_barcode_utils";

// LineComponent.prototype: never patched for `setup` by
// wms_inherit_stock_barcode, so this is guaranteed pristine native code.
const NATIVE_ANCESTOR_PROTO = getNativeAncestorPrototype(PackageLineComponent);

patch(PackageLineComponent.prototype, {
    setup() {
        if (isFoodModel(this.env.model)) {
            return NATIVE_ANCESTOR_PROTO.setup.call(this);
        }
        return super.setup(...arguments);
    },
});
