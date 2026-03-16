# -*- coding: utf-8 -*-
import base64
import json
import logging
import struct
import uuid
import time

from Crypto.Cipher import AES
from Crypto.Util import Counter

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger("sap.coreapi")

SEP_ROW = "[//]"
SEP_DATA = "[|]"


# =====================================================
# CRYPTO HELPERS (AES-CTR legacy)
# =====================================================

class AESCTR:
    def __init__(self, key):
        self.key = key.encode("utf-8") if isinstance(key, str) else key
        if len(self.key) not in (16, 24, 32):
            raise ValueError("Panjang kunci harus 16, 24, atau 32 byte (sesuai legacy).")

    def _generate_nonce(self) -> bytes:
        t = time.time()
        seconds = int(t) & 0xFFFFFFFF
        fraction = int((t - int(t)) * 0x100000000) & 0xFFFFFFFF
        return struct.pack(">II", seconds, fraction)

    def encrypt_raw(self, text: str) -> bytes:
        if not text:
            return b""
        nonce = self._generate_nonce()
        ctr = Counter.new(64, prefix=nonce, initial_value=0, little_endian=False)
        cipher = AES.new(self.key, AES.MODE_CTR, counter=ctr)
        ciphertext = cipher.encrypt(text.encode("utf-8"))
        return nonce + ciphertext

    def decrypt_raw(self, raw_data: bytes) -> str:
        if not raw_data:
            return ""
        nonce = raw_data[:8]
        ciphertext = raw_data[8:]
        ctr = Counter.new(64, prefix=nonce, initial_value=0, little_endian=False)
        cipher = AES.new(self.key, AES.MODE_CTR, counter=ctr)
        return cipher.decrypt(ciphertext).decode("utf-8")


def encrypt_token(plaintext: str, token: str) -> str:
    aes = AESCTR(token)
    raw = aes.encrypt_raw(plaintext)
    return base64.b64encode(raw).decode("utf-8")


def decrypt_token(ciphertext_b64: str, token: str) -> str:
    raw = base64.b64decode(ciphertext_b64)
    aes = AESCTR(token)
    return aes.decrypt_raw(raw)


# =====================================================
# RESPONSE HELPERS
# =====================================================

def _escape_message(msg: str) -> str:
    # Format legacy: MESSAGE:"..."
    if msg is None:
        return ""
    msg = str(msg)
    return msg.replace("\\", "\\\\").replace('"', '\\"')


def _build_plain_response(*, ok: bool, message: str, qtype: str, manifest: str = "", data_block: str = "") -> str:
    status = "TRUE" if ok else "ERROR"
    parts = [
        f"STATUS: {status}",
        (f'MESSAGE:"{_escape_message(message)}"' if not ok else f"MESSAGE: {message}"),
        f"TYPE: {qtype}",
    ]
    if manifest:
        parts.append(f"MANIFEST: {manifest}")
    if data_block:
        parts.append(data_block)
    return SEP_ROW.join(parts)


def _build_select_datablock(cr, rows) -> str:
    if not rows:
        return "HEADER:EMPTY"

    colnames = [d[0] for d in (cr.description or [])]
    if not colnames:
        colnames = [f"col{i+1}" for i in range(len(rows[0]))]

    header = SEP_DATA.join(colnames)
    body = SEP_ROW.join(
        SEP_DATA.join("" if v is None else str(v) for v in row)
        for row in rows
    )
    return f"HEADER:{header}{SEP_ROW}{body}"


def _infer_qtype(sql: str) -> str:
    if not sql:
        return "unknown"
    first = str(sql).strip().split(None, 1)
    return (first[0].lower() if first else "unknown")


# =====================================================
# CONTROLLER
# =====================================================

class SapCoreApi(http.Controller):

    @http.route("/sap/coreapi", type="http", auth="none", methods=["POST"], csrf=False)
    def coreapi(self, **kw):
        start_ts = time.time()
        request_id = uuid.uuid4().hex[:8]
        remote_addr = request.httprequest.remote_addr
        icp = request.env["ir.config_parameter"].sudo()

        encrypted_in = request.httprequest.data.decode("utf-8", errors="ignore")
        token = icp.get_param("sap_coreapi.token") or ""

        _logger.info(
            "[COREAPI][IN] req=%s ip=%s len=%s",
            request_id,
            remote_addr,
            len(encrypted_in) if encrypted_in else 0,
        )

        def _reply_encrypted(plain: str, http_status: int = 200):
            try:
                encrypted_out = encrypt_token(plain, token)
                return Response(encrypted_out, status=http_status)
            except Exception as e:
                _logger.error("[COREAPI][ENCRYPT_FAILED] req=%s err=%s", request_id, str(e))
                return Response("ENCRYPT_FAILED", status=500)

        # -------------------------
        # 1) DECRYPT
        # -------------------------
        try:
            plaintext = decrypt_token(encrypted_in, token)
            _logger.info("[COREAPI][DECRYPT_OK] req=%s payload_len=%s", request_id, len(plaintext))
        except Exception as e:
            _logger.error("[COREAPI][DECRYPT_FAILED] req=%s ip=%s err=%s", request_id, remote_addr, str(e))
            return Response("DECRYPT_FAILED", status=400)

        # -------------------------
        # 2) PARSE JSON
        # -------------------------
        try:
            payload = json.loads(plaintext)
        except Exception:
            _logger.warning("[COREAPI][BAD_JSON] req=%s plaintext=%r", request_id, plaintext[:200])
            return Response("BAD_JSON", status=400)

        sql = payload.get("sql")
        if not sql:
            return Response("NO_SQL", status=400)

        qtype = _infer_qtype(sql)

        # -------------------------
        # 3) EXECUTE SQL (SELECT / INSERT / UPDATE / DELETE / DDL)
        # -------------------------
        cr = request.env.cr
        try:
            _logger.info("[COREAPI][SQL] req=%s type=%s sql=%s", request_id, qtype, sql)
            cr.execute(sql)

            if qtype == "select":
                rows = cr.fetchall()
                data_block = _build_select_datablock(cr, rows)
                response_plain = _build_plain_response(
                    ok=True,
                    message="OK",
                    qtype="select",
                    manifest=f"COUNT={len(rows)}",
                    data_block=data_block,
                )
            else:
                affected = cr.rowcount if cr.rowcount is not None else 0
                response_plain = _build_plain_response(
                    ok=True,
                    message="OK",
                    qtype=qtype,
                    manifest=f"AFFECTED={affected}",
                )

                # Optional (kalau mau pasti commit untuk non-select):
                # request.env.cr.commit()

        except Exception as e:
            msg = getattr(e, "pgerror", None) or str(e) or repr(e)
            _logger.warning("[COREAPI][SQL_ERROR] req=%s type=%s msg=%s", request_id, qtype, msg)

            response_plain = _build_plain_response(
                ok=False,
                message=msg,
                qtype=qtype,
            )
            # legacy-friendly: HTTP 200 tapi STATUS: ERROR
            return _reply_encrypted(response_plain, http_status=200)

        duration = int((time.time() - start_ts) * 1000)
        _logger.info(
            "[COREAPI][OUT] req=%s type=%s time_ms=%s",
            request_id,
            qtype,
            duration,
        )

        return _reply_encrypted(response_plain, http_status=200)
