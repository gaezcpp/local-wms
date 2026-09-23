# Project Context

Read `AGENTS.md` first. It contains binding environment, architecture, security, testing,
and Git restrictions. This file routes each task to deeper context without loading all project
documentation into every session.

## Source Of Truth

- FOOD runtime: `../../wms.conf`, database `WMS-FOOD-001`, module `wms_food_base_v2`.
- FEED runtime: database `DB_WMS_DEV_009`, using a separate config whose filename is not
  currently present/confirmed in this workspace. Ask before executing FEED commands.
- Custom code: this `addons_custom/` directory.
- Odoo core: sibling `../addons/`, read-only and usable only for signature/reference checks.
- System architecture: `@project-docs/architecture.md`.
- Business processes: `@project-docs/business_flow.md`.
- Module/model inventory: `@project-docs/modules_reference.md`.
- Database-derived route snapshot: `@project-docs/warehouse_routing.md`.
- Legacy agent material: `@claude-guidance`; useful context, but current `AGENTS.md` wins on
  conflicts such as database name.

Documentation can drift. Before relying on a model, method, dependency, XML ID, config key, or
route flag, verify current source. Route configuration is database data; code alone cannot prove
the active route.

## Task Routing

- Any Python/XML/model/view/report/controller change: load `odoo19-development`.
- SAP endpoint, query, payload, mapping, cron, or parameter: load `sap-rfc-integration`.
- FEED warehouse, stock, package, lot, route, picking, or quality: load `wms-stock-routing`.
- `wms_food_base_v2` or FOOD database behavior: load `food-wms-v2` and do not load FEED
  routing assumptions unless a shared Odoo core contract is being checked.
- Barcode app, OWL, JS patch, assets, scan flow: load `stock-barcode-owl`.
- Tagging, equipment, preventive planning, maintenance WO: load `pm-maintenance`.
- ACL, record rule, controller, `sudo()`, company isolation: load `security-multicompany`.
- Cron behavior, regression test, module upgrade, lint: load `cron-testing`.
- Changes spanning several domains: load every matching skill, but only read relevant sections
  from referenced docs.

## Module Map

WMS foundation and execution:

```text
wms_base_company
  +-- wms_base_warehouse
      +-- wms_inherit_stock_barcode
      |   +-- wms_production_order_sap
      |       +-- wms_quality_packages
      +-- wms_sale_order_sap

wms_base_partner and wms_purchase_order are adjacent SAP integrations.
```

FOOD is a separate deployment:

```text
wms_food_base_v2 -> WMS-FOOD-001 -> wms.conf
```

`wms_food_base` is legacy/deprecated and no longer used. It remains in source only for history;
do not install it, extend it, or update its former bypass when changing FEED code.

PM:

```text
tagging_system
  +-- maintenance_equipment_adjustment
  +-- pm_work_order_tagging (+ wms_base_company)
```

High-risk or standalone modules:

- `sap_coreapi`: unauthenticated encrypted inbound raw-SQL endpoint; README differs from code.
- `query_deluxe`: privileged arbitrary SQL console.
- `debt_management`: public debt API with known authorization concern.
- `sttl_warehouse_access_control`: third-party rules; current behavior can be permissive.
- `stock_no_negative`: OCA negative-stock constraint with test-specific bypass behavior.
- `hide_menu_user`: third-party menu restriction.
- `wms_cron_logging`: current model implementation is inactive/commented.

## Global Contracts

- `res.company.company_registry` maps SAP plant/WERKS.
- `sync_wms` and `sync_pm` gate company participation in integrations.
- SAP identifiers often require `strip()` and selective leading-zero removal. Never normalize
  business text or identifiers without verifying existing contract.
- Business timezone is usually `Asia/Jakarta`; Odoo Datetime storage remains UTC-naive.
- Existing misspellings such as `cron_synhronize_*` and parameter names can be external/XML
  contracts. Do not rename as cleanup.
- XML records commonly use `noupdate="1"`; module upgrade may not update existing DB rows.
- Credentials already present in data files are secrets. Never repeat them in docs, logs, tests,
  or answers, and never add new credentials to repository files.

## Change Checklist

1. Read manifest, relevant model/view/assets, callers, tests, and matching skill.
2. Read Odoo 19 core signature before overriding core methods.
3. Check downstream FEED modules when changing WMS override chains; ignore deprecated
   `wms_food_base` unless the task explicitly targets legacy removal/history.
4. Preserve multi-company natural keys by including `company_id` where applicable.
5. Add/update focused regression test; mock all SAP/network calls.
6. Run syntax check and Ruff when available. For Odoo tests, select the correct isolated
   environment: FOOD uses `wms.conf`/`WMS-FOOD-001`; FEED uses its separately confirmed
   config/`DB_WMS_DEV_009`.
7. Report environment blockers exactly; do not substitute another Python/DB/config silently.
