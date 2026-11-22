# Coverage, provenance, and limitations — read before trusting results

## Source of this package

- Prepared from `ShopAI_Custom_Frontend_Curated_20261121.zip` (a **static archived copy** previously created from a user-uploaded collector ZIP).
- The previous collector reported 21,021 selected files and 82.11 MiB ZIP; the curated archive had **2,118** project files plus three audit metadata entries. This folder adds user documentation and source checksums.
- Selection identified candidate custom code by project paths; **authorship was not confirmed by a complete commit history**.
- A basic scan of these archived files for common credential/token patterns showed no matches, but no automatic scan guarantees a file has no private data. Avoid publication of any additional logs until sensitive information has been reviewed.

## Known omissions

- Not the latest audited live `/home/shopai/ShopAI` tree; this package has not contacted the ShopAI LAN.
- Original drawings and all independently certified per-source ground truths are not fully included.
- Some later ShopAI-Next scripts and reports may have been omitted by original collection rules or budget limits.
- Altered upstream trees (notably `CADOCR-Paddle3-patched`, `eDOCr2-native-p5-resize-patched`, and `Drawing-to-DXF`) were omitted from the curated bundle and may contain owner-written patches. This package **cannot claim to preserve those deltas**.
- Third-party repository source, OCR/model weights, dependency wheels, Python virtual environments, system packages, executable FreeCAD installation, passwords, SSH keys, and browser profiles are intentionally absent.
- The observed 50 external-repository paths include repeated locations and are **not 50 necessarily distinct upstream projects**.

## How to interpret old results

Historic scores, including early D1 misses and selector evaluations without independently verified spatial ground truth, are dated evidence of those specific tests. They **do not** establish the current performance of the owner's newer drawing-recognition work. The owner reports substantial later improvements; current ability needs evaluation against the actual latest source, inputs, truth, and logs.

A ZIP check, syntax check, launcher startup, or a passing tool call alone is not proof of engineering interpretation accuracy. Score independent OCR glyph occurrence/location, geometry, and dimension-feature relationships separately.

## What is needed for a truly portable, proven recreation

1. Capture the **current** custom source and custom patches from the live ShopAI host with owner permission, retaining existing path maps and hashes.
2. Inventory exact current dependencies and backend versions; pin actual working environments.
3. Preserve exact model IDs/hashes and separately obtained weights/projectors.
4. Include the owner's exact source drawings with permission and independently certified ground truths.
5. Run a clean-room restore and acceptance tests on a disposable machine or clone, without changing live ShopAI.

Until those are done, call this a **development handoff snapshot**, not a fully restored appliance.
