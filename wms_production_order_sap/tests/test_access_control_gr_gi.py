"""Audit record rule `sttl_warehouse_access_control` + alur GR/GI per user.

Latar belakang
--------------
Dua record rule di modul pihak ketiga `sttl_warehouse_access_control` sekarang
diakhiri `(1, '=', 1)`:

    rule_stock_picking_type_access_base_group
        ['|', ('id','in',user.allowed_operation_types.ids), (1,'=',1)]
    rule_stock_picking_access_base_group
        ['|','|','|', ('location_dest_id','in',user.allowed_location_ids.ids),
                      ('location_id','child_of',user.allowed_location_ids.ids),
                      ('bool_picking_flag','=',user.check_location), (1,'=',1)]

`(1,'=',1)` di dalam OR membuat SELURUH rule selalu benar, jadi keduanya
efektif mati. `rule_stock_move_access_base_group` sudah di-archive dan memang
tidak dipakai. Test ini menjawab: **apa yang rusak kalau `(1,'=',1)` dilepas?**

Yang diuji
----------
Kelas 1 (`TestSttlRecordRuleAudit`) memeriksa domain rule-nya sendiri: bentuk
yang terpasang sekarang, escape hatch `bool_* = check_*`, kebocoran lewat
lokasi view, asimetri `in` vs `child_of`, dan flag `noupdate`.

Kelas 2 (`TestGrFlowPerUser`) menjalankan rantai GR 1601 sampai selesai dengan
rule versi ketat (tanpa `(1,'=',1)`), tiap langkah memakai user aslinya:

    plant2.groupa  QR Scanner GR FG   Inbound FG Production (21)
    angga          Barcode/Operations Checker IN (22)
    sutresno       Barcode/Operations Forklift - GR - FG (14)

Kelas 3 (`TestGiFlowPerUser`) menjalankan rantai outbound 1601:

    sunardi         Pick (11)             Checker Out (60)  djunaedi
    djunaedi        Loading (57)          STO SS - Final (30)
    kurnia.widiarta STO SS - Good Issue (31)

Semua memakai `TransactionCase`, jadi picking/lot/quant hasil test di-rollback.
Efek samping yang tidak ikut rollback: nomor urut `ir.sequence` yang terpakai.

Jalankan::

    D:\\CPP\\Odoo19-ENT\\python\\python.exe odoo-bin -c wms.conf \\
        --test-enable --test-tags sttl_access --stop-after-init --no-http
"""

import logging
import re

from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.modules.module import get_module_path
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

RULE_PT = 'sttl_warehouse_access_control.rule_stock_picking_type_access_base_group'
RULE_PICKING = 'sttl_warehouse_access_control.rule_stock_picking_access_base_group'
RULE_MOVE = 'sttl_warehouse_access_control.rule_stock_move_access_base_group'

# Bentuk "ketat": persis seperti XML aslinya, hanya tanpa `(1,'=',1)`.
STRICT_PT_DOMAIN = (
    "['|', ('id', 'in', user.allowed_operation_types.ids),"
    " ('bool_picking_type', '=', user.check_operation)]"
)
STRICT_PICKING_DOMAIN = (
    "['|', '|', ('location_dest_id', 'in', user.allowed_location_ids.ids),"
    " ('location_id', 'child_of', user.allowed_location_ids.ids),"
    " ('bool_picking_flag', '=', user.check_location)]"
)
# Usulan perbaikan: samakan sumbu filternya dengan yang dikonfigurasi user,
# yaitu operation type -- bukan lokasi.
SCOPED_PICKING_DOMAIN = (
    "['|', ('picking_type_id', 'in', user.allowed_operation_types.ids),"
    " ('bool_picking_flag', '=', user.check_operation)]"
)

# Domain action Barcode > Operations (stock_barcode.stock_picking_type_action_kanban).
BARCODE_OPERATIONS_DOMAIN = [('code', 'in', ('incoming', 'outgoing', 'internal'))]

COMPANY_1601 = '1601'


