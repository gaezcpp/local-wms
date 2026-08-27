"""Unit test: UoM Bag & demand pada line bentukan client Barcode (Split QTY Pallet / P2P).

Direproduksi dari kejadian nyata **FINI/P2P/00365** (DB_WMS_DEV_008):

    picking  FINI/P2P/00365 (operation type `Split QTY Pallet`, sequence_code P2P,
             bypass_entire_packs=True, bulk_pallet_lot=True, split_package=True,
             autofill_pack_qty=False) -- dibuat KOSONG, tanpa stock.move sama sekali
    pallet   SPJ-PALLET-3731 (stock.package 10731) berisi satu produk, empat lot:
             +-- quant 11870  lot 372  qty 276 kg
             +-- quant 23502  lot 224  qty 120 kg
             +-- quant 23506  lot 435  qty  54 kg
             +-- quant 23503  lot 495  qty  30 kg
                                       ---------
                                            480 kg  = 80 BOX (UoM Bag "BOX 6")

Gejala yang dilaporkan operator, saat pallet baru saja di-scan:

    1. qty tampil "480 kg" -- masih UoM produk, bukan "0 BOX / 80 BOX";
    2. tombol Bulk Entry menolak dengan
       "Tidak ada quantity yang bisa dibagikan pada pallet ini.";
    3. bagian "/80 BOX" tidak pernah muncul sampai dokumen ditutup lalu dibuka lagi.

PENYEBAB
--------
Dua hal, keduanya bermuara pada satu fakta: pada P2P picking lahir kosong, jadi
SELURUH `stock.move.line` dibentuk di client oleh `_createNewLine()`, dan client
Barcode baru menyimpan saat operasi ditutup (`beforeQuit()`).

1. `uom_bag_id`/`uom_pallet_id` adalah field **related ke produk**, jadi belum
   terisi selama line masih hidup di client. `hasBagUom` false -> qty dirender
   dengan UoM produk; `_computeBagFromQty()` selalu 0 -> kapasitas Bulk Entry 0.

2. `reserved_uom_qty` di client hanyalah ingatan sisi client. Untuk line yang
   dibentuk di app, core sengaja memasangnya 0 ("This line was created in the
   Barcode App, so it has no reservation") dan mempertahankannya pada setiap
   reload dalam sesi yang sama (`reloadingMoveLines` true). Baru pada load
   pertama berikutnya ia diisi `= quantity` -- dari situlah "/80 BOX" muncul
   setelah operator keluar-masuk dokumen.

Timeline di DB membenarkan urutan itu: picking 15614 dibuat 15:07:58, sementara
move + keempat move line-nya baru lahir 15:13:09 (saat operator menekan back).

PERBAIKAN YANG DIUJI DI SINI
----------------------------
* `product.product._get_fields_stock_barcode()` (models/product_product.py) ikut
  mengirim `uom_bag_id`/`uom_pallet_id`, supaya patch `_getNewLineDefaultValues()`
  bisa mengisinya saat line dibentuk.
* `_rememberScannedPackageContent()` / `getScannedPackageQty()`
  (barcode_pickimg_model_patch.js) mencatat isi pallet per (pallet, produk, lot)
  dari quant yang di-scan, dan `_computeSingleBagDemand()`
  (line_componant_patch.js) memakainya sebagai demand untuk line yang belum
  punya reservasi. Isi pallet dipilih -- bukan `qty_done` line -- supaya demand
  tidak ikut mengecil saat Bulk Entry menurunkan qty.

CATATAN SOAL CAKUPAN TEST
-------------------------
Sisi OWL-nya tidak bisa dijalankan dari `TransactionCase`. Yang diuji di sini:

* kontrak payload server yang menyuapi patch itu (`_get_stock_barcode_data()` dan
  `stock.quant.get_stock_barcode_data_records()` -- RPC yang persis dipakai
  `_processPackage()` core); dan
* aritmetikanya, lewat `_BarcodeClientSim` di bawah: replika satu-satu dari
  method JS yang bersangkutan, dijalankan atas payload asli dari server.

Jadi ini menjaga kontrak + hitungannya, bukan rendering OWL-nya. Kalau salah satu
method JS itu diubah, replika di bawah harus ikut diubah -- nama methodnya sengaja
dibuat mirip supaya mudah ditelusuri.

Semua test memakai `TransactionCase` -> data uji di-rollback, DB dev tidak berubah.
"""

