# SAP Core API (Encrypted) - Odoo Module

Module ini menyediakan endpoint **/coreapi** sebagai pengganti `coreAPI.php` versi PHP.

## Alur
1. SAP (via `sap_bridging.php`) mengirim payload **terenkripsi** (base64) pada field `data` atau raw body.
2. Endpoint Odoo melakukan decrypt, parse JSON (`{type,data,callback}`), mengeksekusi SQL, membangun response dengan separator `[//]` dan `[|]`.
3. Response diencrypt kembali dan dikembalikan sebagai plain text (base64).

## Endpoint
- `POST /coreapi`

Input:
- `data=<ciphertext_base64>` (form-urlencoded) **atau** raw body berisi ciphertext base64.

Output:
- ciphertext base64 (plain text).

## System Parameters (Settings -> Technical -> Parameters -> System Parameters)
- `sap_coreapi.token` : token/key untuk encrypt/decrypt (default diambil dari contoh)
- `sap_coreapi.allow_modify` : `1/0` (default `0`). Jika `0`, hanya mengizinkan `SELECT`.
- `sap_coreapi.enable_log` : `1/0` (default `1`). Jika `1`, request/response (encrypted + plaintext) dicatat ke model `sap.coreapi.log` untuk kebutuhan tagging.

## Logging untuk Tagging
Semua transaksi (decrypted payload, SQL, response plaintext) dicatat ke model:
- `sap.coreapi.log`

Akses hanya untuk user group **Settings / Administrator** (`base.group_system`).

## Dependensi Crypto
Implementasi CTR membutuhkan AES-ECB block encryption.
Module ini menggunakan `pycryptodome`:

- Python package: `pycryptodome`

Jika environment Odoo kamu belum ada, install:
- `pip install pycryptodome`

## Catatan Keamanan
Desain legacy ini mengeksekusi SQL dari luar sistem. Default module **memblok query non-SELECT**.
Jika butuh INSERT/UPDATE/DELETE, set `sap_coreapi.allow_modify=1` dan sangat disarankan menambah whitelist/validasi.