class SttlAccessCommon(TransactionCase):
    """Fixture bersama: company 1601, user-user nyata, dan saklar record rule."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env['res.company'].sudo().search(
            [('name', 'like', COMPANY_1601)], limit=1)
        if not cls.company:
            raise ValueError("Company 1601 tidak ada di database ini.")

        cls.rule_pt = cls.env.ref(RULE_PT, raise_if_not_found=False)
        cls.rule_picking = cls.env.ref(RULE_PICKING, raise_if_not_found=False)
        cls.rule_move = cls.env.ref(
            RULE_MOVE, raise_if_not_found=False)
        if not cls.rule_pt or not cls.rule_picking:
            raise ValueError(
                "Modul sttl_warehouse_access_control belum terinstall di database ini.")

        # Domain apa adanya, untuk dilaporkan di test audit.
        cls.shipped_pt_domain = cls.rule_pt.sudo().domain_force or ''
        cls.shipped_picking_domain = cls.rule_picking.sudo().domain_force or ''

    # ------------------------------------------------------------------
    # helper
    # ------------------------------------------------------------------
    @classmethod
    def _user(cls, login):
        user = cls.env['res.users'].sudo().with_context(active_test=False).search(
            [('login', '=', login)], limit=1)
        if not user:
            raise ValueError("User %s tidak ada di database ini." % login)
        return user

    def _env_as(self, user, company=None):
        """Environment milik `user`, dikunci ke satu company aktif.

        `angga` dan `sutresno.sutresno` default company-nya 1481, padahal
        rantai yang diuji ada di 1601 -- tanpa `allowed_company_ids` mereka
        tidak akan melihat dokumennya sama sekali (multi-company rule, bukan
        rule sttl).
        """
        company = company or self.company
        return self.env(user=user, context=dict(
            self.env.context,
            allowed_company_ids=[company.id],
        ))

    def _set_rule(self, rule, domain):
        """Tulis domain rule di dalam transaksi test (otomatis di-rollback).

        `ir.rule.write()` memanggil `registry.clear_cache()`, jadi
        `_compute_domain` yang ter-ormcache ikut dibuang.
        """
        rule.sudo().write({'active': True, 'domain_force': domain})

    def _refresh_check_flags(self, users):
        """Paksa recompute `check_warehouse/location/operation` yang store=True."""
        users.sudo().modified([
            'allowed_warehouse_ids', 'allowed_location_ids', 'allowed_operation_types'])
        users.sudo().flush_recordset()

    def _apply_strict_rules(self):
        """Pasang domain ketat, lalu BUKTIKAN bypass-nya benar-benar hilang.

        Seluruh test alur bergantung pada ini. Kalau `(1, '=', 1)` masih ikut
        terpasang, setiap assertion di bawahnya jadi tidak bermakna -- jadi
        verifikasinya dikerjakan di sini, tiap `setUp`, bukan diasumsikan.
        """
        self._set_rule(self.rule_pt, STRICT_PT_DOMAIN)
        self._set_rule(self.rule_picking, STRICT_PICKING_DOMAIN)
        self._assert_no_bypass()

    def _assert_no_bypass(self):
        """Tiga lapis bukti bahwa rule benar-benar ketat saat test berjalan."""
        # 1. Teks domain yang benar-benar tersimpan, dibaca ulang dari DB.
        for rule in (self.rule_pt, self.rule_picking):
            rule.invalidate_recordset(['domain_force', 'active'])
            domain_text = (rule.sudo().domain_force or '').replace(' ', '')
            self.assertTrue(
                rule.sudo().active,
                "Rule %s tidak aktif saat test alur berjalan." % rule.name)
            self.assertNotIn(
                "1,'=',1", domain_text,
                "Rule %s masih memuat bypass (1, '=', 1); "
                "test alur tidak membuktikan apa pun." % rule.name)

        # 2. Domain EFEKTIF hasil `_compute_domain()` -- yang benar-benar
        #    dipakai ORM, termasuk kalau ormcache-nya belum dibuang.
        probe = self.env['res.users'].sudo().search([
            ('active', '=', True), ('share', '=', False),
            ('allowed_operation_types', '!=', False),
            ('check_operation', '=', True),
        ], limit=1)
        if not probe:
            return
        env = self.env(user=probe)
        for model in ('stock.picking.type', 'stock.picking'):
            effective = list(env['ir.rule']._compute_domain(model, 'read') or [])
            self.assertNotEqual(
                effective, [(1, '=', 1)],
                "Domain efektif %s untuk %s masih terbuka penuh."
                % (model, probe.login))

        # 3. Dan efeknya nyata di layar: user terbatas tidak melihat semuanya.
        visible = env['stock.picking.type'].search_count(BARCODE_OPERATIONS_DOMAIN)
        total = self.env['stock.picking.type'].sudo().search_count(
            BARCODE_OPERATIONS_DOMAIN + [('company_id', 'in', env.companies.ids)])
        self.assertLess(
            visible, total,
            "Rule tidak menggigit: %s masih melihat %d dari %d operation type."
            % (probe.login, visible, total))

    def _visible_picking_types(self, user, company=None):
        return self._env_as(user, company)['stock.picking.type'].search(
            BARCODE_OPERATIONS_DOMAIN)

    def _expected_picking_types(self, user, company=None):
        """Operation type yang SEHARUSNYA muncul di Barcode/Operations.

        Selain rule sttl, layar itu juga kena rule multi-company global dan
        domain `code in (incoming, outgoing, internal)` milik action-nya.
        """
        env = self._env_as(user, company)
        return user.sudo().allowed_operation_types.filtered(
            lambda t: (t.active
                       and t.code in ('incoming', 'outgoing', 'internal')
                       and t.company_id.id in env.companies.ids))

    def _visible_pickings(self, user, extra_domain=None, company=None):
        domain = list(extra_domain or [])
        return self._env_as(user, company)['stock.picking'].search(domain)


@tagged('post_install', '-at_install', 'sttl_access')
class TestSttlRecordRuleAudit(SttlAccessCommon):
    """Pemeriksaan bentuk record rule-nya sendiri, tanpa menjalankan alur."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.u_plant = cls._user('plant2.groupa')
        cls.u_checker = cls._user('angga')
        cls.u_forklift = cls._user('sutresno.sutresno')

    # ------------------------------------------------------------------
    def test_01_deployed_domain_matches_the_module_xml(self):
        """Domain di DATABASE harus sama dengan yang ada di XML modul.

        Ini perangkap paling mudah menjebak di modul ini: kedua rule ada di
        dalam blok `<data noupdate="1">`, jadi mengedit
        `security/warehouse_security.xml` -- termasuk membuang `(1, '=', 1)` --
        **tidak** ikut terpasang oleh `-u sttl_warehouse_access_control`.
        Record lama di database tetap dipakai, dan pembatasannya tetap mati
        tanpa ada tanda apa pun di log.

        Kalau test ini merah, XML dan database sudah berbeda. Perbaikannya:
        ubah record-nya langsung (Settings > Technical > Record Rules, atau
        skrip ORM), atau lepas dulu `noupdate` lalu upgrade modulnya.
        """
        xml_domains = self._module_xml_domains()
        for rule, xmlid in ((self.rule_pt, RULE_PT), (self.rule_picking, RULE_PICKING)):
            key = xmlid.split('.')[1]
            with self.subTest(rule=key):
                self.assertIn(key, xml_domains, "Rule %s hilang dari XML." % key)
                self.assertEqual(
                    self._normalize(rule.sudo().domain_force),
                    self._normalize(xml_domains[key]),
                    "Domain %s di database berbeda dengan XML modul.\n"
                    "  database: %s\n"
                    "  xml     : %s\n"
                    "Blok XML-nya noupdate=\"1\", jadi `-u` tidak menimpanya."
                    % (key, self._normalize(rule.sudo().domain_force),
                       self._normalize(xml_domains[key])))

    def test_01b_deployed_domains_have_no_bypass(self):
        """Rule terpasang tidak boleh memuat `(1, '=', 1)`.

        `(1, '=', 1)` di dalam OR membuat seluruh rule selalu benar -- bukan
        sekadar longgar, tapi mati total. Selain memeriksa teksnya, efeknya
        ikut dibuktikan: hasil pencarian dengan rule terpasang harus BERBEDA
        dari hasil ketika rule-nya dimatikan.
        """
        for rule in (self.rule_pt, self.rule_picking):
            with self.subTest(rule=rule.name):
                self.assertNotIn(
                    "1,'=',1", self._normalize(rule.sudo().domain_force),
                    "Rule %s masih memuat bypass (1, '=', 1) di database; "
                    "tidak ada pembatasan apa pun yang berlaku." % rule.name)

        # Dibandingkan dengan rule dimatikan, bukan dengan sudo(), supaya rule
        # multi-company global tetap ikut berlaku di kedua sisi.
        with_rule = self._visible_picking_types(self.u_checker).ids
        self.rule_pt.sudo().write({'active': False})
        without_rule = self._visible_picking_types(self.u_checker).ids
        self.assertNotEqual(
            set(with_rule), set(without_rule),
            "Rule picking type tidak mengubah apa pun untuk %s -- "
            "efektif mati." % self.u_checker.login)

    def test_01c_allowed_warehouse_ids_is_not_used_by_any_rule(self):
        """`allowed_warehouse_ids` TIDAK membatasi apa pun.

        Field itu hanya dipakai sebagai domain widget di form user
        (`allowed_location_ids` dan `allowed_operation_types` memfilter
        pilihannya) dan oleh `onchange_fill_location_by_types()`. Tidak ada
        satu pun record rule yang membacanya, jadi pembatasan per-warehouse
        yang sebenarnya berjalan datang dari rule multi-company bawaan Odoo
        (`company_ids`), bukan dari field ini. Penting dipahami sebelum
        mengandalkan `allowed_warehouse_ids` sebagai kontrol akses.
        """
        rules = self.env['ir.rule'].sudo().search([('active', '=', True)])
        using = rules.filtered(
            lambda r: 'allowed_warehouse_ids' in (r.domain_force or ''))
        self.assertFalse(
            using,
            "Sekarang ada rule yang memakai allowed_warehouse_ids (%s) -- "
            "perbarui test ini." % using.mapped('name'))

        by_field = {
            'allowed_operation_types': rules.filtered(
                lambda r: 'allowed_operation_types' in (r.domain_force or '')),
            'allowed_location_ids': rules.filtered(
                lambda r: 'allowed_location_ids' in (r.domain_force or '')),
        }
        _logger.info(
            "[audit] field konfigurasi res.users yang benar-benar dipakai "
            "record rule aktif: %s | allowed_warehouse_ids: tidak dipakai "
            "rule mana pun.",
            {k: ['%s (%s)' % (r.name, r.model_id.model) for r in v]
             for k, v in by_field.items()})

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(domain):
        return ''.join((domain or '').split())

    def _module_xml_domains(self):
        """Baca domain_force tiap rule langsung dari XML modulnya."""
        path = get_module_path('sttl_warehouse_access_control')
        with open('%s/security/warehouse_security.xml' % path,
                  encoding='utf-8') as fh:
            content = fh.read()

        result = {}
        pattern = re.compile(
            r'<record\s+id="(?P<id>[^"]+)"[^>]*model="ir\.rule"[^>]*>'
            r'(?P<body>.*?)</record>', re.S)
        domain_re = re.compile(
            r'<field\s+name="domain_force"\s*>(?P<domain>.*?)</field>', re.S)
        for match in pattern.finditer(content):
            body = match.group('body')
            domain = domain_re.search(body)
            if domain:
                result[match.group('id')] = domain.group('domain')
        return result

    def test_02_the_two_rules_under_review_are_noupdate(self):
        """Blok `<data noupdate="1">` -- `-u` TIDAK akan menimpa domain di DB.

        Konsekuensinya: memperbaiki `warehouse_security.xml` saja tidak cukup;
        record di database harus diubah lewat UI/skrip, atau `noupdate`-nya
        dilepas dulu. Sebagian rule versi manager justru sudah ber-`noupdate`
        False (pernah ditulis ulang), jadi campuran ini perlu dicatat.
        """
        imds = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'sttl_warehouse_access_control'),
            ('model', '=', 'ir.rule'),
        ])
        self.assertTrue(imds)
        under_review = imds.filtered(
            lambda i: i.name in (RULE_PT.split('.')[1], RULE_PICKING.split('.')[1]))
        self.assertEqual(len(under_review), 2)
        self.assertTrue(
            all(imd.noupdate for imd in under_review),
            "Rule yang sedang ditinjau sudah tidak noupdate -- `-u` akan "
            "menimpa domain di DB, sesuaikan test ini.")
        mutable = imds.filtered(lambda i: not i.noupdate)
        if mutable:
            _logger.info(
                "[audit] rule sttl yang noupdate=False (akan tertimpa `-u`): %s",
                mutable.mapped('name'))

    def test_03_move_rule_archived_leaves_stock_move_unrestricted(self):
        """`rule_stock_move_access_base_group` archived -> stock.move terbuka.

        Ini memang disengaja, tapi perlu dicatat: karena rule stock.move.line
        juga masih dikomentari di XML, dua model yang justru dibaca layar
        Barcode tidak dibatasi sama sekali. Membatasi stock.picking tanpa
        membatasi move/move line hanya menyembunyikan header dokumennya.
        """
        if self.rule_move:
            self.assertFalse(
                self.rule_move.sudo().active,
                "rule_stock_move_access_base_group ternyata masih aktif.")

        self._apply_strict_rules()
        checker_in = self.env['stock.picking.type'].sudo().search([
            ('company_id', '=', self.company.id),
            ('sequence_code', '=', 'CHECK'), ('active', '=', True)], limit=1)
        foreign_move = self.env['stock.move'].sudo().search(
            [('picking_id.picking_type_id', '=', checker_in.id)], limit=1)
        if not foreign_move:
            self.skipTest("Belum ada stock.move Checker IN di database ini.")

        # `sutresno` tidak punya operation type Checker IN, tapi move-nya
        # tetap terbaca -- termasuk field bisnisnya.
        as_forklift = self._env_as(self.u_forklift)['stock.move'].browse(foreign_move.id)
        self.assertTrue(as_forklift.exists())
        self.assertTrue(as_forklift.product_id)
        self.assertEqual(
            as_forklift.read(['product_id', 'quantity', 'state'])[0]['state'],
            foreign_move.state,
            "stock.move ternyata ikut terbatas -- ada rule lain yang bermain.")

    def test_04_strict_picking_type_rule_matches_user_configuration(self):
        """Tanpa `(1,'=',1)`, rule picking type SUDAH benar.

        Untuk user yang punya `allowed_operation_types`, cabang
        `bool_picking_type = check_operation` tidak pernah cocok
        (`bool_picking_type` default False, `check_operation` True), jadi yang
        tersisa persis daftar operation type-nya.
        """
        self._set_rule(self.rule_pt, STRICT_PT_DOMAIN)

        for user in (self.u_plant, self.u_checker, self.u_forklift):
            with self.subTest(login=user.login):
                expected = self._expected_picking_types(user)
                visible = self._visible_picking_types(user)
                self.assertEqual(
                    set(visible.ids), set(expected.ids),
                    "Menu Barcode/Operations untuk %s tidak sama dengan "
                    "allowed_operation_types.\nmuncul : %s\nseharusnya: %s"
                    % (user.login,
                       visible.mapped('display_name'),
                       expected.mapped('display_name')))

    def test_05_strict_picking_type_rule_hides_other_stations(self):
        """Negatif: operator GR FG tidak boleh melihat station Checker IN, dst."""
        self._set_rule(self.rule_pt, STRICT_PT_DOMAIN)

        checker_in = self.env['stock.picking.type'].sudo().search([
            ('company_id', '=', self.company.id),
            ('sequence_code', '=', 'CHECK'),
            ('active', '=', True),
        ], limit=1)
        gr_fg = self.env['stock.picking.type'].sudo().search([
            ('company_id', '=', self.company.id),
            ('sequence_code', '=', 'GR-FG'),
            ('active', '=', True),
        ], limit=1)
        self.assertTrue(checker_in and gr_fg)

        self.assertNotIn(checker_in.id, self._visible_picking_types(self.u_plant).ids)
        self.assertNotIn(gr_fg.id, self._visible_picking_types(self.u_plant).ids)
        self.assertNotIn(gr_fg.id, self._visible_picking_types(self.u_checker).ids)
        self.assertNotIn(checker_in.id, self._visible_picking_types(self.u_forklift).ids)

    def test_06_rules_fail_open_for_users_without_configuration(self):
        """Cabang `bool_* = check_*` membuat rule **gagal terbuka**.

        User internal tanpa `allowed_operation_types` -> `check_operation`
        False -> cocok dengan `bool_picking_type` yang default False -> semua
        operation type kelihatan. Sama untuk lokasi/picking. Jadi rule ketat
        pun tidak menutup user yang belum dikonfigurasi; itu keputusan desain
        yang harus disadari, bukan bug tersembunyi.
        """
        self._apply_strict_rules()

        unconfigured = self.env['res.users'].sudo().search([
            ('share', '=', False),
            ('active', '=', True),
            ('allowed_operation_types', '=', False),
            ('id', '!=', self.env.ref('base.user_root').id),
        ], limit=1)
        if not unconfigured:
            self.skipTest("Semua user internal sudah punya allowed_operation_types.")

        visible_before = self._visible_picking_types(unconfigured).ids
        self.rule_pt.sudo().write({'active': False})
        visible_without_rule = self._visible_picking_types(unconfigured).ids
        self.assertEqual(
            set(visible_before), set(visible_without_rule),
            "User %s tanpa konfigurasi ternyata TIDAK melihat semua operation "
            "type -- asumsi fail-open sudah berubah." % unconfigured.login)

        _logger.warning(
            "[audit] %d user internal aktif belum punya allowed_operation_types "
            "dan karenanya melihat SELURUH operation type walau rule diketatkan.",
            self.env['res.users'].sudo().search_count([
                ('share', '=', False), ('active', '=', True),
                ('allowed_operation_types', '=', False)]))

    def test_06b_stored_check_flags_are_stale_for_some_users(self):
        """Temuan paling berbahaya: `check_*` itu compute **store=True**.

        `check_warehouse` / `check_location` / `check_operation` dihitung dari
        `allowed_*`. Kalau relasinya pernah diisi lewat jalur yang tidak
        memicu recompute (import/SQL/`write` di modul lain), nilai tersimpan
        bisa tertinggal False padahal daftarnya terisi. Karena rule memakai
        `('bool_x', '=', user.check_x)` sebagai escape hatch, satu flag basi
        langsung **membuka seluruh model** untuk user itu -- persis kasus
        `kurnia.widiarta`.
        """
        self._set_rule(self.rule_pt, STRICT_PT_DOMAIN)

        users = self.env['res.users'].sudo().search([
            ('share', '=', False), ('active', '=', True),
            ('allowed_operation_types', '!=', False),
        ])
        stale = users.filtered(lambda u: not u.check_operation)
        stale_loc = self.env['res.users'].sudo().search([
            ('share', '=', False), ('active', '=', True),
            ('allowed_location_ids', '!=', False),
        ]).filtered(lambda u: not u.check_location)

        if stale:
            _logger.warning(
                "[audit] %d user punya allowed_operation_types tapi "
                "check_operation masih False -> rule picking type terbuka "
                "penuh untuk mereka: %s", len(stale), stale.mapped('login'))
            probe = stale[0]
            visible_before = self._visible_picking_types(probe).ids
            self.rule_pt.sudo().write({'active': False})
            self.assertEqual(
                set(visible_before), set(self._visible_picking_types(probe).ids),
                "Flag basi seharusnya membuka semua operation type untuk %s."
                % probe.login)
        if stale_loc:
            _logger.warning(
                "[audit] %d user punya allowed_location_ids tapi check_location "
                "masih False -> rule stock.picking terbuka penuh: %s",
                len(stale_loc), stale_loc.mapped('login'))

        self.assertFalse(
            stale or stale_loc,
            "Flag `check_*` basi untuk %d user (operation) / %d user (location). "
            "Recompute dulu sebelum melepas `(1,'=',1)`, mis. lewat "
            "`env['res.users'].search([]).modified(['allowed_operation_types',"
            " 'allowed_location_ids', 'allowed_warehouse_ids'])` atau "
            "`--update` pada modulnya."
            % (len(stale), len(stale_loc)))

    def test_07_picking_rule_leaks_through_the_warehouse_view_location(self):
        """Inti masalahnya: rule picking memfilter LOKASI, bukan operation type.

        `res.users.onchange_fill_location_by_types()` selalu menambahkan
        lokasi ber-`usage='view'` milik warehouse ke `allowed_location_ids`.
        Lokasi view itu induk dari semua lokasi warehouse, sehingga cabang
        `('location_id','child_of', allowed)` cocok dengan hampir seluruh
        dokumen warehouse tersebut. Hasilnya: pembatasan operation type tidak
        berpengaruh apa-apa terhadap stock.picking.
        """
        self._apply_strict_rules()

        view_locations = self.u_forklift.sudo().allowed_location_ids.filtered(
            lambda l: l.usage == 'view')
        self.assertTrue(
            view_locations,
            "Konfigurasi berubah: allowed_location_ids sudah tidak memuat "
            "lokasi view -- kebocoran di bawah ini mungkin sudah tidak ada.")

        # Dokumen Checker IN adalah station milik `angga`, bukan `sutresno`.
        checker_in = self.env['stock.picking.type'].sudo().search([
            ('company_id', '=', self.company.id),
            ('sequence_code', '=', 'CHECK'), ('active', '=', True)], limit=1)
        foreign = self.env['stock.picking'].sudo().search(
            [('picking_type_id', '=', checker_in.id)], limit=5)
        if not foreign:
            self.skipTest("Belum ada dokumen Checker IN di database ini.")

        leaked = self._visible_pickings(
            self.u_forklift, [('id', 'in', foreign.ids)])
        self.assertTrue(
            leaked,
            "Kebocoran sudah tidak terjadi -- rule picking mungkin sudah "
            "diperbaiki, sesuaikan test ini.")
        _logger.warning(
            "[audit] %s melihat %d/%d dokumen Checker IN padahal operation "
            "type itu tidak ada di konfigurasinya (bocor lewat lokasi view %s).",
            self.u_forklift.login, len(leaked), len(foreign),
            view_locations.mapped('complete_name'))

    def test_08_scoped_domain_closes_the_leak(self):
        """Filter berdasarkan `picking_type_id` menutup kebocoran test_07."""
        self._set_rule(self.rule_pt, STRICT_PT_DOMAIN)
        self._set_rule(self.rule_picking, SCOPED_PICKING_DOMAIN)

        checker_in = self.env['stock.picking.type'].sudo().search([
            ('company_id', '=', self.company.id),
            ('sequence_code', '=', 'CHECK'), ('active', '=', True)], limit=1)
        foreign = self.env['stock.picking'].sudo().search(
            [('picking_type_id', '=', checker_in.id)], limit=5)
        if not foreign:
            self.skipTest("Belum ada dokumen Checker IN di database ini.")

        self.assertFalse(
            self._visible_pickings(self.u_forklift, [('id', 'in', foreign.ids)]),
            "Domain berbasis picking_type_id masih membocorkan dokumen Checker IN.")
        # dan station-nya sendiri tetap terlihat oleh pemiliknya
        self.assertTrue(
            self._visible_pickings(self.u_checker, [('id', 'in', foreign.ids)]),
            "Domain berbasis picking_type_id malah menutup dokumen milik angga.")

    def test_09_dest_location_uses_in_while_source_uses_child_of(self):
        """Asimetri `in` vs `child_of` -- bug laten kalau lokasi view dilepas.

        Dokumen yang tujuannya sub-bin (mis. Bin to Bin ke `FINI/1601/<bin>`)
        hanya lolos lewat cabang `location_id child_of`. Begitu lokasi view
        tidak lagi ikut terdaftar, dokumen semacam itu hilang dari layar
        operator walaupun operation type-nya sudah benar.
        """
        stock_loc = self.env['stock.warehouse'].sudo().search(
            [('company_id', '=', self.company.id)], limit=1).lot_stock_id
        bin_loc = self.env['stock.location'].sudo().create({
            'name': 'UT-ACL-BIN',
            'location_id': stock_loc.id,
            'usage': 'internal',
            'company_id': self.company.id,
        })
        int_type = self.env['stock.picking.type'].sudo().search([
            ('company_id', '=', self.company.id),
            ('sequence_code', '=', 'INT'), ('active', '=', True)], limit=1)
        self.assertTrue(int_type, "Operation type Bin to Bin tidak ditemukan.")

        # Sumbernya sengaja DI LUAR lokasi yang diizinkan, supaya yang diuji
        # murni cabang tujuan.
        outside_src = self.env['stock.picking.type'].sudo().search([
            ('company_id', '=', self.company.id),
            ('sequence_code', '=', 'PICK'), ('active', '=', True),
        ], limit=1).default_location_dest_id
        self.assertTrue(outside_src and not outside_src._child_of(stock_loc))

        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': int_type.id,
            'location_id': outside_src.id,
            'location_dest_id': bin_loc.id,
            'company_id': self.company.id,
        })

        # Konfigurasi realistis TANPA lokasi view: hanya lokasi stok warehouse.
        self.u_forklift.sudo().write({
            'allowed_location_ids': [(6, 0, stock_loc.ids)]})
        self._apply_strict_rules()

        self.assertFalse(
            self._visible_pickings(self.u_forklift, [('id', '=', picking.id)]),
            "Diharapkan hilang: `location_dest_id in` tidak menjangkau sub-bin.")

        # Buktikan penyebabnya memang operator `in`, bukan hal lain.
        self._set_rule(self.rule_picking, STRICT_PICKING_DOMAIN.replace(
            "('location_dest_id', 'in',", "('location_dest_id', 'child_of',"))
        self.assertTrue(
            self._visible_pickings(self.u_forklift, [('id', '=', picking.id)]),
            "Dengan `child_of` di sisi tujuan dokumen seharusnya terlihat.")

    def test_10_domains_are_valid_against_the_models(self):
        """Domain ketat harus tetap lolos validasi ORM (tidak ada field salah)."""
        eval_context = self.env['ir.rule'].sudo()._eval_context()
        for model, domain in (
            ('stock.picking.type', STRICT_PT_DOMAIN),
            ('stock.picking', STRICT_PICKING_DOMAIN),
            ('stock.picking', SCOPED_PICKING_DOMAIN),
        ):
            with self.subTest(model=model):
                parsed = safe_eval(domain, dict(eval_context))
                Domain(parsed).validate(self.env[model].sudo())


