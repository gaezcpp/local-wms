# AGENTS.md — Odoo 19 Enterprise Development Guide

## Environment

- Odoo Version: **Odoo 19 Enterprise**
- Python: **3.12**
- PostgreSQL: **16**
- Operating System: **Windows**
- Working Directory:

  D:\CPP\Odoo19-ENT\server\

- Main Configuration:

  wms.conf

  - Port: 8019
  - Database: DB_WMS_DEV_007
  - Includes: addons_custom

- Default Configuration:

  odoo.conf

  - Port: 8069
  - Does NOT include addons_custom

---

# Project Rules (Highest Priority)

## 1. Never modify Odoo Core

Everything under:

```
odoo/addons/*
```

is **read-only**.

It may only be used for:

- reading implementation
- understanding behavior
- referencing existing methods
- inheritance targets

It must NEVER be modified.

Do not:

- edit files
- rename files
- delete files
- add files
- patch files

All customizations must be implemented inside:

```
addons_custom/
```

using inheritance.

---

## 2. Always Use The Odoo Way

Before writing custom code, always prefer:

- model inheritance
- view inheritance
- compute fields
- related fields
- onchange
- constraints
- record rules
- automated actions
- server actions

Avoid replacing standard behavior unless absolutely necessary.

Never duplicate existing Odoo functionality.

---

## 3. No Monkey Patching

Never monkey-patch:

- models
- javascript
- owl components
- controllers

unless there is absolutely no supported extension point.

Always prefer inheritance.

---

## 4. Git Restrictions

Never perform any Git operation.

Forbidden:

- git commit
- git push
- git pull
- git merge
- git rebase
- git stash
- git reset
- git checkout
- git switch
- git tag
- git cherry-pick

Never suggest performing Git operations automatically.

Git is outside the agent scope.

---

## 5. No Core Database Changes

Never modify:

- ir_model
- ir_model_fields
- ir_ui_view
- ir_module_module

using SQL.

Always use ORM or XML data.

---

# Development Standards

## Python

Use:

- Python 3.12 syntax
- PEP8
- Ruff compatible

Prefer:

- mapped()
- filtered()
- sorted()
- grouped()
- read_group()
- search_fetch() (when appropriate)
- batch create/write
- model_create_multi

Avoid:

- raw SQL
- excessive loops
- repeated searches inside loops

Raw SQL is allowed only when ORM cannot provide acceptable performance.

Always parameterize SQL.

---

## ORM Rules

Always prefer ORM.

Example priorities:

1. search()
2. browse()
3. read_group()
4. mapped()
5. filtered()

Avoid:

```
for record in self:
    self.env["model"].search(...)
```

inside loops.

Instead, batch queries whenever possible.

---

## Fields

Prefer:

- compute
- related
- stored compute only when necessary

Always specify:

- string
- help (when useful)
- index (when appropriate)
- tracking (only when business relevant)

---

## Security

Every new model must include:

- ir.model.access.csv

Use:

- groups
- record rules

Never bypass ACLs unless absolutely required.

Avoid unnecessary sudo().

---

# XML Development

Always inherit existing views.

Use:

```
xpath
```

Never duplicate entire views unless absolutely necessary.

Use robust xpath expressions.

Avoid fragile positional xpaths.

---

# OWL / JavaScript

Use only the modern OWL architecture available in Odoo 19.

Do not use:

- legacy widgets
- old Class.extend()
- old web client patterns

Prefer:

- components
- services
- hooks
- registries
- patches only when officially supported

---

# Reports

Use:

- QWeb

Do not introduce deprecated report APIs.

---

# Controllers

Use:

```
type="json"
```

or

```
type="http"
```

appropriately.

Validate:

- permissions
- user input
- authentication

Never trust client input.

---

# Performance

Always think about:

- database queries
- prefetching
- batching
- cache

Avoid N+1 queries.

Avoid nested searches.

---

# Logging

Use:

```
import logging

_logger = logging.getLogger(__name__)
```

Use:

- debug
- info
- warning
- error

Never use:

```
print()
```

for debugging.

---

# Custom Modules

All custom modules belong in:

```
addons_custom/
```

Never create modules inside:

```
odoo/addons/
```

Module naming should follow:

```
wms_xxx
pm_xxx
custom_xxx
```

Version format:

```
19.0.x.y.z
```

---

# Existing Module Groups

## WMS

- wms_base_company
- wms_base_partner
- wms_base_warehouse
- wms_inherit_stock_barcode
- wms_production_order_sap
- wms_sale_order_sap
- wms_purchase_order
- wms_quality_packages
- wms_food_base
- wms_cron_logging

Dependency flow:

```
base_company
    ↓
base_warehouse
    ↓
inherit_stock_barcode
    ↓
production_order_sap
    ↓
quality_packages
```

---

## PM

- tagging_system
- maintenance_equipment_adjustment
- pm_work_order_tagging

All depend on:

```
tagging_system
```

---

## Standalone

- debt_management
- hide_menu_user
- query_deluxe
- sap_coreapi
- stock_no_negative
- sttl_warehouse_access_control (third-party, not project-authored)

---

# Commands

## Start Server

```bash
python odoo-bin -c wms.conf
```

## Shell

```bash
python odoo-bin shell -c wms.conf
```

## Scaffold

```bash
python odoo-bin scaffold <module_name> addons_custom/
```

## Upgrade Module

```bash
python odoo-bin -c wms.conf -u <module_name>
```

## Run Tests

```bash
python odoo-bin -c wms.conf --test-enable -d DB_WMS_DEV_007 --stop-after-init -u <module_name>
```

## Ruff

```bash
ruff check ../addons_custom/<module>/
```

---

# Testing

Prefer:

- TransactionCase
- SavepointCase
- BaseCommon

Use:

- setUpClass()
- cls.env

Disable tracking when appropriate:

```python
with self.env.context(tracking_disable=True):
    ...
```

---

# External Dependencies

Project dependencies are managed through:

```
server/requirements.txt
```

Some modules (e.g. sap_coreapi) require:

- cryptography
- pycryptodome

---

# Code Review Checklist

Before finishing any task, verify:

- No modification under `odoo/addons/`
- Changes only inside `addons_custom/`
- Uses inheritance instead of replacing standard behavior
- Compatible with Odoo 19
- Uses ORM efficiently
- No unnecessary sudo()
- No print()
- No raw SQL unless justified
- Security rules respected
- Views inherited via xpath
- OWL only (no legacy JS)
- QWeb for reports
- PEP8 compliant
- Ruff compatible
- No Git operations performed
- No Git instructions suggested
- No destructive database operations
- No modifications to Odoo core

---

# Agent Behavior

When answering development questions:

1. Assume Odoo 19 Enterprise.
2. Always follow standard Odoo architecture.
3. Prefer inheritance over replacement.
4. Never modify Odoo core.
5. Never create solutions requiring changes inside `odoo/addons/`.
6. Never recommend monkey patching unless there is no supported extension point.
7. Optimize for maintainability, upgrade safety, and performance.
8. Preserve compatibility with future Odoo 19 updates.
9. If a requested solution would violate these rules, explain why and provide the closest compliant alternative.