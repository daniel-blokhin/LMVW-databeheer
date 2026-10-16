# From the original demo to this repository

## 1. Keep the original archives private

The original tender ZIP and DSO ZIP are working material, not repository assets. They contain duplicated notebooks, source snapshots, local paths, caches and hardcoded credentials. Preserve a private backup outside Git. Revoke/rotate exposed keys independently of this refactor. Do not import the original Git history or notebook outputs into the new repository.

The repository itself contains only the new implementation, metadata/documentation and independently generated synthetic examples. It does not depend on the old folder hierarchy after the private migration step.

## 2. Install and prove the synthetic path first

From the repository root in an activated virtual environment:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m lmvw_pipeline run --config configs/demo.yaml
python -m lmvw_pipeline verify-bundle examples/database_ready
```

The fixture demonstration is not a live API demonstration. The adapters' request/pagination/replay behaviour is additionally covered by mocked transport tests, and needs a small real-service smoke test with newly issued credentials before being described as live-verified.

## 3. Reuse the original plan and BAG/BRK source snapshots

```bash
python scripts/import_legacy_data.py --archive "/private/location/LMVW Databeheer tender 1.zip"
python -m lmvw_pipeline validate --config configs/snapshots.example.yaml
python -m lmvw_pipeline run --config configs/snapshots.example.yaml
```

On Windows, a quoted full Windows archive path is accepted. `validate` returns exit code 2 if records are rejected; inspect the generated diagnostics, then run the full pipeline deliberately. Do not chain it with `&&` when intentionally testing an imperfect delivery.

The helper extracts exactly six allowed files into ignored `data/private`:

| File | Selection/role |
|---|---|
| `Planlijst demo beheer LMVW.xlsx` | Original `0. LMVW data` plan delivery, worksheet `Planlijst` |
| `LMVW demo plannen.gpkg` | Original `0. LMVW data` geometry, layer `LMVW demo` |
| `bag_panden_db.csv` | Latest-scope `output_lmvw` BAG source snapshot |
| `bag_verblijfsobjecten_db.csv` | Latest-scope `output_lmvw` BAG source snapshot |
| `bag_verblijfsobject_pand_relatie_db.csv` | Official BAG VBO/pand relation snapshot |
| `brk_percelen_db.csv` | Latest-scope `output_lmvw` BRK source snapshot |

The helper refuses existing targets, ambiguous selections, unsafe paths or oversized members. It writes a private import manifest. It does not execute notebooks, copy the DSO archive or trust old plan-relation CSVs. New plan/source links are recalculated with the new identities and geometry logic. Original `output/` dummy-scope snapshots are deliberately not selected when `output_lmvw/` snapshots exist.

`configs/snapshots.example.yaml` sets DSO and RP to false because no DSO API response dataset was provided in the DSO archive. There is no fabricated DSO enrichment in that mode. The `source_status` output records DISABLED, not a successful zero-result query.

For other delivery filenames or locations, copy an example to `configs/my.local.yaml` and edit it. All relative file paths resolve against the YAML file's directory. Place private configuration in `*.local.yaml`; do not store keys inside it. The exact source mappings are in `columns.yaml`, not a brittle list of column positions inside a notebook.

## 4. Enable real API extraction deliberately

Copy `configs/live.example.yaml` to `configs/my.local.yaml`. Keep a small, approved geographic scope for the first test. Select PRODUCTION or PRE explicitly; never label PRE output as production observations. The optional RP adapter uses its own production service and credential, even if the DSO service is PRE; the output records both environments separately.

The live example enables BAG, BRK and DSO and leaves RP off. Use newly issued, least-privileged provider credentials in environment variables or mounted secret files as described in `SECURITY.md`. For local interactive use:

```bash
python scripts/run_live.py --config configs/my.local.yaml
```

The helper prompts without echo for missing enabled-source credentials. It does not save them. Automated environments should inject secrets through their managed runtime, then invoke:

```bash
python -m lmvw_pipeline run --config configs/my.local.yaml
```

The declared `snapshot_utc` controls DSO temporal queries; `null` selects the current UTC time once at run start. BAG and BRK calls retrieve the provider's available state at their actual retrieval time. This is not cross-provider transactional time travel.

If a source rejects a payload or changes its schema, the run fails with a controlled error, keeps input-validation diagnostics and writes no successful database bundle. Investigate the applicable official specification and add a regression test. Do not substitute synthetic data or suppress the failure to obtain a green run.

## 5. Replay a completed live extraction

```bash
python -m lmvw_pipeline run --config configs/my.local.yaml --mode replay --replay-from "/private/data/runs/LIVE_RUN_ID"
```

Point to the run directory containing `run_context.json` and `raw`, not to `database_ready`. Replay uses the original DSO temporal instant, requires the same delivery and rule/mapping files, and looks up the exact request fingerprints. Changing scope or source configuration may make the cache insufficient; that is an error, not permission to fetch live. No key is loaded in replay mode. Protect the raw cache just like the original data.

## 6. Prepare a Git repository

Start with private visibility until ownership/reuse and data-publication checks are complete. After confirming the ZIP's reviewed contents:

```bash
git init
git add .
python scripts/check_repository.py
git diff --cached --stat
git diff --cached
```

Review what is actually staged. `.gitignore` does not remove files already tracked in Git. Do not use a public repository to store private inputs, raw responses, generated production bundles, old notebooks or API keys. A `.git` directory and GitHub remote are intentionally not embedded in this deliverable: choose your own repository, author details and hosting settings.
