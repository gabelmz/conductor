---
name: desktop-lliuib2-conductor-index-build
description: Workspace-specific shortcut for navigating and rebuilding indexes for conductor on DESKTOP-LLIUIB2.
---

# DESKTOP-LLIUIB2-conductor-index-build

This skill is the workspace-specific shortcut for this indexed root.

## Workspace identity

- Machine: `DESKTOP-LLIUIB2`
- Root folder: `conductor`

## Read first

Inside `.eb/`:
- `manifest.json`
- `index.md`
- `manifest-all.json`
- `index-all.md`

## Rebuild

```bash
python .eb/index.py
```

## Notes

- This skill is generated dynamically.
- The shared indexing setup lives in `skills/luxdev-python-index/`.
- This skill stays small and root-specific.
