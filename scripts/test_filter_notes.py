"""Tests for filter_notes.py"""

import sys
from pathlib import Path

# Allow running tests from repo root via `uv run -m pytest scripts/`
sys.path.insert(0, str(Path(__file__).parent))

from filter_notes import (
    build_rename_mapping,
    filter_notes,
    find_asset_references,
    inject_publish,
    parse_frontmatter,
    rewrite_wikilinks,
)

# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------

SAMPLE_FM = "---\npublished: true\nslug: truenas\n---\n# Body\n"


def test_parse_frontmatter_valid():
    fm, body = parse_frontmatter(SAMPLE_FM)
    assert fm == {"published": True, "slug": "truenas"}
    assert body == "\n# Body\n"


def test_parse_frontmatter_no_frontmatter():
    content = "# Just a heading"
    fm, body = parse_frontmatter(content)
    assert fm is None
    assert body == content


def test_parse_frontmatter_published_false():
    content = "---\npublished: false\n---\nbody"
    fm, _ = parse_frontmatter(content)
    assert fm is not None
    assert fm.get("published") is False


def test_parse_frontmatter_missing_published_key():
    content = "---\nslug: test\n---\nbody"
    fm, _ = parse_frontmatter(content)
    assert fm is not None
    assert "published" not in fm


def test_parse_frontmatter_invalid_yaml():
    content = "---\n: bad: yaml: [\n---\nbody"
    fm, body = parse_frontmatter(content)
    assert fm is None
    assert body == content


def test_parse_frontmatter_non_dict_yaml():
    # A YAML scalar at the top level (not a mapping)
    content = "---\n- item1\n- item2\n---\nbody"
    fm, body = parse_frontmatter(content)
    assert fm is None
    assert body == content


def test_parse_frontmatter_no_closing_dashes():
    content = "---\npublished: true\n"
    fm, body = parse_frontmatter(content)
    assert fm is None


# ---------------------------------------------------------------------------
# inject_publish
# ---------------------------------------------------------------------------


def test_inject_publish_adds_key():
    content = "---\npublished: true\nslug: test\n---\n# Body"
    result = inject_publish(content)
    fm, body = parse_frontmatter(result)
    assert fm is not None
    assert fm["publish"] is True
    assert fm["published"] is True
    assert "# Body" in result


def test_inject_publish_with_title():
    content = "---\npublished: true\n---\nbody"
    result = inject_publish(content, title="My Note")
    fm, _ = parse_frontmatter(result)
    assert fm is not None
    assert fm["title"] == "My Note"
    assert fm["publish"] is True


def test_inject_publish_title_none_does_not_inject():
    content = "---\npublished: true\n---\nbody"
    result = inject_publish(content, title=None)
    fm, _ = parse_frontmatter(result)
    assert fm is not None
    assert "title" not in fm


def test_inject_publish_overwrites_existing():
    content = "---\npublished: true\npublish: false\n---\nbody"
    result = inject_publish(content)
    fm, _ = parse_frontmatter(result)
    assert fm["publish"] is True


def test_inject_publish_no_frontmatter():
    content = "# No frontmatter here"
    assert inject_publish(content) == content


def test_inject_publish_preserves_body():
    body = "\n\nSome *markdown* body.\n\n> blockquote\n"
    content = f"---\npublished: true\n---{body}"
    result = inject_publish(content)
    assert result.endswith(body)


# ---------------------------------------------------------------------------
# find_asset_references
# ---------------------------------------------------------------------------


def test_find_asset_references_markdown_image(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "photo.png").write_bytes(b"x")

    refs = find_asset_references("![alt](assets/photo.png)", assets)
    assert Path("photo.png") in refs


def test_find_asset_references_markdown_subdir(tmp_path):
    assets = tmp_path / "assets"
    (assets / "sub").mkdir(parents=True)
    (assets / "sub" / "img.jpg").write_bytes(b"x")

    refs = find_asset_references("![](assets/sub/img.jpg)", assets)
    assert Path("sub/img.jpg") in refs


def test_find_asset_references_obsidian_embed(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "screenshot.png").write_bytes(b"x")

    refs = find_asset_references("![[screenshot.png]]", assets)
    assert Path("screenshot.png") in refs


