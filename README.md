# ShopAI — Open development source and experimental evidence (2026-11-21 snapshot)

> **Start here.** This is a **readable, preserved code-and-evidence snapshot** of ShopAI work—not a one-click installed copy of the running ShopAI computer. The original project remains on its own computer. This folder is designed to make a fresh computer or AI assistant understand the work without guessing, reinstalling everything, or damaging an existing system.

## Why ShopAI exists

The long-term workshop goal is to read real mechanical engineering drawings, recognize their text, symbols, geometry, and dimension-to-feature relationships, and eventually build **dimensionally accurate, editable** FreeCAD models. A shape that only looks right is not success. **The current research priority is the drawing-reading front end**, not speculative STEP/FCStd construction. The owner reports substantial improvements after early experimental difficulties; the historical failures in this archive are **not** a claim about the latest live performance.

## What is in this folder?

| Location | Meaning |
|---|---|
| `SOURCE/live/` | Preserved custom ShopAI application and tool/bridge source **from the collected archive**. The name does **not** mean currently running code was rechecked today. |
| `SOURCE/next/` | Preserved ShopAI-Next research source, configs, and **compact** experiment records. Many historical outputs are included. |
| `INVENTORY/external_repositories_and_dependencies.json` | External repository names/paths, OCR environments, and observed package metadata—**inventory, not downloaded dependencies**. |
| `INVENTORY/SOURCE_SHA256.tsv` | SHA-256 and size for every bundled source/evidence file. |
| `INVENTORY/earlier_static_audit_20261121.txt` | Earlier static audit and caveats; results may be older than recent ShopAI progress. |
| `DOCS/GETTING_STARTED.md` | Plain-language downloading, reading, and cautious recovery instructions. |
| `DOCS/DEPENDENCIES.md` | External tools and Python packages that may be needed, and how to verify versions. |
| `DOCS/ADDING_AI_TO_ZOO.md` | The AI-zoo requirements and safe model-addition procedure. |
| `DOCS/OPERATING_RULES.md` | Constraints future coding assistants must respect. |
| `DOCS/COVERAGE_AND_GAPS.md` | Exactly what this snapshot cannot establish. |
| `AGENTS.md` | Guidance for AI coding agents working in this folder. |

## Where is the actual running project?

These paths are **historical locations on ShopAI** (`10.42.0.10`), **not paths to create on this computer automatically**:

- Main application: `/home/shopai/ShopAI/`
- Original research: `/mnt/shopai-data-new/cad-research/`
- Newer experimental clone: `/mnt/shopai-data-new/ShopAI-Next/`
- LinuxCNC operates on a **different Panasonic Toughbook CF-31**, not on ShopAI.

The ShopAI cluster has three configured PCs: ShopAI `.10`, VirusLoader `.1`, VirusLoaderMax `.2` on the `10.42.0.x` private network. No other machine should be assumed configured.

## Can I download it and run it?

**You can download and inspect the code immediately. You should not expect a fresh laptop to run all of ShopAI immediately.** This archive intentionally excludes large downloaded repositories, model weights, Python environments, private credentials, and some historical inputs. Some scripts refer to tools or absolute paths on the original ShopAI host. No restore, dependency installation, or model download has been performed or validated from this archive. **Do not run a script or overwrite the live ShopAI installation just to see what happens.**

For a safe start: **GitHub → Code → Download ZIP → extract → open this README → read `DOCS/GETTING_STARTED.md`.** If using Git, clone `https://github.com/AZgunNut/ShopAI-Open.git`.

## Adding local AI models

See `DOCS/ADDING_AI_TO_ZOO.md`. Model weights are stored **outside this Git repository**. Model-list changes must retain all original entries, preserve the separate 17-model **UNCHAINED AI MODELS** section, and retain one universal shared-tool catalog.

## Important honesty boundary

The uploaded source input was a **curated 2026-11-21 static archive**. Its selection was based on folder paths, not verified authorship. It is **not proven complete**, and some custom patches to downloaded upstream projects were explicitly excluded. The latest live build and all late experiments have **not** been independently re-collected. See `DOCS/COVERAGE_AND_GAPS.md` before claiming a test, migration, or restoration is complete.

## Never do these without explicit owner approval

Do not change ShopAI's working network, gateways, RPC, menus, model files, shared tools, backups, or FreeCAD setup. Do not install packages on ShopAI, delete data, or replace code. Do not introduce arbitrary experimental timeouts, trial ceilings, token caps, or other stopping conditions. Evaluate actual outputs against independently established truth, not against attractive demo images.


## Public repository and contributions

This public repository is intended to let others **read, download, fork, evaluate, and propose improvements** to the ShopAI drawing-recognition project. It is a **partial archival development snapshot**, not a tested installer or the latest fully verified running build. Do not modify the original user's working ShopAI computer.

GitHub repository: `https://github.com/AZgunNut/ShopAI-Open`

**License status:** No open-source license is being asserted for these archived files until original authorship and third-party rights have been reviewed and the owner chooses a license. GitHub's fork feature is available for public repositories, but broader legal rights to reuse or redistribute this content require a valid license. See `LICENSING.md`.

**Important public security notice:** This source retains example local IPs, historical machine names and absolute paths because they help understand the original setup. No operational tokens, private keys or model weights are intentionally included. Do not upload secrets, credentials, personal data or raw terminal/home backups in contributions.