import math

from odoo.tests import TransactionCase, tagged


class _BarcodeClientSim:
    """Replika sisi client Barcode, disuapi payload asli dari server.

    Setiap method menyebut method JS yang ditirunya. `line` di sini adalah dict
    dengan bentuk yang sama seperti objek line di `currentState.lines`.
    """

    def __init__(self, uoms, autofill_pack_qty=False, checker=False):
        self.uoms = uoms                            # {id: {'factor': ...}}
        self.autofill_pack_qty = autofill_pack_qty  # picking.autofill_pack_qty
        self.checker = checker                      # isCheckerOnly()/isCheckerOut()
        self.package_content = {}

    # -- barcode_pickimg_model_patch.js --------------------------------
    @staticmethod
    def _package_key(package_id, product_id, lot_id):
        """`_scannedPackageKey()`"""
        return '%s_%s_%s' % (package_id, product_id, lot_id or 0)

    def remember_package_content(self, quant_records):
        """`_rememberScannedPackageContent()`

        `quant_records` = isi `records['stock.quant']` dari
        `stock.quant.get_stock_barcode_data_records()`, yaitu persis yang
        dimasukkan core ke cache di dalam `_processPackage()`.
        """
        for quant in quant_records:
            if not quant.get('product_id'):
                continue
            key = self._package_key(
                quant.get('package_id'), quant['product_id'], quant.get('lot_id')
            )
            self.package_content[key] = quant.get('quantity') or 0

    def get_scanned_package_qty(self, line):
        """`getScannedPackageQty()`"""
        package_id = line.get('package_id')
        product_id = line.get('product_id')
        if not package_id or not product_id:
            return 0
        key = self._package_key(package_id, product_id, line.get('lot_id'))
        if key in self.package_content:
            return self.package_content[key] or 0
        return line.get('packedQuantity') or 0

    # -- line_componant_patch.js ---------------------------------------
    def bag_from_qty(self, line, qty):
        """`_computeBagFromQty()`"""
        bag_uom = self.uoms.get(line.get('uom_bag_id'))
        product_uom = self.uoms.get(line.get('product_uom_id'))
        if not bag_uom or not product_uom or not qty:
            return 0
        if not bag_uom.get('factor') or not product_uom.get('factor'):
            return 0
        return (qty * product_uom['factor']) / bag_uom['factor']

    def bag_demand(self, line):
        """`_computeSingleBagDemand()` -- reservasi menang, kalau tidak isi pallet."""
        reserved = line.get('reserved_uom_qty') or 0
        if reserved:
            return self.bag_from_qty(line, reserved)
        return self.bag_from_qty(line, self.get_scanned_package_qty(line))

    def bag_qty(self, line):
        """`_computeSingleBagQty()`"""
        if not line.get('uom_bag_id') or not line.get('product_uom_id'):
            return 0
        if not self.autofill_pack_qty:
            return line.get('bag_qty') or 0
        return self.bag_from_qty(line, line.get('qty_done') or 0)

    @staticmethod
    def _round2(value):
        # JS `Math.round(x * 100) / 100`: pembulatan setengah ke atas, bukan
        # banker's rounding milik `round()` Python.
        return math.floor(value * 100 + 0.5) / 100

    def computed_bag_demand(self, group):
        """`computedBagDemand`"""
        return self._round2(sum(self.bag_demand(line) for line in group))

    def computed_bag_qty(self, group):
        """`computedBagQty`"""
        return self._round2(sum(self.bag_qty(line) for line in group))

    def has_bag_uom(self, group):
        """`hasBagUom` -- core memakai subline PERTAMA sebagai acuan grup."""
        return bool(group and group[0].get('uom_bag_id'))

    def shows_demand(self, group):
        """t-if span demand di barcode_line_component_views.xml, sesudah patch."""
        if self.checker:
            return False
        if self.has_bag_uom(group):
            return bool(self.computed_bag_demand(group))
        # `displayLineQtyDemand()` core = getQtyDemand() = reserved_uom_qty.
        return bool(sum(line.get('reserved_uom_qty') or 0 for line in group))

    def bulk_capacities(self, group):
        """`_getBulkCapacities()` -- tanpa cabang RPC quant (tidak diperlukan lagi
        selama isi pallet sudah tercatat saat scan)."""
        return [int(math.floor(self.bag_demand(line))) for line in group]

    def apply_bulk_bag_qty(self, line, bag_qty):
        """`_applyBulkBagQty()`"""
        line['bag_qty'] = bag_qty
        bag_uom = self.uoms.get(line.get('uom_bag_id'))
        if bag_uom and bag_uom.get('factor'):
            line['qty_done'] = bag_qty * (bag_uom['factor'] / 1000)


