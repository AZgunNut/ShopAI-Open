# Getting started — download, read, and recover safely

This document is for an owner who wants clear directions, not a complicated development environment.

## Download

1. Open the public `AZgunNut/ShopAI-Open` repository. No account is required to download.
2. Click **Code** → **Download ZIP**.
3. Extract the ZIP into a new folder on your computer.
4. Open `README.md` (this folder).
5. Browse `SOURCE/live/` for the application and `SOURCE/next/` for research and benchmark files.

**No account/password, model download, dependency install, or command is needed simply to read the files.**

## If you want Git instead of Download ZIP

In a terminal on a machine with Git and approved GitHub access:

```bash
git clone https://github.com/AZgunNut/ShopAI-Open.git
cd ShopAI-Open
```

The repository is public. You do not need GitHub authentication to clone or download it.

## Find specific material

- Application entry points (historical): `SOURCE/live/shopai_agent.py`, `SOURCE/live/qwen_agent.py`, `SOURCE/live/shopai-appliance.sh`.
- Model manager: `SOURCE/live/tool-suites/model-manager/loaded_ai_manager.py`.
- Shared tool inventory: `SOURCE/live/tool-suites/registry/tools.json` and `SOURCE/next/projects/cad-research/ShopAI-Tools-and-Capabilities/registry/tools.json`.
- OpenCV v5 candidate: search under `SOURCE/next/` for `outline_v5/autotune.py`.
- OCR selector: search under `SOURCE/next/` for `ocr_selector/selector_v2.py` or `Dual-1060-1947-Selector-v2`.
- Research results: `SOURCE/next/projects/cad-research/ShopAI-Tools-and-Capabilities/history/` and `SOURCE/next/projects/cad-research/experiments/`.
- Third-party software inventory: `INVENTORY/external_repositories_and_dependencies.json`.

## Can I restore ShopAI from this folder?

**Not automatically.** The code may use absolute paths to the existing ShopAI machine, external programs, model files, data inputs, and isolated Python environments not shipped here. This is a source/evidence handoff, **not a tested installer or complete disk backup**.

Safest procedure on any NEW computer: inspect the inventory, obtain approved versions of dependencies/models separately, make a disposable working copy, fix one demonstrated issue at a time, and verify functions against known-good tests. On the existing ShopAI computer: first compare the archived file hashes with the live files; do not overwrite working code.

## What counts as success?

- **Collected**: a file exists in the snapshot.
- **Installed**: its runtime dependencies are present.
- **Starts**: a program launches.
- **Executes**: a specified test actually runs.
- **Passed**: results meet independently defined acceptance criteria.

These are different conditions. Never report one as proof of the next.
