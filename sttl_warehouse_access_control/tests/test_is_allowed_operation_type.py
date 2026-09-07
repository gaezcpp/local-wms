from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'sttl_allowed_operation_type')
class TestIsAllowedOperationType(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.operation_types = cls.env['stock.picking.type'].sudo().search([], limit=2)
        if len(cls.operation_types) < 2:
            message = 'Need at least two operation types for this test.'
            raise ValueError(message)

        cls.allowed_type = cls.operation_types[0]
        cls.disallowed_type = cls.operation_types[1]
        cls.base_group = cls.env.ref('base.group_user')
        cls.stock_manager_group = cls.env.ref('stock.group_stock_manager')
        cls.sttl_manager_group = cls.env.ref(
            'sttl_warehouse_access_control.group_warehouse_manager')

    def _make_user(self, login, groups):
        return self.env['res.users'].sudo().create({
            'name': login,
            'login': login,
            'email': '%s@example.test' % login,
            'group_ids': [Command.set([group.id for group in groups])],
            'allowed_operation_types': [Command.set([self.allowed_type.id])],
        })

    def _search_domain(self, user, operator, value):
        return self.env(user=user)['stock.picking.type']._search_is_allowed_operation_type(
            operator, value)

    def test_regular_user_search_true_is_limited_to_allowed_types(self):
        user = self._make_user('sttl_regular_user', [self.base_group])

        self.assertEqual(
            self._search_domain(user, '=', True),
            [('id', 'in', [self.allowed_type.id])],
        )

    def test_regular_user_search_false_excludes_allowed_types(self):
        user = self._make_user('sttl_regular_user_false', [self.base_group])

        domain = self._search_domain(user, '=', False)

        self.assertEqual(domain, [('id', 'not in', [self.allowed_type.id])])
        self.assertIn(self.disallowed_type, self.operation_types.filtered_domain(domain))

    def test_sttl_warehouse_manager_bypasses_allowed_filter(self):
        user = self._make_user(
            'sttl_warehouse_manager',
            [self.base_group, self.sttl_manager_group],
        )

        self.assertEqual(self._search_domain(user, '=', True), [])
        self.assertEqual(self._search_domain(user, '=', False), [])

    def test_stock_manager_does_not_bypass_sttl_filter(self):
        user = self._make_user(
            'sttl_stock_manager_only',
            [self.base_group, self.stock_manager_group],
        )

        self.assertEqual(
            self._search_domain(user, '=', True),
            [('id', 'in', [self.allowed_type.id])],
        )
        self.assertEqual(
            self._search_domain(user, '=', False),
            [('id', 'not in', [self.allowed_type.id])],
        )
