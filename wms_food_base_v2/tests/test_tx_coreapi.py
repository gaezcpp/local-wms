import base64

from Crypto.Cipher import AES
from Crypto.Util import Counter

from odoo.tests.common import TransactionCase

from ..controllers.tx_coreapi import (
    _build_plain_response,
    _build_select_datablock,
    _decrypt_token,
    _encrypt_token,
    _query_type,
)


class TestTxCoreApiResponse(TransactionCase):
    def test_decrypt_token_uses_sap_compatible_aes_ctr(self):
        token = "0123456789abcdef0123456789abcdef"
        nonce = b"12345678"
        counter = Counter.new(
            64, prefix=nonce, initial_value=0, little_endian=False,
        )
        cipher = AES.new(token.encode(), AES.MODE_CTR, counter=counter)
        encrypted = base64.b64encode(
            nonce + cipher.encrypt(b'{"sql":"SELECT 1"}'),
        ).decode()

        self.assertEqual(
            _decrypt_token(encrypted, token), '{"sql":"SELECT 1"}',
        )

    def test_response_is_sap_compatible_and_encrypted(self):
        class Cursor:
            description = [("id",), ("name",)]

        plaintext = _build_plain_response(
            ok=True,
            message="OK",
            query_type="select",
            manifest="COUNT=2",
            data_block=_build_select_datablock(
                Cursor(), [(1, "FOOD"), (2, None)],
            ),
        )
        token = "0123456789abcdef0123456789abcdef"
        self.assertEqual(
            _decrypt_token(_encrypt_token(plaintext, token), token),
            "STATUS: TRUE[//]MESSAGE: OK[//]TYPE: select[//]"
            "MANIFEST: COUNT=2[//]HEADER:id[|]name[//]1[|]FOOD[//]2[|]",
        )

    def test_query_type_matches_legacy_first_word_contract(self):
        self.assertEqual(_query_type("  SELECT 1"), "select")
        self.assertEqual(_query_type("UPDATE product SET active = true"), "update")
