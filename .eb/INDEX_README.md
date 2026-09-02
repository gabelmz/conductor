# Goal

- Create fully logged directory indexes without drowning the root folder in support files.
- Generate JSON manifests for easy rendering and downstream tooling.
- Keep one reusable indexing setup plus one dynamic workspace-specific shortcut skill.

## What this is

This is not an agent.

It is a directory indexing setup built around:

- one reusable indexing skill,
- one dynamic workspace-specific skill,
- one root-level summary manifest,
- one full-depth manifest for complete inspection.

## What this enables

- Quick human-readable workspace maps.
- Machine-readable manifests for rendering, navigation, or UI layers.
- A repeatable indexing workflow that works across many computers.
- A lightweight per-workspace shortcut without duplicating the full indexing system.

## End Structure

```text
<root>/
├── skills/
│   ├── luxdev-python-index/
│   │   └── SKILL.md
│   └── <COMPUTER_NAME>-<ROOT_FOLDER_NAME>-index-build/
│       └── SKILL.md
└── .eb/
    ├── index.py
    ├── index.md
    ├── manifest.json
    ├── index-all.md
    ├── manifest-all.json
    └── INDEX_README.md
```

## How to rebuild indexes

```bash
python .eb/index.py
```
