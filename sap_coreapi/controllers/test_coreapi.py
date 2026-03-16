import base64
import json
import struct
import time
import requests
import hashlib
from Crypto.Cipher import AES

# ======================
# Config
# ======================
ODOO_URL = "https://wms-dev.cpp.co.id/coreapi"
ODOO_DB = "taging_pm"

# TOKEN OPAQUE STRING (SAMA PERSIS DENGAN SYSTEM PARAMETER)
TOKEN = "ZyQqMKclxAA/c4YQ76DiDQYpnR/7NX5v5LkkR0OJDBPzWAWgsm=="


# ======================
# Crypto helpers (HARUS IDENTIK DENGAN SERVER)
# ======================
def _u32(x: int) -> int:
    return x & 0xFFFFFFFF


def normalize_key(token: str) -> bytes:
    token = token.strip()   # ⬅️ WAJIB
    return hashlib.sha256(token.encode("utf-8")).digest()



def new_nonce_and_counter():
    t = time.time()
    sec = int(t)
    frac = int((t - sec) * (2**32)) & 0xFFFFFFFF
    counter = [_u32(sec), _u32(frac), 0, 0]
    nonce = struct.pack(">II", counter[0], counter[1])
    return nonce, counter


def set_counter_from_nonce(nonce8: bytes):
    a, b = struct.unpack(">II", nonce8)
    return [_u32(a), _u32(b), 0, 0]


def inc_counter(counter):
    counter[3] = _u32(counter[3] + 1)
    if counter[3] != 0:
        return
    counter[2] = _u32(counter[2] + 1)
    if counter[2] != 0:
        return
    counter[1] = _u32(counter[1] + 1)


def aes_ecb_encrypt_block(key: bytes, block16: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(block16)


def xor_stream(key: bytes, counter, data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 16):
        counter_block = struct.pack(">IIII", *counter)
        ks = aes_ecb_encrypt_block(key, counter_block)
        chunk = data[i:i + 16]
        out.extend(c ^ ks[j] for j, c in enumerate(chunk))
        inc_counter(counter)
    return bytes(out)


def encrypt_token(plaintext: str, token: str) -> str:
    key = normalize_key(token)
    nonce, counter = new_nonce_and_counter()
    body = xor_stream(key, counter, plaintext.encode("utf-8"))
    return base64.b64encode(nonce + body).decode("ascii")


def decrypt_token(ciphertext_b64: str, token: str) -> str:
    key = normalize_key(token)
    raw = base64.b64decode(ciphertext_b64)
    nonce, body = raw[:8], raw[8:]
    counter = set_counter_from_nonce(nonce)
    pt = xor_stream(key, counter, body)
    return pt.decode("utf-8")


# ======================
# Test call
# ======================
def main():
    payload = {
        "type": "query",
        "data": "SELECT 1 AS one",
        "callback": "true"
    }

    plaintext = json.dumps(payload, separators=(",", ":"))

    print("TOKEN:", TOKEN)
    print("KEY SHA256:", normalize_key(TOKEN).hex())

    enc = encrypt_token(plaintext, TOKEN)

    r = requests.post(
        ODOO_URL,
        json={"data": enc},
        headers={
            "X-Odoo-Database": ODOO_DB,
            "Content-Type": "application/json",
        },
        timeout=30
    )


    print("HTTP:", r.status_code)
    print("RAW RESPONSE:", r.text[:200])

    if r.status_code != 200:
        print("FAILED")
        return

    dec = decrypt_token(r.text.strip(), TOKEN)
    print("\nDECRYPTED RESPONSE:\n", dec)


if __name__ == "__main__":
    main()
