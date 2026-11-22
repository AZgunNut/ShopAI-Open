# Binding ShopAI development and experiment rules

These are condensed operating constraints from prior instructions and handoffs. The current owner's latest explicit request supersedes older conflicting instructions.

1. **Correctness, instruction fidelity, and verified evidence outrank speed or appearance.** Do not silently expand scope or substitute inputs.
2. **No arbitrary experimental limits.** Do not insert timeouts, early-stop criteria, trial/iteration caps, context limits, max-output-token limits, CPU/RAM ceilings, or duration restrictions unless required by actual measured constraints or explicitly authorized. A network diagnostic timeout is not an experiment-completion criterion. If interrupted, mark `INCOMPLETE`, preserve checkpoints, and report why.
3. **Preserve every existing working function**: ShopAI network/SSH/rsync, gateway, llama.cpp RPC, model menu, desktop launchers, shared tools/bridge, FreeCAD and model storage.
4. **Inspect existing code/logs/versions first; fix one evidenced issue at a time.** Make the minimum diff, never rewrite unrelated modules. Show backup and rollback. Permission to inspect is not permission to modify.
5. **No unauthorized edits, deletes, renames, moves, reinstallations, dependency upgrades, network changes, model downloads, external AI calls, or blanket service shutdowns.** Ask approval for live modifications.
6. **Use actual specified source files** with independent truth, SHA-256 hashes, fixed baselines, controlled factors, retained failures and authentic results.
7. **Front-end drawing recognition is the current priority**: every glyph/symbol and location, outlines and geometry, then correct dimension-to-feature association. Do not divert to CAD/STEP experiments without owner direction. Score OCR, geometry and associations separately.
8. **Preserve OpenCV v5 and VTracer** as independent baselines and investigate genuine complementary fusion. Do not confuse a visual overlay with engineering correctness.
9. **No arbitrary limits on hardware capability**: measure real memory, threads, model context/output and needed emergency reserve before assigning restrictions. Don't preallocate unnecessary buffers.
10. **One inference model per physical host**, never kill unrelated services or other hosts. NEW/CONTINUE conversation context must be a user choice, default NEW.
11. **Universal shared tools** for all model groups; privileges and network actions require appropriate approval; tool listing alone is not tool execution.
12. **Local-first, no silent external data transfer.** Use explicitly chosen ChatGPT Web/API routes only. Paid API usage needs prior cost approval.
13. **Long jobs**: a 10-minute heartbeat, hourly progress reports, persistent logs and resumability; report stalled/failed conditions honestly. A historical one-hour stall condition belonged to one OCR evolution test and is not universal.
14. **Emergency stop** should be independently controlled, target verified-owned processes only, preserve checkpoints, and support the discussed unique 24-character code and `TERMINATE` sentinel. Do not fabricate a code or imply completion.
15. **Consolidated Bash for executable steps**: preflight + explicit action + logs in one paste; separate consolidated export/pickup script. Do not give code that casually alters live systems. Verify actual execution vs merely writing the script.
16. **Don't claim results without evidence.** Explicitly distinguish code existence, installation, execution, actual score, and end-to-end validated result. Report all omissions and failed steps.
17. **ShopAI is the AI machine; the separate Panasonic Toughbook runs LinuxCNC.** Do not merge roles or invent configured PCs.
18. **Document librarians remain three separate tasks**; preserve originals, compare candidates on identical copied corpora, alphabetize subjects and titles, preserve proposed/original name mappings and use STL thumbnails.