def test_find_asset_references_obsidian_with_pipe(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "diagram.svg").write_bytes(b"x")

    refs = find_asset_references("![[diagram.svg|300]]", assets)
    assert Path("diagram.svg") in refs


def test_find_asset_references_ignores_note_embeds(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()

    # No extension → treated as embedded note, must be ignored
    refs = find_asset_references("![[Some Note]]", assets)
    assert len(refs) == 0


def test_find_asset_references_ignores_md_embeds(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "note.md").write_text("# hi")

    refs = find_asset_references("![[note.md]]", assets)
    assert len(refs) == 0


def test_find_asset_references_nonexistent_file(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()

    refs = find_asset_references("![](assets/ghost.png)", assets)
    assert len(refs) == 0


def test_find_asset_references_obsidian_recursive(tmp_path):
    """Obsidian embed resolved recursively when stored in a subdir."""
    assets = tmp_path / "assets"
    (assets / "deep").mkdir(parents=True)
    (assets / "deep" / "image.png").write_bytes(b"x")

    refs = find_asset_references("![[image.png]]", assets)
    assert Path("deep/image.png") in refs


# ---------------------------------------------------------------------------
# filter_notes (integration)
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path):
    """Helper to create a small test vault."""
    source = tmp_path / "source"
    source.mkdir()
    assets = source / "assets"
    assets.mkdir()
    return source, assets


def test_filter_notes_copies_published(tmp_path):
    source, assets = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (source / "pub.md").write_text(
        "---\npublished: true\nslug: pub\n---\n# Published"
    )
    (source / "skip.md").write_text("---\npublished: false\n---\n# Skip")
    (source / "bare.md").write_text("# No frontmatter")

    filter_notes(source, dest)

    assert (dest / "pub.md").exists()
    assert not (dest / "skip.md").exists()
    assert not (dest / "bare.md").exists()


def test_filter_notes_injects_publish_true(tmp_path):
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (source / "note.md").write_text("---\npublished: true\n---\nbody")
    filter_notes(source, dest)

    fm, _ = parse_frontmatter((dest / "note.md").read_text())
    assert fm is not None
    assert fm["publish"] is True


def test_filter_notes_copies_referenced_assets(tmp_path):
    source, assets = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (assets / "img.png").write_bytes(b"image data")
    (assets / "unused.png").write_bytes(b"not referenced")
    (source / "note.md").write_text(
        "---\npublished: true\n---\n![pic](assets/img.png)"
    )

    filter_notes(source, dest)

    assert (dest / "assets" / "img.png").exists()
    assert not (dest / "assets" / "unused.png").exists()


def test_filter_notes_copies_obsidian_embed_assets(tmp_path):
    source, assets = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (assets / "chart.svg").write_bytes(b"<svg/>")
    (source / "note.md").write_text(
        "---\npublished: true\n---\n![[chart.svg]]"
    )

    filter_notes(source, dest)

    assert (dest / "assets" / "chart.svg").exists()


def test_filter_notes_skips_unpublished_missing_key(tmp_path):
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (source / "no_key.md").write_text("---\nslug: test\n---\nbody")
    filter_notes(source, dest)

    assert not (dest / "no_key.md").exists()


def test_filter_notes_preserves_subdirectory_structure(tmp_path):
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    sub = source / "subdir"
    sub.mkdir()
    (sub / "deep.md").write_text("---\npublished: true\n---\nbody")

    filter_notes(source, dest)

    assert (dest / "subdir" / "deep.md").exists()


def test_filter_notes_prints_summary(tmp_path, capsys):
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (source / "a.md").write_text("---\npublished: true\n---\nbody")
    (source / "b.md").write_text("---\npublished: false\n---\nbody")

    filter_notes(source, dest)

    captured = capsys.readouterr()
    assert "1 notes copied" in captured.out
    assert "1 notes skipped" in captured.out


# ---------------------------------------------------------------------------
# build_rename_mapping
# ---------------------------------------------------------------------------


def test_build_rename_mapping_slug(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "TrueNAS.md").write_text("---\npublished: true\nslug: truenas\n---\nbody")

    mapping = build_rename_mapping(source)
    assert mapping["truenas"] == "truenas"


def test_build_rename_mapping_lowercase_fallback(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "TrueNAS.md").write_text("---\npublished: true\n---\nbody")

    mapping = build_rename_mapping(source)
    assert mapping["truenas"] == "truenas"


def test_build_rename_mapping_only_published(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "Pub.md").write_text("---\npublished: true\nslug: published-note\n---\nbody")
    (source / "Draft.md").write_text("---\npublished: false\n---\nbody")
    (source / "Bare.md").write_text("# No frontmatter")

    mapping = build_rename_mapping(source)
    assert "pub" in mapping
    assert "draft" not in mapping
    assert "bare" not in mapping


def test_build_rename_mapping_collision_warning(tmp_path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.md").write_text("---\npublished: true\nslug: same\n---\nbody")
    (source / "b.md").write_text("---\npublished: true\nslug: same\n---\nbody")

    build_rename_mapping(source)
    captured = capsys.readouterr()
    assert "Warning" in captured.out
    assert "same" in captured.out


def test_build_rename_mapping_case_insensitive_key(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "Jamstack.md").write_text("---\npublished: true\n---\nbody")

    mapping = build_rename_mapping(source)
    # Key is always lowercased
    assert "jamstack" in mapping
    assert mapping["jamstack"] == "jamstack"


# ---------------------------------------------------------------------------
# rewrite_wikilinks
# ---------------------------------------------------------------------------


def test_rewrite_wikilinks_basic():
    mapping = {"oldname": "new-name"}
    result = rewrite_wikilinks("See [[OldName]] for details.", mapping)
    assert result == "See [[new-name|OldName]] for details."


def test_rewrite_wikilinks_with_title():
    mapping = {"oldname": "new-name"}
    result = rewrite_wikilinks("[[OldName|Display Title]]", mapping)
    assert result == "[[new-name|Display Title]]"


def test_rewrite_wikilinks_with_anchor():
    mapping = {"oldname": "new-name"}
    result = rewrite_wikilinks("[[OldName#section-heading]]", mapping)
    assert result == "[[new-name#section-heading|OldName]]"


def test_rewrite_wikilinks_with_anchor_and_title():
    mapping = {"oldname": "new-name"}
    result = rewrite_wikilinks("[[OldName#heading|My Title]]", mapping)
    assert result == "[[new-name#heading|My Title]]"


def test_rewrite_wikilinks_note_embed():
    mapping = {"oldname": "new-name"}
    result = rewrite_wikilinks("![[OldName]]", mapping)
    assert result == "![[new-name|OldName]]"


def test_rewrite_wikilinks_asset_embed_unchanged():
    """Asset embeds like ![[image.png]] should not be rewritten."""
    mapping = {"image": "image"}  # even if stem matches, extension present
    result = rewrite_wikilinks("![[image.png]]", mapping)
    # image.png has an extension; the lookup key would be "image.png" lowered,
    # which is NOT in the mapping (mapping keys are stems without .png)
    assert result == "![[image.png]]"


def test_rewrite_wikilinks_case_insensitive():
    mapping = {"truenas": "truenas"}
    result = rewrite_wikilinks("[[TrueNAS]]", mapping)
    # target_stem "TrueNAS" differs from new_stem "truenas" → auto-title added
    assert result == "[[truenas|TrueNAS]]"


def test_rewrite_wikilinks_no_title_when_stem_unchanged():
    """When the stem is already correct (same case), no auto-title is added."""
    mapping = {"truenas": "truenas"}
    result = rewrite_wikilinks("[[truenas]]", mapping)
    assert result == "[[truenas]]"


def test_rewrite_wikilinks_auto_title_with_anchor():
    mapping = {"truenas": "truenas"}
    result = rewrite_wikilinks("[[TrueNAS#setup]]", mapping)
    assert result == "[[truenas#setup|TrueNAS]]"


def test_rewrite_wikilinks_existing_title_with_anchor_preserved():
    mapping = {"truenas": "truenas"}
    result = rewrite_wikilinks("[[TrueNAS#setup|Guide]]", mapping)
    assert result == "[[truenas#setup|Guide]]"


def test_rewrite_wikilinks_embed_auto_title():
    mapping = {"truenas": "truenas"}
    result = rewrite_wikilinks("![[TrueNAS]]", mapping)
    assert result == "![[truenas|TrueNAS]]"


def test_rewrite_wikilinks_unknown_link_unchanged():
    mapping = {"known": "known-note"}
    result = rewrite_wikilinks("[[Unknown]]", mapping)
    assert result == '<span class="dead-link">Unknown</span>'


def test_rewrite_wikilinks_preserves_other_content():
    mapping = {"a": "alpha"}
    content = "Before [[A]] middle [[Unknown]] after."
    result = rewrite_wikilinks(content, mapping)
    assert result == 'Before [[alpha|A]] middle <span class="dead-link">Unknown</span> after.'


# ---------------------------------------------------------------------------
# filter_notes — slug and link-rewriting integration
# ---------------------------------------------------------------------------


def test_filter_notes_slug_renames_output(tmp_path):
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (source / "TrueNAS.md").write_text("---\npublished: true\nslug: truenas\n---\nbody")
    filter_notes(source, dest)

    # Verify by listing actual filenames (case-insensitive FS safe)
    names = [p.name for p in dest.iterdir()]
    assert "truenas.md" in names
    assert "TrueNAS.md" not in names


def test_filter_notes_lowercase_fallback(tmp_path):
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (source / "Jamstack.md").write_text("---\npublished: true\n---\nbody")
    filter_notes(source, dest)

    names = [p.name for p in dest.iterdir()]
    assert "jamstack.md" in names
    assert "Jamstack.md" not in names


def test_filter_notes_subdirectory_slug(tmp_path):
    """Slug replaces only the filename, not the directory path."""
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    sub = source / "subdir"
    sub.mkdir()
    (sub / "MyNote.md").write_text("---\npublished: true\nslug: my-note\n---\nbody")
    filter_notes(source, dest)

    assert (dest / "subdir" / "my-note.md").exists()


def test_filter_notes_rewrites_wikilinks(tmp_path):
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (source / "Home.md").write_text(
        "---\npublished: true\n---\nSee [[TrueNAS]] for storage."
    )
    (source / "TrueNAS.md").write_text(
        "---\npublished: true\nslug: truenas\n---\nbody"
    )
    filter_notes(source, dest)

    home_content = (dest / "home.md").read_text()
    # auto-title injected because "TrueNAS" != "truenas"
    assert "[[truenas|TrueNAS]]" in home_content
    assert "[[TrueNAS]]" not in home_content


def test_filter_notes_injects_title_from_filename(tmp_path):
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (source / "TrueNAS.md").write_text("---\npublished: true\nslug: truenas\n---\nbody")
    filter_notes(source, dest)

    fm, _ = parse_frontmatter((dest / "truenas.md").read_text())
    assert fm is not None
    assert fm["title"] == "TrueNAS"


def test_filter_notes_no_rewrite_for_unpublished_links(tmp_path):
    source, _ = _make_vault(tmp_path)
    dest = tmp_path / "dest"

    (source / "note.md").write_text(
        "---\npublished: true\n---\nSee [[Draft]] here."
    )
    (source / "Draft.md").write_text("---\npublished: false\n---\nbody")
    filter_notes(source, dest)

    note_content = (dest / "note.md").read_text()
    assert '<span class="dead-link">Draft</span>' in note_content


def test_rewrite_wikilinks_dead_link_basic():
    mapping = {"known": "known"}
    result = rewrite_wikilinks("See [[Unpublished]] for details", mapping)
    assert result == 'See <span class="dead-link">Unpublished</span> for details'


def test_rewrite_wikilinks_dead_link_with_title():
    mapping = {"known": "known"}
    result = rewrite_wikilinks("See [[Unpublished|Custom Title]]", mapping)
    assert result == 'See <span class="dead-link">Custom Title</span>'


def test_rewrite_wikilinks_dead_link_with_anchor():
    mapping = {"known": "known"}
    result = rewrite_wikilinks("See [[Unpublished#heading]]", mapping)
    assert result == 'See <span class="dead-link">Unpublished</span>'


def test_rewrite_wikilinks_dead_link_asset_embed_unchanged():
    mapping = {"known": "known"}
    result = rewrite_wikilinks("![[image.png]]", mapping)
    assert result == "![[image.png]]"


def test_rewrite_wikilinks_dead_link_note_embed():
    mapping = {"known": "known"}
    result = rewrite_wikilinks("![[Unpublished]]", mapping)
    assert result == '<span class="dead-link">Unpublished</span>'
