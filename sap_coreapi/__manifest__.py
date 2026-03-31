{
    "name": "SAP Core API (Encrypted)",
    "summary": "Drop-in replacement for legacy coreAPI.php (AES-CTR encrypted payload) to serve SAP bridging.",
    "version": "1.0.0",
    "category": "Integration",
    "license": "LGPL-3",
    "author": "Bayu Faturahman",
    "depends": ["base"],
    'license': 'LGPL-3',
    "data": [
    ],
    "installable": True,
    "application": False,
    "external_dependencies": {"python": ["cryptography", "pycryptodome"]},
}