@tagged('post_install', '-at_install', 'wms_outbound', 'wms_p2p_bag_uom')
class TestSplitQtyPalletBagUom(TransactionCase):

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.type_p2p = cls.env['stock.picking.type'].search([
            ('sequence_code', '=', 'P2P'),
            ('bypass_entire_packs', '=', True),
        ], limit=1)
        if not cls.type_p2p:
            raise ValueError("Operation type Split QTY Pallet (P2P, bypass_entire_packs) tidak ada.")

        cls.company = cls.type_p2p.company_id
        cls.env.user.write({
            'company_ids': [(4, cls.company.id)],
            'company_id': cls.company.id,
        })
        cls.env = cls.env(context=dict(
            cls.env.context,
            allowed_company_ids=[cls.company.id],
        ))
        cls.type_p2p = cls.type_p2p.with_env(cls.env)

        # Konversi bag hanya masuk akal kalau UoM aktif -- itu juga syarat
        # `_get_stock_barcode_data()` mengirim SELURUH uom.uom ke cache client,
        # tempat `cache.getRecord("uom.uom", bagUomId)` mencarinya.
        cls.env.user.group_ids = [(4, cls.env.ref('uom.group_uom').id)]

        cls.loc_src = cls.type_p2p.default_location_src_id
        cls.loc_bin = cls.env['stock.location'].create({
            'name': 'UT-P2P-BIN',
            'location_id': cls.loc_src.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })

        reference = cls.env['product.product'].search([
            ('uom_bag_id', '!=', False),
            ('uom_pallet_id', '!=', False),
            ('tracking', '=', 'lot'),
        ], limit=1)
        if not reference:
            raise ValueError("Tidak ada produk dengan UoM Bag & Pallet untuk dijadikan acuan.")

        cls.product = cls.env['product.product'].create({
            'name': 'UT Pakan Ikan Floating MIX 1mm',
            'default_code': 'UT-TF1-100-MIX',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'uom_id': reference.uom_id.id,
            'uom_bag_id': reference.uom_bag_id.id,
            'uom_pallet_id': reference.uom_pallet_id.id,
        })
        # Produk kedua dengan UoM bag BERBEDA, untuk skenario pallet campur produk.
        cls.product_other = cls.env['product.product'].create({
            'name': 'UT Pakan Ikan Sinking 2mm',
            'default_code': 'UT-TF2-200-MIX',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'uom_id': reference.uom_id.id,
            'uom_bag_id': reference.uom_pallet_id.id,
            'uom_pallet_id': reference.uom_pallet_id.id,
        })

        # Berapa UoM produk per satu bag (kg -> BOX 6: 6).
        cls.bag_ratio = cls.product.uom_bag_id.factor / cls.product.uom_id.factor

        # Isi pallet 3731. Sengaja dinyatakan dalam KELIPATAN bag supaya
        # skenarionya tetap 46/20/9/5 = 80 bag berapa pun UoM Bag produk acuan
        # yang kebetulan ada di database ini -- dengan produk aslinya
        # (BOX 6) angkanya persis 276/120/54/30 kg = 480 kg.
        cls.bag_by_lot_name = {
            'UT-P2P-LOT-372': 46,
            'UT-P2P-LOT-224': 20,
            'UT-P2P-LOT-435': 9,
            'UT-P2P-LOT-495': 5,
        }
        cls.qty_by_lot_name = {
            name: bags * cls.bag_ratio for name, bags in cls.bag_by_lot_name.items()
        }
        cls.lots = cls.env['stock.lot'].create([{
            'name': name,
            'product_id': cls.product.id,
            'company_id': cls.company.id,
        } for name in cls.qty_by_lot_name])

        cls.total_qty = sum(cls.qty_by_lot_name.values())
        cls.total_bag = float(sum(cls.bag_by_lot_name.values()))  # 80

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_pallet(self, name='UT-SPJ-PALLET-3731', qty_by_lot_name=None, product=None):
        product = product or self.product
        qty_by_lot_name = qty_by_lot_name if qty_by_lot_name is not None else self.qty_by_lot_name
        package = self.env['stock.package'].search([('name', '=', name)], limit=1)
        if not package:
            package = self.env['stock.package'].create({
                'name': name,
                'company_id': self.company.id,
            })
            package.yellow_tag = 'ready'
        lots = self.env['stock.lot']
        for lot_name, qty in qty_by_lot_name.items():
            lot = self.env['stock.lot'].search([
                ('name', '=', lot_name), ('product_id', '=', product.id),
            ], limit=1)
            if not lot:
                lot = self.env['stock.lot'].create({
                    'name': lot_name,
                    'product_id': product.id,
                    'company_id': self.company.id,
                })
            lots |= lot
            self.env['stock.quant']._update_available_quantity(
                product, self.loc_bin, qty, lot_id=lot, package_id=package,
            )
        quants = self.env['stock.quant'].sudo().search([
            ('package_id', '=', package.id),
        ])
        quants.write({'stock_type': 'UU'})
        return package, quants

    def _make_empty_p2p_picking(self):
        """Persis FINI/P2P/00365 sebelum di-scan: tanpa move, tanpa move line."""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.type_p2p.id,
            'location_id': self.loc_src.id,
            'location_dest_id': self.type_p2p.default_location_dest_id.id,
            'company_id': self.company.id,
        })
        self.assertFalse(picking.move_ids, "Picking P2P harus lahir kosong.")
        self.assertFalse(picking.move_line_ids, "Picking P2P harus lahir tanpa move line.")
        return picking

    @staticmethod
    def _by_id(data, model):
        return {rec['id']: rec for rec in data['records'].get(model, [])}

    def _scan(self, picking, quants):
        """Jalankan simulasi scan pallet dan kembalikan (sim, lines).

        `lines` dibentuk seperti `_createNewLine()` di client SESUDAH patch
        `_getNewLineDefaultValues()` -- termasuk `reserved_uom_qty = 0` yang
        memang dipasang core untuk line bentukan app.
        """
        picking_data = picking._get_stock_barcode_data()
        uoms = self._by_id(picking_data, 'uom.uom')

        # RPC yang dipanggil core di dalam `_processPackage()`.
        scan_payload = quants.get_stock_barcode_data_records()
        quant_records = scan_payload['records']['stock.quant']
        products = {rec['id']: rec for rec in scan_payload['records']['product.product']}

        sim = _BarcodeClientSim(
            uoms,
            autofill_pack_qty=picking.picking_type_id.autofill_pack_qty,
        )
        sim.remember_package_content(quant_records)

        lines = []
        for quant in quant_records:
            product = products[quant['product_id']]
            lines.append({
                'id': False,
                'product_id': quant['product_id'],
                # `updateLine()` core: product_uom_id diambil dari produk.
                'product_uom_id': product['uom_id'],
                'uom_bag_id': product.get('uom_bag_id'),
                'uom_pallet_id': product.get('uom_pallet_id'),
                'lot_id': quant.get('lot_id'),
                'package_id': quant.get('package_id'),
                'reserved_uom_qty': 0,
                'qty_done': quant['quantity'],
                'bag_qty': 0,
            })
        return sim, lines

    def _save_scanned_lines(self, picking, lines):
        """Tiru simpanan client Barcode: satu write ke move_line_ids."""
        picking.write({'move_line_ids': [(0, 0, {
            'product_id': line['product_id'],
            'product_uom_id': line['product_uom_id'],
            'location_id': self.loc_bin.id,
            'location_dest_id': picking.location_dest_id.id,
            'lot_id': line['lot_id'],
            'package_id': line['package_id'],
            'quantity': line['qty_done'],
            'picked': True,
            'company_id': self.company.id,
        }) for line in lines]})
        self.env.flush_all()

    def _reload(self, picking):
        """Line seperti yang dibangun `_getMoveLineData()` pada load PERTAMA:
        `reserved_uom_qty = quantity`. Inilah keadaan "sesudah back lalu masuk
        lagi" yang tampilannya sudah benar sejak dulu."""
        data = picking._get_stock_barcode_data()
        uoms = self._by_id(data, 'uom.uom')
        sim = _BarcodeClientSim(
            uoms, autofill_pack_qty=picking.picking_type_id.autofill_pack_qty
        )
        lines = []
        for sml in data['records']['stock.move.line']:
            lines.append({
                'id': sml['id'],
                'product_id': sml['product_id'],
                'product_uom_id': sml['product_uom_id'],
                'uom_bag_id': sml.get('uom_bag_id'),
                'uom_pallet_id': sml.get('uom_pallet_id'),
                'lot_id': sml.get('lot_id'),
                'package_id': sml.get('package_id'),
                'reserved_uom_qty': sml['quantity'],
                'qty_done': sml['qty_done'],
                'bag_qty': sml.get('bag_qty') or 0,
            })
        return sim, lines

    # ------------------------------------------------------------------
    # 1. Kontrak field: produk harus membawa UoM bag/pallet ke client
    # ------------------------------------------------------------------
    def test_01_product_barcode_fields_memuat_uom_bag_dan_pallet(self):
        """Tanpa dua field ini, line bentukan client tidak pernah punya UoM bag."""
        fields_list = self.env['product.product']._get_fields_stock_barcode()

        self.assertIn('uom_bag_id', fields_list)
        self.assertIn('uom_pallet_id', fields_list)
        # Field core tidak boleh hilang gara-gara override.
        for core_field in ('display_name', 'tracking', 'uom_id', 'barcode'):
            self.assertIn(core_field, fields_list)

    # ------------------------------------------------------------------
    # 2. Payload scan: record produk + record uom.uom-nya ikut terkirim
    # ------------------------------------------------------------------
    def test_02_payload_barcode_membawa_uom_bag_produk(self):
        """`_get_stock_barcode_data()` harus cukup untuk mengisi line di client."""
        pallet, quants = self._make_pallet()
        picking = self._make_empty_p2p_picking()

        # Pada picking P2P yang masih kosong, produknya hanya sampai ke client
        # lewat quant pallet yang di-scan (`get_stock_barcode_data_records()`),
        # bukan lewat payload picking -- picking-nya belum punya line sama sekali.
        specific = quants.get_stock_barcode_data_records()
        products = {rec['id']: rec for rec in specific['records']['product.product']}

        self.assertIn(
            self.product.id, products,
            "Produk pallet harus ikut terkirim ke client saat pallet di-scan.",
        )
        product_data = products[self.product.id]
        self.assertEqual(
            product_data.get('uom_bag_id'), self.product.uom_bag_id.id,
            "Record product.product di client wajib membawa uom_bag_id.",
        )
        self.assertEqual(
            product_data.get('uom_pallet_id'), self.product.uom_pallet_id.id,
            "Record product.product di client wajib membawa uom_pallet_id.",
        )

        # Picking-nya sendiri harus mengirim seluruh uom.uom (grup uom aktif),
        # supaya `cache.getRecord("uom.uom", bagUomId)` di client ketemu.
        uoms = self._by_id(picking._get_stock_barcode_data(), 'uom.uom')
        self.assertIn(
            self.product.uom_bag_id.id, uoms,
            "UoM Bag harus ada di cache client, kalau tidak konversi bag mustahil.",
        )
        self.assertTrue(uoms[self.product.uom_bag_id.id].get('factor'))

    # ------------------------------------------------------------------
    # 3. Payload quant: isi pallet per lot harus terbaca
    # ------------------------------------------------------------------
    def test_03_payload_quant_membawa_isi_pallet_per_lot(self):
        """Sumber demand & kapasitas Bulk Entry -- kalau field ini hilang, 0 lagi."""
        pallet, quants = self._make_pallet()

        records = quants.get_stock_barcode_data_records()['records']['stock.quant']
        self.assertEqual(len(records), len(self.qty_by_lot_name))
        for field in ('product_id', 'lot_id', 'package_id', 'quantity'):
            self.assertIn(field, records[0], "Field %s hilang dari payload quant." % field)

        lot_name_by_id = {lot.id: lot.name for lot in self.lots}
        self.assertEqual(
            {lot_name_by_id[rec['lot_id']]: rec['quantity'] for rec in records},
            self.qty_by_lot_name,
        )
        self.assertEqual(
            {rec['package_id'] for rec in records}, {pallet.id},
        )

    # ------------------------------------------------------------------
    # 4. Kapasitas Bulk Entry tidak nol
    # ------------------------------------------------------------------
    def test_04_kapasitas_bulk_entry_tidak_nol(self):
        """480 kg = 80 BOX; sebelum fix totalnya 0 -> Bulk Entry ditolak."""
        pallet, quants = self._make_pallet()
        picking = self._make_empty_p2p_picking()
        sim, lines = self._scan(picking, quants)

        capacities = sim.bulk_capacities(lines)
        expected = [
            int(math.floor(line['qty_done'] / self.bag_ratio)) for line in lines
        ]
        self.assertEqual(capacities, expected)
        # Isi tiap lot di skenario ini kelipatan bag, jadi total kapasitas sama
        # dengan isi pallet. (Kalau tidak bulat, tiap lot dibulatkan ke bawah
        # sendiri-sendiri -- lihat test_09.)
        self.assertEqual(sorted(capacities), sorted(self.bag_by_lot_name.values()))
        self.assertEqual(sum(capacities), int(self.total_bag))
        self.assertTrue(
            sum(capacities),
            "Kapasitas 0 = pesan 'Tidak ada quantity yang bisa dibagikan pada pallet ini.'",
        )

    # ------------------------------------------------------------------
    # 5. Demand tampil sejak scan
    # ------------------------------------------------------------------
    def test_05_demand_bag_tampil_sejak_scan(self):
        """Yang dilaporkan: "0 BOX / 80 BOX" baru muncul setelah back + masuk lagi."""
        pallet, quants = self._make_pallet()
        picking = self._make_empty_p2p_picking()
        sim, lines = self._scan(picking, quants)

        self.assertTrue(sim.has_bag_uom(lines), "Line harus dirender dalam UoM bag.")
        self.assertEqual(sim.computed_bag_qty(lines), 0.0, "Belum ada bag yang diisi operator.")
        self.assertEqual(sim.computed_bag_demand(lines), self.total_bag)
        self.assertTrue(
            sim.shows_demand(lines),
            "Tanpa ini bagian '/80 BOX' tidak dirender sama sekali.",
        )

        # Per subline juga harus benar, bukan cuma totalnya.
        self.assertEqual(
            sorted(sim.bag_demand(line) for line in lines),
            sorted(qty / self.bag_ratio for qty in self.qty_by_lot_name.values()),
        )

    # ------------------------------------------------------------------
    # 6. Reservasi asli tetap menang atas isi pallet
    # ------------------------------------------------------------------
    def test_06_reservasi_menang_atas_isi_pallet(self):
        """Line yang memang punya reservasi tidak boleh ikut memakai isi pallet."""
        pallet, quants = self._make_pallet()
        picking = self._make_empty_p2p_picking()
        sim, lines = self._scan(picking, quants)

        reserved_line = lines[0]
        pallet_qty = sim.get_scanned_package_qty(reserved_line)
        reserved_line['reserved_uom_qty'] = self.bag_ratio * 3  # 3 bag saja
        self.assertNotEqual(pallet_qty, reserved_line['reserved_uom_qty'])

        self.assertEqual(sim.bag_demand(reserved_line), 3.0)
        self.assertEqual(
            sim.computed_bag_demand(lines),
            sim._round2(3.0 + sum(
                qty / self.bag_ratio
                for qty in list(self.qty_by_lot_name.values())[1:]
            )),
        )

    # ------------------------------------------------------------------
    # 7. Bulk Entry mengubah qty, bukan demand
    # ------------------------------------------------------------------
    def test_07_bulk_entry_tidak_menggerus_demand(self):
        """Demand bersumber dari isi pallet, jadi kebal terhadap perubahan qty_done.

        Kalau sumbernya `qty_done`, angka "/80 BOX" akan menyusut sendiri setiap
        operator mengisi Bulk Entry -- justru bikin bingung.
        """
        pallet, quants = self._make_pallet()
        picking = self._make_empty_p2p_picking()
        sim, lines = self._scan(picking, quants)

        demand_before = sim.computed_bag_demand(lines)
        capacities = sim.bulk_capacities(lines)

        # Operator mengisi 10 bag: dibagikan ke line sesuai urutan kapasitas,
        # persis `openBulkEntry()`.
        remaining = 10
        for line, max_bag in zip(lines, capacities):
            assign = min(remaining, max_bag)
            remaining -= assign
            sim.apply_bulk_bag_qty(line, assign)
        self.assertEqual(remaining, 0)

        self.assertEqual(sim.computed_bag_qty(lines), 10.0)
        self.assertEqual(
            sim.computed_bag_demand(lines), demand_before,
            "Demand harus tetap 80 BOX walau qty_done sudah dipangkas Bulk Entry.",
        )
        self.assertTrue(sim.shows_demand(lines))

    # ------------------------------------------------------------------
    # 8. Pallet campur produk
    # ------------------------------------------------------------------
    def test_08_pallet_campur_produk_tidak_saling_mencampur_demand(self):
        """Isi pallet dicatat per (pallet, produk, lot), jadi tiap grup berdiri sendiri."""
        pallet, _ = self._make_pallet()
        qty_other = self.product_other.uom_bag_id.factor / self.product_other.uom_id.factor * 2
        pallet, quants = self._make_pallet(
            qty_by_lot_name={'UT-P2P-LOT-OTHER': qty_other},
            product=self.product_other,
        )
        picking = self._make_empty_p2p_picking()
        sim, lines = self._scan(picking, quants)

        first = [line for line in lines if line['product_id'] == self.product.id]
        other = [line for line in lines if line['product_id'] == self.product_other.id]
        self.assertEqual(len(first), len(self.qty_by_lot_name))
        self.assertEqual(len(other), 1)

        self.assertEqual(sim.computed_bag_demand(first), self.total_bag)
        self.assertEqual(sim.computed_bag_demand(other), 2.0)
        self.assertEqual(sim.bulk_capacities(other), [2])

    # ------------------------------------------------------------------
    # 9. Qty yang tidak habis dibagi bag
    # ------------------------------------------------------------------
    def test_09_qty_tidak_bulat_dalam_bag(self):
        """Demand dibulatkan 2 desimal, kapasitas Bulk Entry dibulatkan ke bawah."""
        sisa = self.bag_ratio / 2  # setengah bag, tidak bisa jadi bag utuh
        pallet, quants = self._make_pallet(
            name='UT-SPJ-PALLET-SISA',
            qty_by_lot_name={'UT-P2P-LOT-SISA': self.bag_ratio * 46 + sisa},
        )
        picking = self._make_empty_p2p_picking()
        sim, lines = self._scan(picking, quants)

        expected_demand = sim._round2(46 + sisa / self.bag_ratio)
        self.assertEqual(sim.computed_bag_demand(lines), expected_demand)
        self.assertNotEqual(expected_demand, 46.0, "Skenario ini harus punya pecahan bag.")
        self.assertEqual(
            sim.bulk_capacities(lines), [46],
            "Bulk Entry tidak boleh menawarkan bag yang isinya tidak penuh.",
        )
        self.assertTrue(sim.shows_demand(lines))

    # ------------------------------------------------------------------
    # 10. Line tanpa pallet tidak boleh dapat demand palsu
    # ------------------------------------------------------------------
    def test_10_line_tanpa_pallet_tidak_dapat_demand_palsu(self):
        """Produk lepas hasil scan memang tidak punya demand -- jangan dikarang."""
        pallet, quants = self._make_pallet()
        picking = self._make_empty_p2p_picking()
        sim, lines = self._scan(picking, quants)

        loose = dict(lines[0], package_id=False, lot_id=False)
        self.assertEqual(sim.get_scanned_package_qty(loose), 0)
        self.assertEqual(sim.bag_demand(loose), 0)
        self.assertFalse(
            sim.shows_demand([loose]),
            "Line tanpa pallet dan tanpa reservasi tidak boleh menampilkan demand.",
        )

        # Pallet lain yang belum pernah di-scan juga tidak boleh nyangkut.
        unknown = dict(lines[0], package_id=lines[0]['package_id'] + 999999)
        self.assertEqual(sim.get_scanned_package_qty(unknown), 0)

    # ------------------------------------------------------------------
    # 11. Tampilan saat scan == tampilan setelah back lalu masuk lagi
    # ------------------------------------------------------------------
    def test_11_demand_sama_sebelum_dan_sesudah_reload(self):
        """Inti keluhannya: angkanya berubah setelah dokumen dibuka ulang."""
        pallet, quants = self._make_pallet()
        picking = self._make_empty_p2p_picking()
        sim_scan, lines_scan = self._scan(picking, quants)
        demand_scan = sim_scan.computed_bag_demand(lines_scan)
        qty_scan = sim_scan.computed_bag_qty(lines_scan)

        self._save_scanned_lines(picking, lines_scan)
        sim_reload, lines_reload = self._reload(picking)

        self.assertEqual(len(lines_reload), len(lines_scan))
        self.assertTrue(sim_reload.has_bag_uom(lines_reload))
        self.assertEqual(
            sim_reload.computed_bag_demand(lines_reload), demand_scan,
            "Demand tidak boleh berubah hanya karena dokumen dibuka ulang.",
        )
        self.assertEqual(sim_reload.computed_bag_qty(lines_reload), qty_scan)
        self.assertEqual(sim_reload.shows_demand(lines_reload), sim_scan.shows_demand(lines_scan))

        # Sekalian pastikan field related di server memang terisi seperti yang
        # sudah ditebak client saat scan.
        smls = picking.move_line_ids
        self.assertEqual(
            set(smls.mapped('uom_bag_id').ids), {self.product.uom_bag_id.id},
        )
        self.assertEqual(
            set(smls.mapped('uom_pallet_id').ids), {self.product.uom_pallet_id.id},
        )
        # `autofill_pack_qty` mati pada P2P: bag_qty tetap 0 sampai Bulk Entry.
        self.assertFalse(self.type_p2p.autofill_pack_qty)
        self.assertEqual(set(smls.mapped('bag_qty')), {0.0})
