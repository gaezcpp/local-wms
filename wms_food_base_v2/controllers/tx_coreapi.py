import base64
import json
import logging
import struct
import time
import uuid

from Crypto.Cipher import AES
from Crypto.Util import Counter

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

SEP_ROW = "[//]"
SEP_DATA = "[|]"


class AESCTR:
    def __init__(self, key):
        self.key = key.encode("utf-8") if isinstance(key, str) else key
        if len(self.key) not in (16, 24, 32):
            message = "TX token must be 16, 24, or 32 bytes."
            raise ValueError(message)

    def _generate_nonce(self):
        current_time = time.time()
        seconds = int(current_time) & 0xFFFFFFFF
        fraction = int((current_time - int(current_time)) * 0x100000000)
        return struct.pack(">II", seconds, fraction & 0xFFFFFFFF)

    def encrypt_raw(self, text):
        if not text:
            return b""
        nonce = self._generate_nonce()
        counter = Counter.new(
            64, prefix=nonce, initial_value=0, little_endian=False,
        )
        cipher = AES.new(self.key, AES.MODE_CTR, counter=counter)
        return nonce + cipher.encrypt(text.encode("utf-8"))

    def decrypt_raw(self, raw_data):
        if not raw_data:
            return ""
        nonce = raw_data[:8]
        counter = Counter.new(
            64, prefix=nonce, initial_value=0, little_endian=False,
        )
        cipher = AES.new(self.key, AES.MODE_CTR, counter=counter)
        return cipher.decrypt(raw_data[8:]).decode("utf-8")


def _encrypt_token(plaintext, token):
    return base64.b64encode(AESCTR(token).encrypt_raw(plaintext)).decode("utf-8")


def _decrypt_token(ciphertext, token):
    return AESCTR(token).decrypt_raw(base64.b64decode(ciphertext))


def _escape_message(message):
    if message is None:
        return ""
    return str(message).replace("\\", "\\\\").replace('"', '\\"')


def _build_plain_response(*, ok, message, query_type, manifest="", data_block=""):
    parts = [
        f"STATUS: {'TRUE' if ok else 'ERROR'}",
        f"MESSAGE: {message}" if ok else f'MESSAGE:"{_escape_message(message)}"',
        f"TYPE: {query_type}",
    ]
    if manifest:
        parts.append(f"MANIFEST: {manifest}")
    if data_block:
        parts.append(data_block)
    return SEP_ROW.join(parts)


def _build_select_datablock(cursor, rows):
    if not rows:
        return "HEADER:EMPTY"
    columns = [description[0] for description in (cursor.description or [])]
    if not columns:
        columns = [f"col{index + 1}" for index in range(len(rows[0]))]
    header = SEP_DATA.join(columns)
    body = SEP_ROW.join(
        SEP_DATA.join("" if value is None else str(value) for value in row)
        for row in rows
    )
    return f"HEADER:{header}{SEP_ROW}{body}"


def _query_type(sql):
    parts = str(sql or "").strip().split(None, 1)
    return parts[0].lower() if parts else "unknown"


class TxCoreApi(http.Controller):
    @http.route("/tx/coreapi", type="http", auth="none", methods=["POST"], csrf=False)
    def coreapi(self, **kwargs):
        start_time = time.time()
        request_id = uuid.uuid4().hex[:8]
        remote_addr = request.httprequest.remote_addr
        encrypted_input = request.httprequest.data.decode("utf-8", errors="ignore")
        token = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("wms_food_tx.token")
            or ""
        )

        _logger.info(
            "[TX_COREAPI][IN] req=%s ip=%s len=%s",
            request_id,
            remote_addr,
            len(encrypted_input) if encrypted_input else 0,
        )

        def reply_encrypted(plaintext, http_status=200):
            try:
                return Response(
                    _encrypt_token(plaintext, token), status=http_status,
                )
            except Exception as error:  # ruff: ignore[blind-except]
                _logger.error(
                    "[TX_COREAPI][ENCRYPT_FAILED] req=%s error=%s",
                    request_id,
                    error,
                )
                return Response("ENCRYPT_FAILED", status=500)

        try:
            plaintext = _decrypt_token(encrypted_input, token)
            _logger.info(
                "[TX_COREAPI][DECRYPT_OK] req=%s payload_len=%s",
                request_id,
                len(plaintext),
            )
        except Exception as error:  # ruff: ignore[blind-except]
            _logger.error(
                "[TX_COREAPI][DECRYPT_FAILED] req=%s ip=%s error=%s",
                request_id,
                remote_addr,
                error,
            )
            return Response("DECRYPT_FAILED", status=400)

        try:
            payload = json.loads(plaintext)
        except Exception:  # ruff: ignore[blind-except]
            _logger.warning(
                "[TX_COREAPI][BAD_JSON] req=%s plaintext=%r",
                request_id,
                plaintext[:200],
            )
            return Response("BAD_JSON", status=400)

        sql = payload.get("sql")
        if not sql:
            return Response("NO_SQL", status=400)

        query_type = _query_type(sql)
        cursor = request.env.cr
        try:  # ruff: ignore[too-many-statements-in-try-clause]
            _logger.info(
                "[TX_COREAPI][SQL] req=%s type=%s sql=%s",
                request_id,
                query_type,
                sql,
            )
            cursor.execute(sql)
            if query_type == "select":
                rows = cursor.fetchall()
                response_plain = _build_plain_response(
                    ok=True,
                    message="OK",
                    query_type="select",
                    manifest=f"COUNT={len(rows)}",
                    data_block=_build_select_datablock(cursor, rows),
                )
            else:
                affected = cursor.rowcount if cursor.rowcount is not None else 0
                response_plain = _build_plain_response(
                    ok=True,
                    message="OK",
                    query_type=query_type,
                    manifest=f"AFFECTED={affected}",
                )
        except Exception as error:  # ruff: ignore[blind-except]
            message = getattr(error, "pgerror", None) or str(error) or repr(error)
            _logger.warning(
                "[TX_COREAPI][SQL_ERROR] req=%s type=%s message=%s",
                request_id,
                query_type,
                message,
            )
            response_plain = _build_plain_response(
                ok=False,
                message=message,
                query_type=query_type,
            )
            return reply_encrypted(response_plain)

        _logger.info(
            "[TX_COREAPI][OUT] req=%s type=%s time_ms=%s",
            request_id,
            query_type,
            int((time.time() - start_time) * 1000),
        )
        return reply_encrypted(response_plain)
