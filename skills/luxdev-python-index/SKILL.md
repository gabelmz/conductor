---
name: luxdev-python-index
description: Reusable file indexing setup that generates root and deep directory maps, JSON manifests for rendering, and a workspace-specific shortcut skill.
---

# luxdev-python-index

This is a reusable file indexing setup, not an agent.

## Purpose

- Generate a clean root-level index.
- Generate full-depth index artifacts for deeper inspection.
- Create JSON manifests for easy rendering and downstream tooling.
- Generate a dynamic workspace-specific shortcut skill.

## Outputs

Inside `.eb/`:
- `manifest.json`
- `index.md`
- `manifest-all.json`
- `index-all.md`
- `index.py`
- `INDEX_README.md`

Inside `skills/`:
- `luxdev-python-index/SKILL.md`
- `<COMPUTER_NAME>-<ROOT_FOLDER_NAME>-index-build/SKILL.md`

## Rebuild

```bash
python .eb/index.py
```
