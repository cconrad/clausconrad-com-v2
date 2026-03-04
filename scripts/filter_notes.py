#!/usr/bin/env python3
"""Filter and copy published Obsidian notes to a Quartz content directory."""

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

import yaml


def parse_frontmatter(content: str) -> tuple[Optional[dict], str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_after_closing_dashes) or (None, content).
    Body is everything after the closing '---', including the leading newline.
    """
    if not content.startswith("---\n") and not content.startswith("---\r\n"):
        return None, content

    # Skip the opening "---\n"
    rest = content[4:]
    end_idx = rest.find("\n---")
    if end_idx == -1:
        return None, content

    fm_text = rest[:end_idx]
    # body starts after the "\n---" marker
    body = rest[end_idx + 4:]

    try:
        fm = yaml.safe_load(fm_text)
        if not isinstance(fm, dict):
            return None, content
        return fm, body
    except yaml.YAMLError:
        return None, content


def inject_publish(content: str, title: str | None = None) -> str:
    """Inject ``publish: true`` (and optionally ``title``) into existing YAML frontmatter.

    If 'publish' already exists it is overwritten.  When *title* is provided,
    it is written as the ``title`` key (unless there is an existing value).
    Returns content unchanged if there is no valid frontmatter.
    """
    fm, body = parse_frontmatter(content)
    if fm is None:
        return content

    fm["publish"] = True
    if title and not fm.get("title"):
        fm["title"] = title
    new_fm = yaml.dump(
        fm, allow_unicode=True, default_flow_style=False, sort_keys=False
    ).strip()
    return f"---\n{new_fm}\n---{body}"


def find_asset_references(content: str, source_assets_dir: Path) -> set[Path]:
    """Find asset references in *content* that resolve to real files.

    Handles two syntaxes:
    * ``![alt text](assets/path/to/file.ext)`` — standard Markdown image
    * ``![[filename.ext]]`` or ``![[filename.ext|width]]`` — Obsidian embed

    Only paths that actually exist under *source_assets_dir* are returned.
    Returns a set of :class:`Path` objects relative to *source_assets_dir*.
    """
    found: set[Path] = set()

    # Standard Markdown: ![alt](assets/relative/path.ext)
    for match in re.finditer(r"!\[.*?\]\(assets/([^)\s]+)\)", content):
        rel = match.group(1)
        candidate = source_assets_dir / rel
        if candidate.is_file():
            found.add(Path(rel))

    # Obsidian wikilink embed: ![[name.ext]] or ![[name.ext|display]]
    for match in re.finditer(r"!\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]", content):
        ref = match.group(1).strip()
        suffix = Path(ref).suffix.lower()
        # Skip if no extension or a Markdown file (it's an embedded note)
        if not suffix or suffix == ".md":
            continue

        # 1. Try exact path inside assets dir (supports ![[sub/file.png]])
        exact = source_assets_dir / ref
        if exact.is_file():
            found.add(Path(ref))
            continue

        # 2. Search recursively by filename (Obsidian stores by unique name)
        filename = Path(ref).name
        for hit in source_assets_dir.rglob(filename):
            if hit.is_file():
                found.add(hit.relative_to(source_assets_dir))
                break  # Use first match

    return found


def build_rename_mapping(source_dir: Path) -> dict[str, str]:
    """Build a case-insensitive mapping from original stem to output stem.

    Pass 1: scan all published ``.md`` files and determine output filenames.

    * If the note has a ``slug`` frontmatter key → new stem = slug value.
    * Otherwise → new stem = original filename stem lowercased.

    The returned dict uses lowercased stems as keys so that lookups from
    wikilinks (which are case-insensitive in Obsidian) work correctly.
    A warning is printed when two published notes would map to the same output
    stem.
    """
    mapping: dict[str, str] = {}  # lowercase_stem → new_stem
    reverse: dict[str, str] = {}  # new_stem → original key (for collision check)

    for md_file in sorted(source_dir.rglob("*.md")):
        rel_path = md_file.relative_to(source_dir)
        if rel_path.parts[0] == "assets":
            continue

        content = md_file.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)

        if fm is None or fm.get("published") is not True:
            continue

        original_stem = md_file.stem
        slug = fm.get("slug")
        new_stem = str(slug) if slug else original_stem.lower()
        key = original_stem.lower()

        if new_stem in reverse:
            print(
                f"Warning: output stem collision '{new_stem}': "
                f"'{reverse[new_stem]}' and '{key}' both map to the same filename."
            )
        mapping[key] = new_stem
        reverse[new_stem] = key

    return mapping


def rewrite_wikilinks(content: str, rename_mapping: dict[str, str]) -> str:
    """Rewrite wikilink targets in *content* using *rename_mapping*.

    Handles all four wikilink forms (with and without ``!`` prefix):

    * ``[[OldName]]`` → ``[[new-name]]``
    * ``[[OldName|Title]]`` → ``[[new-name|Title]]``
    * ``[[OldName#heading]]`` → ``[[new-name#heading]]``
    * ``[[OldName#heading|Title]]`` → ``[[new-name#heading|Title]]``

    Only rewrites when the link target (case-insensitive, without ``.md``
    extension) is present as a key in *rename_mapping*.  Asset embeds such as
    ``![[image.png]]`` are left untouched because non-markdown extensions will
    not appear in the mapping.
    """
    # Groups: (1) prefix ('[[' or '![['), (2) target, (3) heading, (4) title
    pattern = re.compile(
        r"(!?\[\[)([^\]|#\n]+?)(?:#([^\]|\n]*))?(?:\|([^\]\n]*))?\]\]"
    )

    def _replace(m: re.Match) -> str:
        prefix = m.group(1)
        target = m.group(2).strip()
        heading = m.group(3)  # None when absent
        title = m.group(4)    # None when absent

        # Strip .md suffix for the lookup
        target_stem = target[:-3] if target.lower().endswith(".md") else target
        new_stem = rename_mapping.get(target_stem.lower())
        if new_stem is None:
            # Check if this is an asset reference (has non-md file extension)
            has_ext = "." in target
            is_md = target.lower().endswith(".md")
            if has_ext and not is_md:
                # Asset reference (e.g., ![[image.png]]) — leave unchanged
                return m.group(0)
            # Dead link to unpublished/non-existing page — render as styled text
            display = title if title is not None else target_stem
            return f'<span class="dead-link">{display}</span>'

        result = prefix + new_stem
        if heading is not None:
            result += f"#{heading}"
        if title is not None:
            result += f"|{title}"
        elif target_stem != new_stem:
            # Auto-add the original name as display title when renaming
            result += f"|{target_stem}"
        result += "]]"
        return result

    return pattern.sub(_replace, content)


def filter_notes(source_dir: Path, dest_dir: Path) -> None:
    """Filter and copy published notes and their referenced assets."""
    notes_copied = 0
    notes_skipped = 0
    assets_copied = 0
    all_asset_refs: set[Path] = set()

    source_assets_dir = source_dir / "assets"

    # Pass 1: build the rename mapping for all published notes
    rename_mapping = build_rename_mapping(source_dir)

    # Pass 2: copy each published note with rewritten links and new filename
    for md_file in sorted(source_dir.rglob("*.md")):
        rel_path = md_file.relative_to(source_dir)

        # Skip anything inside the assets/ directory
        if rel_path.parts[0] == "assets":
            continue

        content = md_file.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)

        if fm is None or fm.get("published") is not True:
            notes_skipped += 1
            continue

        # Determine output filename
        slug = fm.get("slug")
        new_stem = str(slug) if slug else md_file.stem.lower()
        new_filename = new_stem + ".md"

        # Inject publish flag (+ title from filename) then rewrite wikilinks
        out_content = rewrite_wikilinks(
            inject_publish(content, title=md_file.stem), rename_mapping
        )

        dest_file = dest_dir / rel_path.parent / new_filename
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(out_content, encoding="utf-8")
        notes_copied += 1

        # Collect asset references from the *original* content
        if source_assets_dir.is_dir():
            all_asset_refs.update(find_asset_references(content, source_assets_dir))

    # Copy referenced assets
    dest_assets_dir = dest_dir / "assets"
    for asset_rel in all_asset_refs:
        src = source_assets_dir / asset_rel
        dst = dest_assets_dir / asset_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        assets_copied += 1

    print(
        f"Done: {notes_copied} notes copied, "
        f"{assets_copied} assets copied, "
        f"{notes_skipped} notes skipped."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy published Obsidian notes to a Quartz content directory."
    )
    parser.add_argument("source_dir", type=Path, help="Source Obsidian vault directory")
    parser.add_argument(
        "dest_dir", type=Path, help="Destination Quartz content directory"
    )
    args = parser.parse_args()

    if not args.source_dir.is_dir():
        print(
            f"Error: source_dir '{args.source_dir}' is not a directory",
            file=sys.stderr,
        )
        sys.exit(1)

    filter_notes(args.source_dir, args.dest_dir)


if __name__ == "__main__":
    main()

