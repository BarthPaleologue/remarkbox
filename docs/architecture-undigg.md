# Operation Undigg — Architecture

Document-first platform: every namespace is a book, every thread is a chapter,
every reply is a section. Pandoc renders 67 output formats.

## Data Flow — Write Path

```dot
digraph write_path {
    rankdir=LR
    node [shape=box, style=rounded, fontname="sans-serif"]
    edge [fontname="sans-serif", fontsize=10]

    input [label="User Input\n(md, html, rst,\nmediawiki, latex,\ntextile, org, ...)", shape=note]
    source_fmt [label="source_format\ndetection", shape=diamond]
    pandoc_html [label="pandoc\nconvert to html5"]
    pandoc_roundtrip [label="pandoc\nhtml → markdown\n(round-trip clean)"]
    bleach [label="bleach\nsanitize"]
    data [label="Node.data\n(raw source)", shape=cylinder]
    data_html [label="Node.data_html\n(rendered)", shape=cylinder]
    source_col [label="Node.source_format", shape=cylinder]

    input -> source_fmt
    source_fmt -> pandoc_html [label="rst, mediawiki,\nlatex, etc."]
    source_fmt -> pandoc_roundtrip [label="html input"]
    source_fmt -> data [label="markdown\n(direct)"]
    pandoc_roundtrip -> data [label="cleaned md"]
    pandoc_html -> bleach
    bleach -> data_html
    input -> source_col [style=dashed, label="store format"]
    data -> data_html [label="markdown_to_html\n(for md input)", style=dashed]
}
```

## Data Flow — Read / Export Path

```dot
digraph read_path {
    rankdir=LR
    node [shape=box, style=rounded, fontname="sans-serif"]
    edge [fontname="sans-serif", fontsize=10]

    tree [label="Node tree\n(adjacency list)", shape=cylinder]
    renderer [label="tree-to-markdown\nrenderer"]
    pandoc [label="pandoc\nconvert to\ntarget format"]
    output [label="Output\n(pdf, epub, docx,\nhtml, rst, ...)", shape=note]

    tree -> renderer
    renderer -> pandoc [label="markdown\ndocument"]
    pandoc -> output

    subgraph cluster_heading_map {
        label="Heading depth mapping"
        style=dashed
        fontname="sans-serif"
        h1 [label="# Thread Title (h1)", shape=plaintext]
        h2 [label="## Author Name (h2, reply)", shape=plaintext]
        h3 [label="### Author Name (h3, nested)", shape=plaintext]
    }
}
```

## Export Hierarchy

```dot
digraph export_hierarchy {
    rankdir=TB
    node [shape=box, style=rounded, fontname="sans-serif"]
    edge [fontname="sans-serif", fontsize=10]

    ns [label="Namespace (book)\n/export/namespace/{name}.{fmt}"]
    rootA [label="Root Node A (chapter)\n/export/threads/{id}.{fmt}"]
    rootB [label="Root Node B (chapter)\n/export/threads/{id}.{fmt}"]
    reply1 [label="Reply 1 (section)\n/export/nodes/{id}.{fmt}"]
    reply2 [label="Reply 2 (section)\n/export/nodes/{id}.{fmt}"]
    reply1_1 [label="Reply 1.1 (subsection)\n/export/nodes/{id}.{fmt}"]

    ns -> rootA [label="default"]
    ns -> rootB [label="default"]
    rootA -> reply1 [label="on-demand"]
    rootA -> reply2 [label="on-demand"]
    reply1 -> reply1_1 [label="on-demand"]
}
```

67 output formats including: markdown, html5, pdf, epub, docx, odt, rst,
latex, mediawiki, man, plain, rtf, asciidoc, textile, org, json, and more.

## Wiki Mode