class SttlFlowCommon(SttlAccessCommon):
    """Fixture untuk dua kelas alur: rule ketat + helper validate per user."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env['ir.config_parameter'].sudo()
        if not icp.get_param('prod_in_move_type'):
            icp.set_param('prod_in_move_type', 'Productioncode')
        icp.set_param('upload_stock', 'false')

    def setUp(self):
        super().setUp()
        # Semua test alur berjalan dengan rule versi ketat, dan dengan flag
        # `check_*` yang sudah di-recompute -- kalau tidak, rule-nya terbuka
        # penuh untuk sebagian user dan alurnya tidak menguji apa pun.
        self._refresh_check_flags(self._flow_users())
        self._apply_strict_rules()

    def _flow_users(self):
        return self.env['res.users'].sudo().browse([])

    # ------------------------------------------------------------------
    def _assert_station_visible(self, user, picking, company=None):
        """Cek dua hal sekaligus, seperti yang dilihat operator di layar.

        1. Operation type dokumen ada di menu Barcode/Operations user itu.
        2. Dokumennya sendiri terbaca oleh user itu.
        """
        types = self._visible_picking_types(user, company)
        self.assertIn(
            picking.picking_type_id.id, types.ids,
            "Operation type %s tidak muncul di Barcode/Operations milik %s."
            % (picking.picking_type_id.display_name, user.login))
        self.assertTrue(
            self._visible_pickings(user, [('id', '=', picking.id)], company),
            "Dokumen %s tidak terbaca oleh %s." % (picking.name, user.login))

    def _assert_station_hidden(self, user, picking_type):
        self.assertNotIn(
            picking_type.id, self._visible_picking_types(user).ids,
            "Operation type %s seharusnya tidak muncul untuk %s."
            % (picking_type.display_name, user.login))

    def _package(self, name, company=None):
        return self.env['stock.package'].sudo().create({
            'name': name, 'company_id': (company or self.company).id})

    def _validate_as(self, user, picking, context=None, company=None):
        """`button_validate()` dijalankan sebagai `user`, bukan sebagai admin."""
        env = self._env_as(user, company)
        if context:
            env = env(context=dict(env.context, **context))
        doc = env['stock.picking'].browse(picking.id)
        res = doc.button_validate()
        self.assertNotIsInstance(
            res, dict,
            "button_validate %s (user %s) minta wizard tambahan: %s"
            % (picking.name, user.login, res))
        picking.invalidate_recordset()
        self.assertEqual(
            picking.state, 'done',
            "Dokumen %s tidak selesai setelah divalidasi %s."
            % (picking.name, user.login))
        return res

    def _next_picking(self, picking, picking_type):
        """Dokumen lanjutan hasil push rule dari `picking`."""
        nxt = picking.sudo().move_ids.move_dest_ids.picking_id.filtered(
            lambda p: p.picking_type_id == picking_type)
        self.assertTrue(
            nxt, "Push rule tidak membuat dokumen %s setelah %s."
            % (picking_type.display_name, picking.name))
        return nxt[0]


@tagged('post_install', '-at_install', 'sttl_access', 'sttl_access_gr')
class TestGrFlowPerUser(SttlFlowCommon):
    """Rantai GR 1601 lengkap: QR Scanner GR FG -> Checker IN -> Forklift GR FG."""

    PO_NUMBER = '160110003518'
    PRODUCTION_LINE_CODE = '07'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.u_plant = cls._user('plant2.groupa')
        cls.u_checker = cls._user('angga')
        cls.u_forklift = cls._user('sutresno.sutresno')

        cls.u_plant_1481 = cls._user('plant1.groupa')

        # Rantai GR ada di dua warehouse dengan bentuk identik; keduanya
        # dijalankan supaya tidak ada station GR yang lolos dari matriks.
        cls.gr_setups = [
            cls._gr_setup(cls.company, cls.u_plant, cls.u_checker, cls.u_forklift,
                          cls.PO_NUMBER, cls.PRODUCTION_LINE_CODE),
        ]
        other = cls.env['stock.warehouse'].sudo().search(
            [('name', 'like', 'FINI')]).company_id - cls.company
        for company in other:
            setup = cls._gr_setup(company, cls.u_plant_1481, cls.u_checker,
                                  cls.u_forklift, False, False)
            if setup:
                cls.gr_setups.append(setup)

        first = cls.gr_setups[0]
        cls.type_gr_prod = first['type_gr_prod']
        cls.type_check_in = first['type_check_in']
        cls.type_gr_fg = first['type_gr_fg']
        cls.po_sap = first['po_sap']
        cls.production_line = first['production_line']

    @classmethod
    def _gr_setup(cls, company, u_plant, u_checker, u_forklift,
                  po_number=False, line_code=False):
        """Kumpulkan operation type + PO SAP + production line satu warehouse.

        Mengembalikan None kalau warehouse itu tidak punya bahan yang cukup
        (mis. belum ada PO SAP terbuka), supaya database lain tetap bisa
        menjalankan test ini.
        """
        PickingType = cls.env['stock.picking.type'].sudo()
        types = {}
        for key, domain in (
            ('type_gr_prod', [('barcode', '=', 'GRPROD')]),
            ('type_check_in', [('sequence_code', '=', 'CHECK')]),
            ('type_gr_fg', [('sequence_code', '=', 'GR-FG')]),
        ):
            types[key] = PickingType.search(
                [('company_id', '=', company.id), ('active', '=', True)] + domain,
                limit=1)
            if not types[key]:
                return None

        po_sap = cls.env['production.order.sap'].sudo().browse([])
        if po_number:
            po_sap = cls.env['production.order.sap'].sudo().search(
                [('po_number', '=', po_number)], limit=1)
        if not po_sap:
            po_sap = cls.env['production.order.sap'].sudo().search([
                ('company_id', '=', company.id),
                ('state', 'in', ('open', 'in_progress')),
                ('active', '=', True),
                ('remaining_qty', '>', 0),
            ], limit=1)
        if not po_sap:
            return None

        ProductionLine = cls.env['production.line'].sudo()
        line = ProductionLine.browse([])
        if line_code:
            line = ProductionLine.search(
                [('company_id', '=', company.id), ('code', '=', line_code)], limit=1)
        if not line:
            line = ProductionLine.search([('company_id', '=', company.id)], limit=1)
        if not line:
            return None

        return dict(types, company=company, po_sap=po_sap, production_line=line,
                    u_plant=u_plant, u_checker=u_checker, u_forklift=u_forklift)

    def _flow_users(self):
        return (self.u_plant | self.u_plant_1481 | self.u_checker
                | self.u_forklift)

    # ------------------------------------------------------------------
    def test_01_menu_scope_per_station(self):
        """Tiap operator hanya melihat station-nya sendiri di Barcode/Operations."""
        for setup in self.gr_setups:
            company = setup['company']
            with self.subTest(company=company.name):
                self.assertEqual(
                    set(self._visible_picking_types(setup['u_plant'], company).ids),
                    {setup['type_gr_prod'].id},
                    "%s seharusnya hanya melihat Inbound FG Production di %s."
                    % (setup['u_plant'].login, company.name))
                self.assertIn(
                    setup['type_check_in'].id,
                    self._visible_picking_types(setup['u_checker'], company).ids)
                self.assertIn(
                    setup['type_gr_fg'].id,
                    self._visible_picking_types(setup['u_forklift'], company).ids)

                # dan tidak melihat station tetangganya
                for user, hidden in (
                    (setup['u_plant'], setup['type_check_in']),
                    (setup['u_plant'], setup['type_gr_fg']),
                    (setup['u_checker'], setup['type_gr_fg']),
                    (setup['u_checker'], setup['type_gr_prod']),
                    (setup['u_forklift'], setup['type_check_in']),
                    (setup['u_forklift'], setup['type_gr_prod']),
                ):
                    self.assertNotIn(
                        hidden.id,
                        self._visible_picking_types(user, company).ids,
                        "Operation type %s seharusnya tidak muncul untuk %s."
                        % (hidden.display_name, user.login))

    def test_02_gr_chain_end_to_end_per_user(self):
        """Alur GR tiap warehouse dijalankan sampai barang masuk lokasi stok.

        Langkah pertama lewat menu QR Scanner GR FG
        (`production.order.sap.action_picking_po_sap_from_qr`), dua langkah
        sisanya lewat Barcode/Operations, masing-masing dengan user aslinya.
        """
        for setup in self.gr_setups:
            with self.subTest(company=setup['company'].name):
                self._run_gr_chain(setup)

    def _run_gr_chain(self, setup):
        company = setup['company']
        po_sap = setup['po_sap']
        u_plant = setup['u_plant']
        u_checker = setup['u_checker']
        u_forklift = setup['u_forklift']

        # --- langkah 1: operator packing lewat menu QR Scanner GR FG --------
        env_plant = self._env_as(u_plant, company)
        before = self.env['stock.picking'].sudo().search(
            [('po_sap_id', '=', po_sap.id)]).ids

        env_plant['production.order.sap'].action_picking_po_sap_from_qr(
            po_sap.po_number, setup['production_line'].code)

        created = self.env['stock.picking'].sudo().search([
            ('po_sap_id', '=', po_sap.id), ('id', 'not in', before)])
        self.assertEqual(
            len(created), 1,
            "QR Scanner GR FG harus membuat tepat satu dokumen, dapat %d."
            % len(created))
        gr_prod = created
        self.assertEqual(gr_prod.picking_type_id, setup['type_gr_prod'])
        self._assert_station_visible(u_plant, gr_prod, company)

        self._prepare_gr_prod_lines(gr_prod, setup)
        self._validate_as(u_plant, gr_prod, context={'pallet_ke_confirmed': True},
                          company=company)

        # --- langkah 2: checker, Checker IN lewat Barcode/Operations --------
        check_in = self._next_picking(gr_prod, setup['type_check_in'])
        self._assert_station_visible(u_checker, check_in, company)
        # operator packing tidak boleh ikut memegang dokumen ini
        self.assertNotIn(
            check_in.picking_type_id.id,
            self._visible_picking_types(u_plant, company).ids)

        check_in.sudo().action_assign()
        self._pick_all_lines(check_in)
        self._validate_as(u_checker, check_in, company=company)

        # --- langkah 3: forklift, Forklift - GR - FG ------------------------
        gr_fg = self._next_picking(check_in, setup['type_gr_fg'])
        self._assert_station_visible(u_forklift, gr_fg, company)
        self.assertNotIn(
            gr_fg.picking_type_id.id,
            self._visible_picking_types(u_checker, company).ids)

        gr_fg.sudo().action_assign()
        self._pick_all_lines(gr_fg, need_result_package=True)
        self._validate_as(u_forklift, gr_fg, company=company)

        # --- hasil akhir ----------------------------------------------------
        warehouse = setup['type_gr_fg'].warehouse_id
        self.assertEqual(gr_fg.location_dest_id, warehouse.lot_stock_id)
        landed = self.env['stock.quant'].sudo().search([
            ('location_id', 'child_of', warehouse.lot_stock_id.id),
            ('product_id', '=', po_sap.product_id.id),
            ('lot_id', 'in', gr_fg.move_line_ids.lot_id.ids),
        ])
        self.assertTrue(
            landed,
            "Barang GR tidak sampai ke stok %s."
            % warehouse.lot_stock_id.complete_name)
        self.assertEqual(po_sap.sudo().state, 'in_progress')

    def test_03_foreign_station_document_is_not_writable(self):
        """Operator tidak boleh memvalidasi dokumen station lain.

        Dokumen Checker IN milik checker tidak boleh terbaca operator packing.
        Dengan rule picking berbasis lokasi, ini JUSTRU LOLOS -- dicatat di
        sini sebagai temuan, bukan sebagai perilaku yang benar.
        """
        check_in = self.env['stock.picking'].sudo().search([
            ('picking_type_id', '=', self.type_check_in.id),
            ('state', 'not in', ('done', 'cancel')),
        ], limit=1)
        if not check_in:
            self.skipTest("Tidak ada dokumen Checker IN terbuka di database ini.")

        visible_to_plant = bool(
            self._visible_pickings(self.u_plant, [('id', '=', check_in.id)]))
        if visible_to_plant:
            _logger.warning(
                "[audit] dokumen %s (Checker IN) masih terbaca oleh %s walau "
                "operation type-nya tidak dikonfigurasi -- rule stock.picking "
                "berbasis lokasi tidak menutup ini.",
                check_in.name, self.u_plant.login)
        self.assertTrue(
            visible_to_plant,
            "Kebocoran sudah tertutup -- perbarui test ini bila rule sudah "
            "diganti ke SCOPED_PICKING_DOMAIN.")

    # ------------------------------------------------------------------
    # helper khusus GR
    # ------------------------------------------------------------------
    def _prepare_gr_prod_lines(self, picking, setup):
        """Lengkapi baris GR produksi seperti yang diisi operator di scanner."""
        picking = picking.sudo()
        self.assertTrue(picking.move_line_ids,
                        "action_confirm() tidak membuat move line GR produksi.")
        for idx, line in enumerate(picking.move_line_ids, start=1):
            vals = {
                'quantity': self._cap_to_one_pallet(line),
                'picked': True,
                'production_line_id': setup['production_line'].id,
            }
            if not line.result_package_id:
                vals['result_package_id'] = self._package(
                    'UT-ACL-GR-%s-%s' % (picking.id, idx),
                    setup['company']).id
            line.write(vals)

    def _cap_to_one_pallet(self, line):
        """Satu baris scanner = satu pallet.

        Demand GR produksi adalah sisa PO (bisa ribuan kg), sedangkan
         menolak satu result package
        yang isinya lebih dari satu pallet. Di lapangan operator memang men-scan
        per pallet; test ini menirunya supaya yang diuji tetap hak aksesnya,
        bukan kapasitas pallet.
        """
        qty = line.quantity or line.move_id.product_uom_qty
        uom_pallet = line.product_id.uom_pallet_id
        if uom_pallet:
            one_pallet = uom_pallet._compute_quantity(
                1.0, line.product_uom_id, rounding_method='HALF-UP')
            if one_pallet > 0:
                qty = min(qty, one_pallet)
        return qty

    def _pick_all_lines(self, picking, need_result_package=False):
        picking = picking.sudo()
        if not picking.move_line_ids:
            picking.action_assign()
        self.assertTrue(
            picking.move_line_ids,
            "Dokumen %s tidak punya move line untuk diproses." % picking.name)
        for idx, line in enumerate(picking.move_line_ids, start=1):
            vals = {'picked': True}
            if not line.quantity:
                vals['quantity'] = line.move_id.product_uom_qty
            if need_result_package and not line.result_package_id:
                vals['result_package_id'] = (
                    line.package_id.id
                    or self._package('UT-ACL-%s-%s' % (picking.id, idx)).id)
            line.write(vals)


@tagged('post_install', '-at_install', 'sttl_access', 'sttl_access_gi')
class TestGiFlowPerUser(SttlFlowCommon):
    """Rantai outbound 1601: Pick -> Checker Out -> Loading -> Final -> Good Issue."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.u_pick = cls._user('sunardi')
        cls.u_out = cls._user('djunaedi')
        cls.u_gi = cls._user('kurnia.widiarta')

        PickingType = cls.env['stock.picking.type'].sudo()

        def _pt(seq_code, **extra):
            domain = [('company_id', '=', cls.company.id),
                      ('sequence_code', '=', seq_code), ('active', '=', True)]
            domain += [(k, '=', v) for k, v in extra.items()]
            ptype = PickingType.search(domain, limit=1)
            if not ptype:
                raise ValueError("Operation type %s (1601) tidak ditemukan." % seq_code)
            return ptype

        cls.type_pick = _pt('PICK', uu_only=True)
        cls.type_co = _pt('CO')
        cls.type_load = _pt('LOAD')
        cls.type_final = _pt('STO-SS-FINAL')
        cls.type_gi = _pt('GI-STO-SS')

        cls.warehouse = cls.type_pick.warehouse_id
        cls.loc_stock = cls.type_pick.default_location_src_id

        reference = cls.env['product.product'].sudo().search([
            ('uom_bag_id', '!=', False), ('uom_pallet_id', '!=', False),
        ], limit=1)
        if not reference:
            raise ValueError("Tidak ada produk dengan UoM Bag & Pallet sebagai acuan.")

        cls.product = cls.env['product.product'].sudo().create({
            'name': 'UT ACL Outbound',
            'default_code': 'UT-ACL-OUT',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'uom_id': reference.uom_id.id,
            'uom_bag_id': reference.uom_bag_id.id,
            'uom_pallet_id': reference.uom_pallet_id.id,
        })
        cls.lot = cls.env['stock.lot'].sudo().create({
            'name': 'UT-ACL-LOT-1',
            'product_id': cls.product.id,
            'company_id': cls.company.id,
        })
        cls.loc_bin = cls.env['stock.location'].sudo().create({
            'name': 'UT-ACL-OUT-BIN',
            'location_id': cls.loc_stock.id,
            'usage': 'internal',
            'company_id': cls.company.id,
        })
        cls.production_line = cls.env['production.line'].sudo().search(
            [('company_id', '=', cls.company.id)], limit=1)

        # Tepat satu pallet penuh: `stock.move.line._check_pallet_qty_limit()`
        # menolak `pallet_qty > 1` untuk operation type non-outgoing.
        cls.QTY = cls.product.uom_pallet_id._compute_quantity(
            1.0, cls.product.uom_id, rounding_method='HALF-UP')

    def _flow_users(self):
        return self.u_pick | self.u_out | self.u_gi

    # ------------------------------------------------------------------
    def test_01_menu_scope_per_station(self):
        """Menu Barcode/Operations tiap peran outbound sesuai konfigurasinya.

        `kurnia.widiarta` sengaja ikut diuji: dia yang mengungkap flag
        `check_operation` basi (lihat
        `TestSttlRecordRuleAudit.test_06b_stored_check_flags_are_stale_for_some_users`).
        Di sini flag-nya di-recompute dulu supaya yang diuji benar-benar
        domain rule-nya, bukan data basi.
        """
        for user in (self.u_pick, self.u_out, self.u_gi):
            with self.subTest(login=user.login):
                self._refresh_check_flags(user)
                self.assertEqual(
                    set(self._visible_picking_types(user).ids),
                    set(self._expected_picking_types(user).ids))

        self._assert_station_hidden(self.u_pick, self.type_co)
        self._assert_station_hidden(self.u_pick, self.type_load)
        self._assert_station_hidden(self.u_out, self.type_pick)
        self._assert_station_hidden(self.u_out, self.type_gi)

    def test_02_good_issue_is_configured_only_for_a_supervisor(self):
        """Temuan konfigurasi: hampir tak ada operator yang punya op type GI.

        Sesuai docs/business_flow.md 5.1, langkah Good Issue biasanya
        diselesaikan cron (`cron_auto_done_*`) setelah SAP menerbitkan nomor
        dokumennya, bukan lewat Barcode. Test ini mengunci kenyataan itu supaya
        tidak keliru dibaca sebagai konfigurasi yang kurang.
        """
        holders = self.env['res.users'].sudo().search([
            ('allowed_operation_types', 'in', self.type_gi.ids),
            ('active', '=', True),
        ])
        _logger.info("[audit] pemegang op type %s: %s",
                     self.type_gi.display_name, holders.mapped('login'))
        self.assertIn(self.u_gi, holders)

    def test_03_gi_chain_end_to_end_per_user(self):
        """Pick -> Checker Out -> Loading -> Final -> Good Issue, per user."""
        package = self._seed_pallet('UT-ACL-PLT-1')

        pick = self._make_picking(self.type_pick, self.QTY)
        self._assert_station_visible(self.u_pick, pick)
        self._assert_station_hidden(self.u_pick, self.type_co)
        pick.sudo().action_assign()
        self._process(pick, keep_package=True)
        self._validate_as(self.u_pick, pick)
        self._release_auto_dest(pick)

        co = self._make_picking(self.type_co, self.QTY, move_orig=pick.move_ids,
                                procure_method='make_to_order')
        self._assert_station_visible(self.u_out, co)
        co.sudo().action_assign()
        self._process(co, keep_package=True)
        self._validate_as(self.u_out, co)
        self._release_auto_dest(co)

        load = self._make_picking(self.type_load, self.QTY, move_orig=co.move_ids,
                                  procure_method='make_to_order')
        self._assert_station_visible(self.u_out, load)
        load.sudo().action_assign()
        self._process(load, keep_package=True)
        self._validate_as(self.u_out, load)
        self._release_auto_dest(load)

        final = self._make_picking(self.type_final, self.QTY, move_orig=load.move_ids,
                                   procure_method='make_to_order')
        self._assert_station_visible(self.u_out, final)
        final.sudo().action_assign()
        self._process(final)
        self._validate_as(self.u_out, final)
        self._release_auto_dest(final)

        # --- Good Issue: tujuan lokasi customer -----------------------------
        gi = self._make_picking(self.type_gi, self.QTY, move_orig=final.move_ids,
                                procure_method='make_to_order')
        self._assert_station_visible(self.u_gi, gi)
        gi.sudo().action_assign()
        self._process(gi)

        # `wms_inherit_stock_barcode.stock.picking.restrict_customer_location()`
        # menolak user non-manager untuk tujuan customer. Itu sebabnya langkah
        # ini di lapangan diselesaikan cron, bukan operator.
        if not self.u_gi.has_group('stock.group_stock_manager'):
            with self.assertRaises(ValidationError):
                self._env_as(self.u_gi)['stock.picking'].browse(gi.id).button_validate()
            env_cron = self._env_as(self.u_gi)(
                context=dict(self._env_as(self.u_gi).context, from_cron=True))
            env_cron['stock.picking'].browse(gi.id).button_validate()
            gi.invalidate_recordset()
            self.assertEqual(gi.state, 'done')
        else:
            self._validate_as(self.u_gi, gi)

        self.assertEqual(gi.location_dest_id.usage, 'customer')
        remaining = self.env['stock.quant'].sudo()._get_available_quantity(
            self.product, self.loc_bin, lot_id=self.lot, package_id=package)
        self.assertEqual(
            remaining, 0.0,
            "Stok pallet outbound seharusnya sudah keluar dari bin asal.")

    # ------------------------------------------------------------------
    # helper khusus GI
    # ------------------------------------------------------------------
    def _release_auto_dest(self, picking):
        """Lepas reservasi dokumen lanjutan yang dibuat push rule.

        Routing FINI ikut membuat dokumen berikutnya sendiri begitu satu
        langkah selesai. Test ini merangkai dokumennya secara eksplisit supaya
        tiap langkah bisa dipegang user yang benar, jadi reservasi otomatis itu
        harus dilepas -- kalau tidak, move buatan test tidak kebagian stok dan
        berhenti di state `waiting`.
        """
        auto_dest = picking.sudo().move_ids.move_dest_ids.filtered(
            lambda m: m.state not in ('done', 'cancel'))
        if auto_dest:
            auto_dest._do_unreserve()

    def _seed_pallet(self, name, qty=None):
        qty = self.QTY if qty is None else qty
        package = self.env['stock.package'].sudo().create({
            'name': name, 'company_id': self.company.id})
        self.env['stock.quant'].sudo()._update_available_quantity(
            self.product, self.loc_bin, qty, lot_id=self.lot, package_id=package)
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product.id),
            ('location_id', '=', self.loc_bin.id),
            ('package_id', '=', package.id)], limit=1)
        quant.write({
            'stock_type': 'UU',
            'production_line_id': self.production_line.id if self.production_line else False,
        })
        return package

    def _make_picking(self, picking_type, qty, move_orig=None,
                      procure_method='make_to_stock'):
        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
            'company_id': self.company.id,
        })
        move_vals = {
            'picking_id': picking.id,
            'product_id': self.product.id,
            'product_uom_qty': qty,
            'product_uom': self.product.uom_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': self.company.id,
            'procure_method': procure_method,
        }
        if move_orig:
            move_vals['move_orig_ids'] = [(6, 0, move_orig.ids)]
        self.env['stock.move'].sudo().create(move_vals)
        picking.action_confirm()
        return picking

    def _process(self, picking, keep_package=False):
        picking = picking.sudo()
        if not picking.move_line_ids:
            picking.action_assign()
        self.assertTrue(
            picking.move_line_ids,
            "Dokumen %s tidak punya move line untuk diproses." % picking.name)
        for line in picking.move_line_ids:
            vals = {'picked': True}
            if not line.quantity:
                vals['quantity'] = line.move_id.product_uom_qty
            if keep_package and line.package_id and not line.result_package_id:
                vals['result_package_id'] = line.package_id.id
            line.write(vals)


