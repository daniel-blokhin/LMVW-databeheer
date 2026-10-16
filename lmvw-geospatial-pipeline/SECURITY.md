# Security and publication boundary

## Credentials already embedded in the source material

The source-code review found hardcoded credentials, including fallback values in environment-variable lookups. Those values are not copied into this repository and were not used to contact services. **Revoke/rotate exposed credentials at the provider before using live mode.** Removing a value from the latest file does not revoke it or remove it from earlier copies or Git history.

This repository implements specific controls; it does not certify compliance with every legal, contractual or security requirement.

## Runtime secret handling

The DSO adapter selects exactly one variable based on its explicit environment:

- `DSO_API_KEY_PRODUCTION` for the production DSO services.
- `DSO_API_KEY_PRE` for the pre-production DSO services.
- `RUIMTELIJKE_PLANNEN_API_KEY` for the optional, distinct RP service.

For each variable, `<NAME>_FILE` can instead point to a mounted secret file. Direct value and file injection are mutually exclusive. Files must be regular, non-symlink files; POSIX group/other permissions are rejected. On Windows, operators must set and verify restrictive ACLs. A managed secret store can supply these environment variables or mounted files; no cloud-specific secret-store integration is claimed here.

There is no real key, default key, `.env` auto-loader or CLI key argument. `Secret` values have redacted string/repr output. The transport owns the authentication header and only adds `x-api-key` after validating the destination. The helper `scripts/run_live.py` uses hidden `getpass` input and refuses a terminal that would fall back to echoing input.

Python cannot guarantee erasure of immutable secret strings in memory. Environment injection is not encryption at rest, and other processes with sufficient privileges can inspect process memory. Protect the runtime account, host, container configuration and secret store.

## Request controls

`http.JsonClient` restricts each client to one HTTPS host and service-path prefix. The source adapters use fixed official endpoints, not arbitrary URLs from YAML. Unexpected hosts, credentials in URLs, path traversal, secret-like query parameters, conflicting query parameters and redirects are rejected before another destination can be contacted. Environment proxies and `.netrc` are disabled (`trust_env=False`). TLS certificate validation remains enabled and there is no insecure override.

Requests are bounded by connect/read timeouts, retry attempts, response bytes, page count, feature count and geographic scope. Only `GET` and read-only `_zoek` `POST` operations are allowed. The original code's credentials are never needed for tests or fixture mode. All needed live credentials are checked before the first external source request.

Normal application logs contain aggregate stage information and controlled error messages. They omit request headers, response bodies, arbitrary third-party exception text and tracebacks. Cached metadata contains request fingerprints, not authentication headers or raw request parameters. A response echoing the active literal secret is rejected before caching. Do not enable HTTP wire/debug logging, crash dumps or environment dumps in a real deployment. These controls cannot guarantee that an external provider never logs a credential it receives.

## Data is separate from secret safety

`data/private`, `data/runs`, raw response caches and generated exports are ignored by Git. They are not encrypted by the pipeline. Run folders use restrictive POSIX permissions where supported; storage encryption, backup controls, retention, access review and deletion are deployment responsibilities.

A live DSO query sends plan geometry to the provider; BAG/BRK requests disclose a geographic query scope. Confirm that this processing is authorised, including for confidential plans. `confidential = true` is a data label, not an access-control system.

The complete database-ready bundle contains confidential records, raw input values, plan locations, relation evidence and quality findings. It is an **internal staging product**, not an approved open-data release. Filtering out confidential plans alone is not asserted to implement the full LMVW dataprotocol. A future public layer needs explicit authorisation, approved aggregation/suppression, historical-release policy and tests against direct/indirect disclosure.

CSV files are intended for typed database ingestion. Free text is preserved, including strings that a spreadsheet might interpret as formulas. Do not double-click untrusted production exports in spreadsheet software; import explicitly as text or build a separately sanitised presentation export. SQL values must later be inserted with parameters, not string concatenation.

## CI and repository controls

The CI workflow does not request DSO/RP credentials, query live sources or upload real data. Its token permissions are read-only, checkout credentials are not persisted and action references are pinned to reviewed full commit SHAs. It runs on `push`/`pull_request`, not privileged `pull_request_target` execution of untrusted code.

`scripts/check_repository.py` checks tracked files (or a local source tree before Git initialisation) for prohibited assets, common credential patterns and literal credential assignments/fallbacks. It prints only filenames and reason categories. This lightweight guard is **not** exhaustive secret detection, a dependency vulnerability scan, a penetration test or a rights review. Enable your host's secret scanning/push protection and dependency scanning where available. Review each dependency update and rerun tests before accepting it.

Before the first push, initialise Git, stage only reviewed content, run the repository check, inspect `git diff --cached`, verify the intended visibility and confirm rights to publish. Never add the original ZIP or notebooks to a public repository merely because this refactor is clean. For a suspected leak, revoke the credential first, investigate history/logs/backups, and coordinate removal with the repository and credential owners.

## References

- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [GitHub Actions secure-use reference](https://docs.github.com/en/actions/reference/security/secure-use)
- [Official DSO API key request information](https://developer.omgevingswet.overheid.nl/formulieren/api-key-aanvragen-0/)

Security-sensitive values or confidential examples must not be posted in public issues.