```dot
digraph wiki_mode {
    rankdir=TB
    node [shape=record, fontname="sans-serif"]
    edge [fontname="sans-serif", fontsize=10]

    rb_node [label="{rb_node|id\ldata\ldata_html\lsource_format\l}"]
    rb_revision [label="{rb_revision|id\lnode_id (FK)\luser_id (FK)\ldata\lsource_format\lrevision_number\lcreated\l}"]
    wiki_edit [label="wiki_edit()", shape=ellipse]
    check [label="can_wiki_edit(node, user)?", shape=diamond]

    rb_node -> wiki_edit [label="called on node"]
    wiki_edit -> rb_revision [label="1. snapshot\ncurrent data"]
    wiki_edit -> rb_node [label="3. overwrite\nwith new content", style=dashed]

    check -> wiki_edit [label="allowed"]

    subgraph cluster_perms {
        label="Permission checks"
        style=dashed
        fontname="sans-serif"
        node [shape=plaintext]
        p1 [label="user.authenticated → required"]
        p2 [label="namespace.can_alter_node() → owner/moderator always yes"]
        p3 [label="namespace.wiki && node.is_root → wiki mode for root nodes"]
    }

    check -> p1 [style=invis]
}
```

## Auto-Generated Themes

```dot
digraph themes {
    rankdir=TB
    node [shape=box, style=rounded, fontname="sans-serif"]
    edge [fontname="sans-serif", fontsize=10]

    name [label="namespace_name", shape=plaintext]
    sha [label="SHA-256 hash"]
    hue [label="hue (0-360)\nbits[0:8]"]
    seeds [label="8 seed values\nbits[8:40]"]
    palette [label="HSL color palette"]

    light [label="Light mode\n:root, .theme-light\n--rb-bg, --rb-text,\n--rb-link, --rb-accent,\n--rb-border, ...", shape=note]
    dark [label="Dark mode\n@media prefers-color-scheme: dark\n.theme-dark\n--rb-bg, --rb-text,\n--rb-link, --rb-accent,\n--rb-border, ...", shape=note]

    css [label="GET /api/v1/themes/{ns}/css\n(1-day cache)", shape=component]
    preview [label="GET /api/v1/themes/{ns}/preview\n(JSON palette)", shape=component]

    name -> sha
    sha -> hue
    sha -> seeds
    hue -> palette
    seeds -> palette
    palette -> light
    palette -> dark
    light -> css
    dark -> css
    palette -> preview
}
```

Deterministic: same namespace name always produces the same theme.

## Module Map

```dot
digraph modules {
    rankdir=TB
    node [shape=box, fontname="monospace", fontsize=10]
    edge [fontname="sans-serif", fontsize=9]
    compound=true

    subgraph cluster_lib {
        label="remarkbox/lib/"
        style=rounded
        fontname="sans-serif"
        pandoc_py [label="pandoc.py\nsubprocess wrapper\ntree renderer"]
        theme_gen [label="theme_generator.py\ndeterministic CSS"]
    }

    subgraph cluster_api {
        label="remarkbox/api/"
        style=rounded
        fontname="sans-serif"
        export_py [label="export.py\n/export/ endpoints"]
        wiki_py [label="wiki.py\n/wiki-edit, /revisions"]
        themes_py [label="themes.py\n/themes/ endpoints"]
        views_py [label="views.py\nsource_format on\ncreate/reply/edit"]
        serial_py [label="serializers.py\nsource_format in JSON"]
    }

    subgraph cluster_models {
        label="remarkbox/models/"
        style=rounded
        fontname="sans-serif"
        node_py [label="node.py\nsource_format column\nset_data(), wiki_edit()"]
        ns_py [label="namespace.py\ncan_wiki_edit()"]
        rev_py [label="revision.py\nRevision model"]
    }

    subgraph cluster_migrations {
        label="remarkbox/scripts/alembic/versions/"
        style=rounded
        fontname="sans-serif"
        mig1 [label="d47dc908d2ea\nadd source_format"]
        mig2 [label="8e3c406e4049\ncreate rb_revision"]
    }

    export_py -> pandoc_py
    themes_py -> theme_gen
    wiki_py -> rev_py
    wiki_py -> node_py
    views_py -> node_py
    export_py -> node_py
    export_py -> ns_py
    node_py -> pandoc_py [style=dashed, label="non-md formats"]
    mig1 -> node_py [style=dotted]
    mig2 -> rev_py [style=dotted]
}
```