@tagged('post_install', '-at_install', 'sttl_access', 'sttl_access_matrix')
class TestEveryOperationTypePerUser(SttlFlowCommon):
    """Matriks penuh: SETIAP operation type aktif dijalankan user-nya sendiri.

    Dua kelas sebelumnya hanya membuktikan satu rantai GR dan satu rantai GI.
    Kelas ini menjawab pertanyaan yang lebih besar -- apakah **semua** station
    masih bisa dikerjakan kalau `(1, '=', 1)` dilepas -- dengan cara membuat
    dokumen nyata untuk tiap operation type aktif di 1601 dan 1481, lalu
    memvalidasinya sebagai user yang memang dikonfigurasi untuk station itu.

    Operation type yang belum punya user sama sekali hanya dicatat, tidak
    digagalkan: itu celah master data, bukan soal record rule.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        warehouses = cls.env['stock.warehouse'].sudo().search(
            [('name', 'like', 'FINI')])
        cls.companies = warehouses.company_id
        if not cls.companies:
            raise ValueError("Warehouse FINI tidak ada di database ini.")

        cls.all_types = cls.env['stock.picking.type'].sudo().search([
            ('active', '=', True),
            ('company_id', 'in', cls.companies.ids),
            ('code', 'in', ('incoming', 'outgoing', 'internal')),
        ], order='company_id, sequence_code, id')

        # Satu produk uji dipakai bersama; UoM Bag/Pallet diambil dari produk
        # nyata supaya konversi pallet_qty ikut realistis.
        reference = cls.env['product.product'].sudo().search([
            ('uom_bag_id', '!=', False), ('uom_pallet_id', '!=', False),
        ], limit=1)
        if not reference:
            raise ValueError("Tidak ada produk dengan UoM Bag & Pallet sebagai acuan.")
        cls.product = cls.env['product.product'].sudo().create({
            'name': 'UT ACL Matrix',
            'default_code': 'UT-ACL-MTX',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'uom_id': reference.uom_id.id,
            'uom_bag_id': reference.uom_bag_id.id,
            'uom_pallet_id': reference.uom_pallet_id.id,
        })
        # Operation type yang sama sekali tidak mengelola lot
        # (`use_create_lots` dan `use_existing_lots` dua-duanya False, mis.
        # Receipts STO BULK-IN) tidak bisa memakai produk ber-tracking.
        cls.product_untracked = cls.product.sudo().copy({
            'name': 'UT ACL Matrix (no lot)',
            'default_code': 'UT-ACL-MTX-NL',
            'tracking': 'none',
        })
        cls.pallet_qty = cls.product.uom_pallet_id._compute_quantity(
            1.0, cls.product.uom_id, rounding_method='HALF-UP')

        cls.lot_by_company = {}
        cls.line_by_company = {}
        for company in cls.companies:
            cls.lot_by_company[company.id] = cls.env['stock.lot'].sudo().create({
                'name': 'UT-ACL-MTX-%s' % company.id,
                'product_id': cls.product.id,
                'company_id': company.id,
            })
            cls.line_by_company[company.id] = cls.env['production.line'].sudo().search(
                [('company_id', '=', company.id)], limit=1)

        cls.seq = 0

    # ------------------------------------------------------------------
    # pemilihan user
    # ------------------------------------------------------------------
    def _flow_users(self):
        return self._configured_users_all()

    def _configured_users_all(self):
        users = self.env['res.users'].sudo().browse([])
        for ptype in self.all_types:
            users |= self._configured_users(ptype)
        return users

    def _configured_users(self, ptype):
        return self.env['res.users'].sudo().search([
            ('active', '=', True), ('share', '=', False),
            ('allowed_operation_types', 'in', ptype.ids),
        ], order='login')

    def _operator_for(self, ptype):
        """User yang dipakai menjalankan station ini.

        Dipilih yang paling sedikit operation type-nya -- itu operator lapangan
        sungguhan, bukan supervisor yang memegang hampir semua station. Justru
        user sempit itulah yang paling mudah terjegal record rule.
        """
        candidates = self._configured_users(ptype).filtered(
            lambda u: ptype.company_id.id in u.company_ids.ids)
        if not candidates:
            return self.env['res.users'].sudo().browse([])
        return sorted(
            candidates, key=lambda u: (len(u.allowed_operation_types), u.login))[0]

    # ------------------------------------------------------------------
    # pembuatan dokumen
    # ------------------------------------------------------------------
    def _product_for(self, ptype):
        if ptype.use_create_lots or ptype.use_existing_lots:
            return self.product
        return self.product_untracked

    def _real_location(self, location, warehouse):
        """Lokasi view tidak bisa jadi src/dest dokumen; pakai lokasi stok."""
        if not location or location.usage == 'view':
            return warehouse.lot_stock_id
        return location

    def _seed(self, location, company, product):
        self.seq += 1
        package = self.env['stock.package'].sudo().create({
            'name': 'UT-ACL-MTX-PKG-%s' % self.seq,
            'company_id': company.id,
        })
        lot = self.lot_by_company[company.id] if product.tracking != 'none' else False
        self.env['stock.quant'].sudo()._update_available_quantity(
            product, location, self.pallet_qty, lot_id=lot, package_id=package)
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
            ('package_id', '=', package.id)], limit=1)
        quant.write({
            'stock_type': 'UU',
            'production_line_id': self.line_by_company[company.id].id or False,
        })
        return package

    def _build_document(self, ptype):
        company = ptype.company_id
        warehouse = ptype.warehouse_id
        product = self._product_for(ptype)
        src = self._real_location(ptype.default_location_src_id, warehouse)
        dst = self._real_location(ptype.default_location_dest_id, warehouse)

        if src.usage in ('internal', 'transit'):
            self._seed(src, company, product)

        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': ptype.id,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'company_id': company.id,
        })
        self.env['stock.move'].sudo().create({
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_qty': self.pallet_qty,
            'product_uom': product.uom_id.id,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'company_id': company.id,
        })
        picking.action_confirm()
        picking.action_assign()
        self._fill_lines(picking, company, product)
        return picking

    def _fill_lines(self, picking, company, product):
        picking = picking.sudo()
        ptype = picking.picking_type_id
        if not picking.move_line_ids:
            # Lokasi asal virtual (Vendors/Production) tidak perlu reservasi;
            # barisnya dibuat manual, seperti yang dikirim client Barcode.
            picking.write({'move_line_ids': [(0, 0, {
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'lot_id': (self.lot_by_company[company.id].id
                           if product.tracking != 'none' and ptype.use_existing_lots
                           else False),
                'lot_name': (self.lot_by_company[company.id].name
                             if product.tracking != 'none' and not ptype.use_existing_lots
                             else False),
                'quantity': self.pallet_qty,
                'picked': True,
                'state': 'assigned',
            })]})
        lot = self.lot_by_company[company.id]
        for line in picking.move_line_ids:
            vals = {'picked': True}
            if not line.quantity:
                vals['quantity'] = line.move_id.product_uom_qty
            # Baris hasil reservasi dari lokasi virtual (Vendors/Production)
            # lahir tanpa lot; core menolak validate kalau operation type-nya
            # mengelola lot.
            if product.tracking != 'none' and not line.lot_id and not line.lot_name:
                if ptype.use_existing_lots:
                    vals['lot_id'] = lot.id
                elif ptype.use_create_lots:
                    vals['lot_name'] = lot.name
            if ptype.mandatory_destination and not line.result_package_id:
                self.seq += 1
                vals['result_package_id'] = (
                    line.package_id.id
                    or self.env['stock.package'].sudo().create({
                        'name': 'UT-ACL-MTX-DEST-%s' % self.seq,
                        'company_id': company.id,
                    }).id)
            if ptype.production_only and not line.production_line_id:
                vals['production_line_id'] = self.line_by_company[company.id].id
            line.write(vals)

    def _run_station(self, ptype, operator):
        """Jalankan satu dokumen station ini sampai `done` sebagai `operator`."""
        company = ptype.company_id
        picking = self._build_document(ptype)

        self.assertTrue(
            self._visible_pickings(operator, [('id', '=', picking.id)], company),
            "Dokumen %s tidak terbaca oleh %s." % (picking.name, operator.login))

        context = {}
        if ptype.production_only:
            context['pallet_ke_confirmed'] = True

        if picking.location_dest_id.usage == 'customer' \
                and not operator.has_group('stock.group_stock_manager'):
            # `restrict_customer_location()` memang memblokir operator biasa;
            # langkah Good Issue diselesaikan cron. Dua-duanya dibuktikan.
            env = self._env_as(operator, company)
            with self.assertRaises(ValidationError):
                env['stock.picking'].browse(picking.id).button_validate()
            context['from_cron'] = True

        self._validate_as(operator, picking, context=context or None,
                          company=company)
        return picking

    # ------------------------------------------------------------------
    def test_01_every_configured_user_sees_only_their_own_stations(self):
        """Menu Barcode/Operations tiap user = persis allowed_operation_types.

        Anggota `group_warehouse_manager` dikecualikan: rule versi manager
        (`[(1,'=',1)]`) memang membuka semuanya, dan rule antar-grup di-OR,
        jadi pembatasan base group tidak berlaku untuk mereka. Itu desain,
        bukan kebocoran -- tapi perlu jelas siapa saja yang kena.
        """
        manager_group = self.env.ref(
            'sttl_warehouse_access_control.group_warehouse_manager')
        users = self._configured_users_all()
        self.assertTrue(users)
        managers = users.filtered(lambda u: manager_group in u.all_group_ids)
        if managers:
            _logger.warning(
                "[audit] %d user berkonfigurasi juga anggota Warehouse Manager, "
                "jadi tetap melihat SEMUA operation type: %s",
                len(managers), managers.mapped('login'))
        for user in (users - managers).sorted('login'):
            for company in self.companies:
                if company.id not in user.company_ids.ids:
                    continue
                with self.subTest(login=user.login, company=company.name):
                    self.assertEqual(
                        set(self._visible_picking_types(user, company).ids),
                        set(self._expected_picking_types(user, company).ids))

    def test_02_operation_types_without_any_user(self):
        """Laporan celah konfigurasi -- bukan soal record rule."""
        orphans = self.all_types.filtered(lambda t: not self._configured_users(t))
        if orphans:
            _logger.warning(
                "[audit] %d dari %d operation type aktif belum punya user sama "
                "sekali, jadi tidak akan pernah muncul di Barcode/Operations "
                "siapa pun: %s",
                len(orphans), len(self.all_types),
                ['%s / %s (id %s)' % (t.company_id.name, t.display_name, t.id)
                 for t in orphans])
        self.assertTrue(
            len(orphans) < len(self.all_types),
            "Tidak ada satu pun operation type yang punya user.")

    def test_03_every_station_can_be_processed_by_its_own_user(self):
        """Inti pertanyaannya: tiap station bisa diselesaikan user-nya sendiri.

        Satu dokumen nyata per operation type, dibuat lalu di-`button_validate`
        sebagai user yang dikonfigurasi untuk station itu, dengan record rule
        versi ketat. Tiap station dibungkus savepoint sendiri supaya satu
        kegagalan tidak menjatuhkan sisanya -- satu kali jalan langsung
        menghasilkan matriks lengkapnya.
        """
        rows = []
        failures = []
        for ptype in self.all_types:
            operator = self._operator_for(ptype)
            label = '%s / %s (id %s)' % (
                ptype.company_id.name, ptype.display_name, ptype.id)

            if not operator:
                rows.append((label, '-', 'NO USER'))
                continue
            if ptype.production_only:
                # Dijalankan lewat jalur aslinya (QR Scanner GR FG) di
                # TestGrFlowPerUser; membuat dokumennya langsung di sini akan
                # melewati production.order.sap dan tidak mewakili apa pun.
                rows.append((label, operator.login, 'SKIP (lewat QR GR FG)'))
                continue

            savepoint = self.cr.savepoint(flush=False)
            try:
                self._run_station(ptype, operator)
            except Exception as exc:
                savepoint.rollback()
                rows.append((label, operator.login,
                             'FAIL %s: %s' % (type(exc).__name__, exc)))
                failures.append((label, operator.login, exc))
            else:
                savepoint.close()
                rows.append((label, operator.login, 'OK'))

        _logger.info(
            "[matrix] hasil per operation type:\n%s",
            '\n'.join('  %-52s %-24s %s' % row for row in rows))

        self.assertFalse(
            failures,
            "%d station tidak bisa diselesaikan user-nya sendiri:\n%s"
            % (len(failures),
               '\n'.join('  %s (user %s): %s' % (lbl, login, exc)
                         for lbl, login, exc in failures)))


@tagged('post_install', '-at_install', 'sttl_access', 'sttl_access_deployed')
class TestDeployedStateAsIs(SttlAccessCommon):
    """Verifikasi APA ADANYA: rule dan data persis seperti yang ada di DB.

    Kelas alur lain sengaja memasang domain ketat dan me-recompute flag
    `check_*` di `setUp`, supaya yang diuji murni alur kerjanya. Kelas ini
    justru tidak menyentuh apa pun: ia memeriksa keadaan database saat ini,
    sehingga bisa menjawab "apakah konfigurasi yang sedang terpasang sudah
    benar", bukan "apakah bisa benar".
    """

    def test_01_deployed_domains_are_the_strict_ones(self):
        """Domain terpasang harus persis bentuk ketat yang dipakai test alur."""
        for rule, expected in ((self.rule_pt, STRICT_PT_DOMAIN),
                               (self.rule_picking, STRICT_PICKING_DOMAIN)):
            with self.subTest(rule=rule.name):
                self.assertTrue(rule.sudo().active)
                self.assertEqual(
                    ''.join((rule.sudo().domain_force or '').split()),
                    ''.join(expected.split()),
                    "Domain %s di database bukan bentuk ketat yang diuji "
                    "kelas-kelas alur." % rule.name)

    def test_02_live_menu_matches_each_user_configuration(self):
        """Untuk SETIAP user berkonfigurasi: isi menu = allowed_operation_types.

        Dijalankan tanpa menyentuh rule maupun flag `check_*`, jadi hasilnya
        adalah apa yang benar-benar dilihat operator kalau login sekarang.
        Anggota `group_warehouse_manager` dikecualikan -- rule versi manager
        (`[(1,'=',1)]`) memang membuka semuanya dan rule antar-grup di-OR.
        """
        manager_group = self.env.ref(
            'sttl_warehouse_access_control.group_warehouse_manager')
        users = self.env['res.users'].sudo().search([
            ('active', '=', True), ('share', '=', False),
            ('allowed_operation_types', '!=', False),
        ], order='login')
        self.assertTrue(users, "Belum ada user dengan allowed_operation_types.")

        companies = self.env['stock.warehouse'].sudo().search(
            [('name', 'like', 'FINI')]).company_id
        managers = users.filtered(lambda u: manager_group in u.all_group_ids)
        if managers:
            _logger.warning(
                "[audit] %d user berkonfigurasi juga anggota Warehouse Manager "
                "sehingga tetap melihat SEMUA operation type: %s",
                len(managers), managers.mapped('login'))

        offenders = []
        for user in users - managers:
            for company in companies:
                if company.id not in user.company_ids.ids:
                    continue
                visible = self._visible_picking_types(user, company)
                expected = self._expected_picking_types(user, company)
                extra = visible - expected
                missing = expected - visible
                if extra or missing:
                    offenders.append((
                        user.login, company.name,
                        extra.mapped('display_name'),
                        missing.mapped('display_name'),
                        user.check_operation,
                    ))

        if offenders:
            _logger.error(
                "[audit] %d kombinasi user/company menu-nya TIDAK sesuai "
                "konfigurasi:\n%s",
                len(offenders),
                '\n'.join(
                    '  %-32s %-26s check_operation=%s\n'
                    '      kelebihan: %s\n      kekurangan: %s'
                    % (login, comp, flag, extra or '-', missing or '-')
                    for login, comp, extra, missing, flag in offenders))

        self.assertFalse(
            offenders,
            "%d kombinasi user/company melihat operation type di luar "
            "konfigurasinya. Penyebab tersering: flag `check_operation` "
            "tersimpan masih False padahal allowed_operation_types terisi -- "
            "recompute dengan `env['res.users'].sudo().with_context("
            "active_test=False).search([]).modified(['allowed_warehouse_ids', "
            "'allowed_location_ids', 'allowed_operation_types'])`.\n%s"
            % (len(offenders),
               '\n'.join('  %s @ %s: kelebihan %s' % (o[0], o[1], o[2])
                          for o in offenders)))

    def test_03_no_user_has_stale_check_flags(self):
        """Flag `check_*` tersimpan harus konsisten dengan relasinya."""
        users = self.env['res.users'].sudo().with_context(
            active_test=False).search([('share', '=', False)])
        stale = users.filtered(
            lambda u: (bool(u.allowed_operation_types) != u.check_operation
                       or bool(u.allowed_location_ids) != u.check_location
                       or bool(u.allowed_warehouse_ids) != u.check_warehouse))
        self.assertFalse(
            stale,
            "Flag `check_*` basi untuk %d user: %s. Selama masih basi, cabang "
            "escape hatch `bool_x = check_x` cocok dengan SEMUA record dan "
            "rule terbuka penuh untuk mereka."
            % (len(stale), stale.mapped('login')))
