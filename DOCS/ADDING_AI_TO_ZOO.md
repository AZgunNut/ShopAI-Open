# Adding a local AI model to ShopAI — without breaking the existing Zoo

**Purpose:** Explain the intended procedure, file locations, and safety checks. This is not an untested drop-in model installer. The installed/current model-manager source must be inspected before changing it.

## The required user experience

- Keep the **same existing model-selection screen**, with all original models and numbering untouched.
- Add/keep the separate divider **`UNCHAINED AI MODELS`** and its 17 specifically chosen entries in the original order. Do not create another submenu or mix these choices into pre-existing groups.
- Each model has user-selectable **local** (controlled tools), **ChatGPT Web bridge**, and **OpenAI API** modes. External access is never automatic.
- Selection order: **backend → model → resource mode → NEW or CONTINUE** an explicitly chosen conversation. Default **NEW** without hidden context injection.
- **One active inference model per physical PC**; on switch or `/quit`, stop only the host's verified owned model process, verify resource release, and preserve unrelated infrastructure and other hosts.
- All models use the **same shared tools**; permissions for protected/system/network actions remain at the tool/dispatcher boundary.

## Historical model and tool entry points to inspect first

- `../SOURCE/live/shopai_agent.py`
- `../SOURCE/live/qwen_agent.py`
- `../SOURCE/live/tool-suites/model-manager/loaded_ai_manager.py`
- `../SOURCE/live/tool-suites/registry/tools.json`
- `../SOURCE/next/projects/cad-research/ShopAI-Tools-and-Capabilities/registry/tools.json`

These are archived copies; actual live paths, menu construction, and dispatcher behavior must be verified before modifying anything.

## The exact historically requested Unchained roster (in order)

1. Qwen2.5-3B Abliterated SFT
2. Qwen3-4B Instruct Abliterated
3. Gemma 3 4B Abliterated
4. MedGemma 4B Abliterated
5. Qwen2.5-Coder-7B Abliterated
6. Dolphin 3.0 Llama 3.1 8B
7. Qwen3-8B Abliterated v2
8. Dolphin 2.9.3 Mistral Nemo 12B
9. Gemma 3 12B Abliterated
10. Qwen3-14B Abliterated v2
11. DeepSeek-R1 Distill Qwen 14B Abliterated v2
12. GPT-OSS-20B Abliterated GGUF
13. Dolphin 3.0 Mistral 24B
14. Dolphin 3.0 R1 Mistral 24B
15. Gemma 3 27B Abliterated
16. Qwen3-Coder-30B-A3B Abliterated
17. Qwen3-30B-A3B Instruct Abliterated

**Names alone are not exact model IDs.** The original audit did not establish definitive repositories, GGUF filenames, quantization, checksums, or compatible projector files for every entry. Do not substitute a similar name or fabricate a path.

## Safe addition of ONE new model

1. **Read-only inventory:** verify current menu code, registry, current live model directories, available RAM/VRAM, service/process ownership, and whether the requested model is already present.
2. **Identify exact model**: upstream repository, release, filename, quantization, hash, license, architecture, backend compatibility, and projector if applicable.
3. **Download separately**, only to the explicitly approved model-storage location; weights are not stored in GitHub. External downloads require the owner's authorization.
4. **Back up the current menu/registry** and write a minimal proposed diff. Preserve existing model names, numbers, ordering, tool registry, and resource routes.
5. **Add ONE model choice** to the correct group on an isolated copy. No new independent menu or model-specific tool silo.
6. **Verify end-to-end**: model launches using the selected backend; NEW session is genuinely clean; CONTINUE selects a known saved conversation; tool discovery **and actual invocation** work; switching and `/quit` terminate only the owned model; RAM is released; no other PC/services are stopped.
7. **Approve and apply** the tested change to live ShopAI only with explicit owner permission and rollback available. Record the diff and test results.

## Running a downloaded copy elsewhere

A new user will need to provide their own compatible model files and installed inference backend. Model files are large and intentionally absent. Do not assume the archived absolute paths exist outside the original ShopAI computer.
