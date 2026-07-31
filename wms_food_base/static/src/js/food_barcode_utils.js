/** @odoo-module **/

/**
 * Shared helpers for every FOOD/FEED bypass patch under this module's
 * static/src/js/ folder.
 *
 * -----------------------------------------------------------------------
 * WHY THIS FILE EXISTS / HOW THE BYPASS IS IMPLEMENTED
 * -----------------------------------------------------------------------
 * wms_inherit_stock_barcode (FEED) patches several core stock_barcode OWL
 * classes (BarcodePickingModel, LineComponent, PackageLineComponent,
 * Digipad, MainComponent, ...) via `patch()` from "@web/core/utils/patch".
 * wms_food_base depends on wms_inherit_stock_barcode and therefore always
 * loads AFTER it in the web.assets_backend bundle. The naive approach would
 * be to patch the same prototypes a second time here and call `super.x()`
 * for the FOOD branch, expecting it to skip past the FEED layer straight to
 * native Odoo behaviour -- exactly like the Phase 1-3 Python bypasses did
 * with `super(<innermost FEED class>, self).method(...)`.
 *
 * That does NOT work for OWL's `patch()`. Proof, from
 * odoo/addons/web/static/src/core/utils/patch.js:
 *
 *   function getPatchDescription(objToPatch) {
 *       if (!patchDescriptions.has(objToPatch)) {
 *           patchDescriptions.set(objToPatch, {
 *               originalProperties: new Map(),
 *               skeleton: Object.create(Object.getPrototypeOf(objToPatch)),
 *               extensions: new Set(),
 *           });
 *       }
 *       return patchDescriptions.get(objToPatch);
 *   }
 *   ...
 *   export function patch(objToPatch, extension) {
 *       const description = getPatchDescription(objToPatch);
 *       ...
 *       // Replace the old property by the new one.
 *       Object.defineProperty(objToPatch, key, newProperty);
 *       ...
 *       // Sets the current skeleton as the extension's prototype to make
 *       // `super` keyword working and then set extension as the new skeleton.
 *       description.skeleton = Object.setPrototypeOf(extension, description.skeleton);
 *   }
 *
 * `patchDescriptions` is a WeakMap keyed by the patched object itself (e.g.
 * `BarcodePickingModel.prototype`), and it is only created once ("if
 * (!patchDescriptions.has(objToPatch))"). Every subsequent `patch()` call on
 * the SAME prototype reuses that single description and its `skeleton`
 * reference. After wms_inherit_stock_barcode's `patch()` call runs:
 *   - `objToPatch` (e.g. BarcodePickingModel.prototype) has every FEED
 *     method/getter destructively installed as its OWN property
 *     (`Object.defineProperty(objToPatch, key, newProperty)` always runs,
 *     regardless of whether native Odoo already owned that key).
 *   - `description.skeleton` is reassigned to FEED's *extension object
 *      itself* (`Object.setPrototypeOf(extension, description.skeleton)`,
 *      then `description.skeleton = extension`).
 *
 * So when wms_food_base calls `patch()` a SECOND time on the very same
 * prototype: `oldProperty` for every key is now FEED's version (since step
 * 1 above already overwrote it), and the new extension's prototype
 * (`super`) is set to whatever `description.skeleton` currently holds --
 * which is FEED's extension object, not native Odoo's. In other words:
 * from a *second* `patch()` call, `super.x()` ALWAYS resolves to the
 * immediately-preceding patch layer (FEED), never to pristine native
 * behaviour, REGARDLESS of whether native Odoo itself defined that method
 * as an own property. There is no supported/reflective way to retrieve the
 * pre-patch descriptor from outside patch.js (the WeakMap is module-private
 * and not exported), and by the time this bundle evaluates, FEED's
 * `patch()` call has already run (bundle/module evaluation strictly follows
 * manifest `depends`/asset order), so we can't "get there first" either.
 *
 * RESOLUTION ("(b)" from the task, confirmed correct by the evidence above):
 * for every method/getter that native Odoo defines directly on the patched
 * class itself (e.g. `BarcodePickingModel.prototype.pageLines`,
 * `.barcodeInfo`, `._processPackage`, Digipad's `._increment`, ...), the
 * FOOD branch in our patch REIMPLEMENTS the native body verbatim (copied
 * from the corresponding odoo/addons/stock_barcode file read during this
 * phase) instead of relying on `super`. This is deliberate, intentional
 * duplication required by how `patch()` works -- not a shortcut -- and is
 * called out explicitly in every file that does it.
 *
 * There is one narrower case where `super.x()` from a second `patch()` call
 * DOES reach true native behaviour: when the method/getter FEED overrides
 * is NOT defined as an own property anywhere on the immediately patched
 * prototype natively, only on an ANCESTOR class's prototype that nobody
 * ever patches (e.g. `BarcodePickingModel` extends `BarcodeModel`, and
 * `_createState`/`_getSaveLineCommand`/`groupedLines` are only defined on
 * `BarcodeModel.prototype`, never redefined by native `BarcodePickingModel`
 * itself). Since `Object.getPrototypeOf(BarcodePickingModel.prototype)` is
 * `BarcodeModel.prototype` and FEED's patch() call never touches that
 * object, we can safely grab a *direct* reference to it once (see
 * `getNativeAncestorPrototype` below) and call `TheAncestorProto.x.call(this,
 * ...)` (or `Reflect.get(TheAncestorProto, "x", this)` for a getter) to run
 * genuinely untouched native code, with no duplication needed. This is used
 * throughout the patch files below wherever applicable; it is documented
 * per-usage since it only works for methods native Odoo does NOT itself
 * redefine on the direct class being patched.
 *
 * -----------------------------------------------------------------------
 * COMPANY / wms_type DETECTION
 * -----------------------------------------------------------------------
 * `res.company.wms_type` (see wms_food_base/models/res_company.py) is
 * exposed, related and stored, on stock.picking / stock.move /
 * stock.move.line / stock.quant / stock.package (Phase 1-3). For the
 * barcode app client, the most direct and already-plumbed way to read it
 * without an extra RPC is:
 *   - `BarcodePickingModel.record.wms_type`: populated as long as
 *     'wms_type' is part of `stock.picking._get_fields_stock_barcode()`'s
 *     field list (added in wms_food_base/models/stock_picking.py as part of
 *     this phase -- it was NOT there before). Every OWL component that
 *     renders under MainComponent's `useSubEnv({model, ...})` (LineComponent,
 *     PackageLineComponent, the QWeb templates in barcode_line_component_views.xml,
 *     MainComponent itself, ...) can reach it via `this.env.model.record.wms_type`.
 *   - Digipad is different: it is a `view_widgets` field widget rendered
 *     inside a plain form view (`stock_move_line_product_selector`), NOT
 *     under MainComponent's subEnv, so `env.model` is not reliably available
 *     there. Its `this.props.record` is a relational_model Record for
 *     stock.move.line, which already carries `wms_type` (Phase 3 added
 *     `<field name="wms_type" invisible="1"/>` to that exact view in
 *     wms_food_base/views/stock_move_line_barcode_views.xml). So Digipad
 *     uses `this.props.record.data.wms_type` instead.
 *   - Components with NO access to either (e.g. `ConfirmQuantDialog`,
 *     rendered by the DialogService against the app's root env -- see
 *     odoo/addons/web/static/src/core/dialog/dialog_service.js, `start(env,
 *     ...)` captures the *service-registration* env, not MainComponent's
 *     subEnv -- and `MainMenu`, the barcode app's home screen, which never
 *     fetches any company/picking data at all) have NO reliable low-cost
 *     way to know wms_type without inventing a brand new channel (a new
 *     RPC, or extending the main menu's own data endpoint). Per the task's
 *     explicit ordering of preference, this was NOT implemented in this
 *     phase; those two spots are intentionally left unbypassed and are
 *     called out in the phase report.
 */

