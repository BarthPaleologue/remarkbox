# Operation Undigg — Architecture

Document-first platform: every namespace is a book, every thread is a chapter,
every reply is a section. Pandoc renders 67 output formats.

## Data Flow

```
                          ┌─────────────────────────────────────────────┐
                          │              Write Path                     │
                          │                                             │
  User Input              │  source_format     pandoc         bleach    │
  (md/html/rst/           │  ─────────────►  convert to  ──► sanitize  │
   mediawiki/latex/       │                   html5          pipeline   │
   textile/org/...)       │                     │                │      │
                          │                     │                ▼      │
                          │                     │           data_html   │
                          │                     │          (rendered)   │
                          │                     │                       │
                          │  html input:        │                       │
                          │  pandoc html→md     │                       │
                          │  (round-trip clean) │                       │
                          │         │           │                       │
                          │         ▼           │                       │
                          │     data (raw)      │                       │
                          │   + source_format   │                       │
                          └─────────────────────────────────────────────┘

                          ┌─────────────────────────────────────────────┐
                          │              Read / Export Path              │
                          │                                             │
  Node tree               │  tree-to-markdown    pandoc                 │
  (adjacency list)  ────► │  renderer         ──► convert to  ────►  output
                          │                      target format          │
                          │                                             │
                          │  Hierarchy:                                 │
                          │    # Thread Title     (h1)                  │
                          │    ## Author Name     (h2, per reply)       │
                          │    ### Author Name    (h3, nested reply)    │
                          │    ...depth maps to heading level           │
                          └─────────────────────────────────────────────┘
```

## Export Hierarchy

```
  Namespace (book)
  GET /api/v1/export/namespace/{name}.{fmt}
  │
  ├── Root Node A (chapter)           ← default export
  │   GET /api/v1/export/threads/{id}.{fmt}
  │   │
  │   ├── Reply 1 (section)           ← on-demand
  │   │   GET /api/v1/export/nodes/{id}.{fmt}
  │   │   │
  │   │   └── Reply 1.1 (subsection)  ← on-demand
  │   │
  │   └── Reply 2 (section)           ← on-demand
  │
  └── Root Node B (chapter)           ← default export
      GET /api/v1/export/threads/{id}.{fmt}
```

**67 output formats** including: markdown, html5, pdf, epub, docx, odt, rst,
latex, mediawiki, man, plain, rtf, asciidoc, textile, org, json, and more.

## Wiki Mode

```
  ┌──────────────┐      wiki_edit()      ┌──────────────┐
  │              │  ──────────────────►  │  rb_revision  │
  │   rb_node    │                       │               │
  │              │  1. snapshot current   │  id           │
  │  id          │     data → revision   │  node_id (FK) │
  │  data        │  2. increment rev#    │  user_id (FK) │
  │  data_html   │  3. overwrite node    │  data          │
  │  source_fmt  │     with new content  │  source_format │
  │              │                       │  revision_number│
  └──────────────┘                       │  created       │
        │                                └──────────────┘
        │
        ▼
  can_wiki_edit(node, user)?
  ├── user.authenticated?           → required
  ├── namespace.can_alter_node()?   → owner/moderator always yes
  └── namespace.wiki && node.is_root? → wiki mode for root nodes
```

## Auto-Generated Themes

```
  namespace_name
       │
       ▼
  SHA-256 hash
       │
       ├── bits[0:8]   → hue (0-360)
       ├── bits[8:40]  → 8 seed values
       │
       ▼
  HSL color palette
       │
       ├── Light mode (:root, .theme-light)
       │   --rb-bg, --rb-text, --rb-link, --rb-accent, --rb-border, ...
       │
       └── Dark mode (@media prefers-color-scheme: dark, .theme-dark)
           --rb-bg, --rb-text, --rb-link, --rb-accent, --rb-border, ...

  Deterministic: same namespace → same theme, always.
  Served at: GET /api/v1/themes/{namespace}/css  (1-day cache)
  Preview:   GET /api/v1/themes/{namespace}/preview  (JSON palette)
```

## Module Map

```
  remarkbox/
  ├── lib/
  │   ├── pandoc.py              ← subprocess wrapper, tree renderer
  │   └── theme_generator.py     ← deterministic CSS from namespace name
  ├── api/
  │   ├── export.py              ← /export/ endpoints (namespace, thread, node)
  │   ├── wiki.py                ← /wiki-edit, /revisions endpoints
  │   ├── themes.py              ← /themes/ endpoints (css, preview)
  │   ├── views.py               ← modified: source_format on create/reply/edit
  │   └── serializers.py         ← modified: source_format in node JSON
  ├── models/
  │   ├── node.py                ← modified: source_format column, set_data(), wiki_edit()
  │   ├── namespace.py           ← modified: can_wiki_edit()
  │   └── revision.py            ← new: Revision model
  └── scripts/alembic/versions/
      ├── d47dc908d2ea_...       ← add source_format to rb_node
      └── 8e3c406e4049_...       ← create rb_revision table
```
