# Publication and ownership note

This repository is a **portfolio reconstruction** of data-processing work associated with a housing-monitoring tender demonstration. It is **not** a deployed national monitoring service.

- Input data in `examples/input/` and all committed CSV results are synthetic.
- Original tender deliveries, internal scripts, original API caches and credentials are not included.
- The Python quality checks are a standalone implementation; the original demo used IO Factory for part of its validation workflow.
- Do not upload company/client files or reuse project-specific proprietary code without confirming permission from its owner. Publishing a public GitHub repository does not itself grant redistribution rights.
- No real DSO API key is bundled. Previously exposed credentials must be rotated/revoked; removing a value from source code is insufficient.
