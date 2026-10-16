# External interface and engineering references

Official documentation was checked during construction on 2026-10-16. References establish the intended API/engineering contracts; they are not a substitute for live compatibility tests. Provider interfaces may change.

| Interface | Implemented purpose | Official reference |
|---|---|---|
| PDOK BAG OGC API v2 | Panden, verblijfsobjecten, explicit CRS, bounded feature extraction | [API landing page](https://api.pdok.nl/kadaster/bag/ogc/v2/) |
| PDOK BRK cadastral map OGC API v1 | Parcel geometry and cadastral attributes, not ownership | [Perceel schema](https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1/collections/perceel/schema) |
| DSO Omgevingsdocumenten Presenteren v8 | Regulation/permit search and regulation document structure | [API register](https://developer.omgevingswet.overheid.nl/api-register/api/omgevingsdocument-presenteren/) and [OpenAPI](https://developer.omgevingswet.overheid.nl/publish/pages/166112/omgevingsdocumenten-presenteren-v8.json) |
| DSO Geometrie Opvragen v1 | Retrieve referenced document/area geometry | [API register](https://developer.omgevingswet.overheid.nl/api-register/api/omgevingsdocumenten-geometrie-opvragen/) |
| Ruimtelijkeplannen Opvragen v4 | Optional IMRO document lookup | [API register](https://developer.omgevingswet.overheid.nl/api-register/api/rp-opvragen/) |
| DSO credential registration | Runtime x-api-key authentication and environment selection | [API key information](https://developer.omgevingswet.overheid.nl/formulieren/api-key-aanvragen-0/) |

Presenteren v8's consulted OpenAPI defines one-based pagination for the implemented searches. The adapter does not assume page zero. DSO temporal parameters are fixed once for each run. Regulation identifiers are encoded for the document-structure URI; geographic request coordinates are rounded only in the request, not in the local analytical geometry.

The DSO/RP implementation covers the described resources, not every LVBB publication, permit application lifecycle or legal milestone. A missing implemented payload variant should fail visibly and lead to a new fixture/test, not be silently interpreted as no data.

Engineering references:

- [Python Packaging: pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) and [src layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).
- [OWASP secrets management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html).
- [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use).
- [Pinned checkout v7.0.1 commit](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1).
- [Pinned setup-python v7.0.0 commit](https://github.com/actions/setup-python/commit/5fda3b95a4ea91299a34e894583c3862153e4b97).

The supplied Basisset, dataprotocol and tender/project documents informed domain interpretation but are not redistributed. Their requirements and confidential publication rules are not represented as fully implemented or certified by this portfolio.