/**
 * @param {object|null|undefined} record  A BarcodePickingModel-style
 *  `.record` (plain object with fields fetched via _get_fields_stock_barcode).
 * @returns {boolean}
 */
export function isFoodRecord(record) {
    return Boolean(record && record.wms_type === "FOOD");
}

/**
 * @param {object|null|undefined} model  A BarcodeModel instance (e.g.
 *  `this` inside a BarcodePickingModel patch, or `this.env.model` inside an
 *  OWL component rendered under MainComponent).
 * @returns {boolean}
 */
export function isFoodModel(model) {
    return isFoodRecord(model && model.record);
}

/**
 * @param {object|null|undefined} formRecord  A relational_model Record
 *  (`this.props.record` in a view_widgets field widget like Digipad).
 * @returns {boolean}
 */
export function isFoodFormRecord(formRecord) {
    return Boolean(formRecord && formRecord.data && formRecord.data.wms_type === "FOOD");
}

/**
 * Returns the prototype right above `PatchedClass.prototype` in the class
 * hierarchy. Safe to use as a native-code escape hatch ONLY for
 * methods/getters that native Odoo does not itself redefine as an own
 * property on `PatchedClass.prototype` (see the big comment above) --
 * otherwise it silently returns FEED's body instead of native's, or worse,
 * misses the native BarcodePickingModel-level logic entirely (only
 * reaching the grand-parent BarcodeModel behaviour). Every call site below
 * documents which case it is.
 *
 * @param {Function} PatchedClass
 * @returns {object}
 */
export function getNativeAncestorPrototype(PatchedClass) {
    return Object.getPrototypeOf(PatchedClass.prototype);
}
