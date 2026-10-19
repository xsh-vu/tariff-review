# Presentation

This directory contains the Harbor & Crane panel-presentation materials.

- `harbor-crane-tariff-audit-demo-v2.pptx` — validated four-slide presentation deck.
- `build_deck.mjs` — editable deck-generation source.
- `DEMO_RUNBOOK.md` — five-minute demonstration sequence and fallback guidance.
- `build/` — generated slide previews, validation receipts, candidate decks, and chart scratch data. This directory is intentionally ignored by Git.

From the repository root, rebuild the deck with:

```bash
node presentation/build_deck.mjs
```

The build script uses the local Codex presentation runtime paths recorded in the script. Update those paths if the runtime installation changes.
