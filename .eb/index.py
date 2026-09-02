import os
import json
import socket
import shutil


def get_root_dir():
    current_dir = os.path.dirname(os.path.abspath(__file__))

    if os.path.basename(current_dir) in (".eb", "src", "index", "engine"):
        return os.path.dirname(current_dir)

    return current_dir


def build_tree(dir_path, current_depth, max_depth, root_dir, ignore_dirs, ignore_files):
    items = []

    try:
        entries = list(os.scandir(dir_path))
    except OSError:
        return items

    dirs = []
    files = []

    for entry in entries:
        if entry.is_dir():
            if entry.name in ignore_dirs:
                continue
            dirs.append(entry.name)
        elif entry.is_file():
            if entry.name in ignore_files:
                continue
            files.append(entry.name)

    dirs.sort(key=lambda x: (x.lower(), x))
    files.sort(key=lambda x: (x.lower(), x))

    for d_name in dirs:
        full_path = os.path.join(dir_path, d_name)
        rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")
        d_dict = {
            "name": d_name,
            "path": rel_path,
            "type": "directory"
        }

        if max_depth is None or current_depth < max_depth:
            d_dict["children"] = build_tree(
                full_path,
                current_depth + 1,
                max_depth,
                root_dir,
                ignore_dirs,
                ignore_files
            )

        items.append(d_dict)

    for f_name in files:
        full_path = os.path.join(dir_path, f_name)
        rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")
        items.append({
            "name": f_name,
            "path": rel_path,
            "type": "file"
        })

    return items


def generate_markdown(items, depth=0):
    lines = []

    for item in items:
        indent = "  " * depth

        if item["type"] == "directory":
            lines.append(f"{indent}- 📁 **{item['name']}/**")
            if "children" in item:
                lines.extend(generate_markdown(item["children"], depth + 1))
        else:
            lines.append(f"{indent}- 📄 {item['name']}")

    return lines


def write_text(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    root_dir = get_root_dir()
    computer_name = os.environ.get("COMPUTERNAME", socket.gethostname())
    root_folder_name = os.path.basename(root_dir)

    skill_folder_name = "luxdev-python-index"
    builder_folder_name = f"{computer_name}-{root_folder_name}-index-build"
    builder_skill_name = f"{computer_name}-{root_folder_name}-index-build".lower()

    index_dir = os.path.join(root_dir, ".eb")
    src_dir = os.path.join(root_dir, ".eb")
    skills_dir = os.path.join(root_dir, "skills")
    
    master_skill_dir = os.path.join(skills_dir, skill_folder_name)
    builder_skill_dir = os.path.join(skills_dir, builder_folder_name)

    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(skills_dir, exist_ok=True)
    os.makedirs(master_skill_dir, exist_ok=True)
    os.makedirs(builder_skill_dir, exist_ok=True)

    ignore_dirs = {
        ".git",
        "node_modules",
        "__pycache__",
        "venv",
        ".venv",
        ".eb"
    }

    ignore_files = {
        "index.md",
        "index-all.md",
        "manifest.json",
        "manifest-all.json"
    }

    root_manifest_path = os.path.join(src_dir, "manifest.json")
    root_index_md_path = os.path.join(src_dir, "index.md")
    all_manifest_path = os.path.join(src_dir, "manifest-all.json")
    all_index_md_path = os.path.join(src_dir, "index-all.md")
    readme_path = os.path.join(src_dir, "INDEX_README.md")
    master_skill_path = os.path.join(master_skill_dir, "SKILL.md")
    builder_skill_path = os.path.join(builder_skill_dir, "SKILL.md")

    print("Generating 4-layer manifest and index...")
    manifest_data = build_tree(root_dir, 1, 4, root_dir, ignore_dirs, ignore_files)
    markdown_lines = generate_markdown(manifest_data)

    write_json(root_manifest_path, manifest_data)
    write_text(
        root_index_md_path,
        f"# Directory Index (4 Layers)\n\n- 📁 **{root_folder_name}/**\n"
        + ("\n".join("  " + line for line in markdown_lines) + "\n" if markdown_lines else "")
    )

    print("Generating all-layer manifest and index...")
    manifest_all_data = build_tree(root_dir, 1, None, root_dir, ignore_dirs, ignore_files)
    markdown_all_lines = generate_markdown(manifest_all_data)

    write_json(all_manifest_path, manifest_all_data)
    write_text(
        all_index_md_path,
        f"# Directory Index (All Layers)\n\n- 📁 **{root_folder_name}/**\n"
        + ("\n".join("  " + line for line in markdown_all_lines) + "\n" if markdown_all_lines else "")
    )

    print("Writing luxdev-python-index skill...")
    master_skill_content = """---
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
"""
    write_text(master_skill_path, master_skill_content)

    print("Writing workspace-specific build skill...")
    builder_skill_content = f"""---
name: {builder_skill_name}
description: Workspace-specific shortcut for navigating and rebuilding indexes for {root_folder_name} on {computer_name}.
---

# {computer_name}-{root_folder_name}-index-build

This skill is the workspace-specific shortcut for this indexed root.

## Workspace identity

- Machine: `{computer_name}`
- Root folder: `{root_folder_name}`

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
"""
    write_text(builder_skill_path, builder_skill_content)

    print("Writing README.md...")
    readme_content = """# Goal

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
"""
    write_text(readme_path, readme_content)

    print("Relocating script into src if needed...")
    target_script_path = os.path.join(src_dir, "index.py")
    current_script_path = os.path.abspath(__file__)

    if os.path.abspath(current_script_path) != os.path.abspath(target_script_path):
        try:
            shutil.copy2(current_script_path, target_script_path)
            try:
                os.remove(current_script_path)
            except Exception:
                print("Note: Could not remove the original executing script path.")
        except Exception as e:
            print(f"Warning: Could not relocate script: {e}")

    print("Done.")


if __name__ == "__main__":
    main()