# Functional Testing the Remarkbox API

Walkthrough for testing every endpoint with `curl`. Replace
`REMARKBOX` with your deploy URL (e.g. `https://my.remarkbox.com`).

## Read Endpoints

### List Threads

```bash
curl -s "$REMARKBOX/api/v1/threads?namespace=meta.remarkbox.com" | python3 -m json.tool
```

### Get Thread

```bash
# grab the first thread id from the list
THREAD_ID=$(curl -s "$REMARKBOX/api/v1/threads?namespace=meta.remarkbox.com" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['threads'][0]['id'])")

curl -s "$REMARKBOX/api/v1/threads/$THREAD_ID" | python3 -m json.tool
```

### Get Node

```bash
curl -s "$REMARKBOX/api/v1/nodes/$THREAD_ID" | python3 -m json.tool
```

## Anonymous Posting

Requires a namespace with **Allow Anonymous Comments** enabled.

### Create Thread

```bash
curl -s -X POST "$REMARKBOX/api/v1/threads" \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "meta.remarkbox.com",
    "title": "Test thread from curl",
    "data": "Hello from the API.",
    "anonymous_name": "CurlBot"
  }' | python3 -m json.tool
```

### Reply to Thread

```bash
curl -s -X POST "$REMARKBOX/api/v1/threads/$THREAD_ID/replies" \
  -H "Content-Type: application/json" \
  -d '{
    "data": "Reply from curl.",
    "anonymous_name": "CurlBot"
  }' | python3 -m json.tool
```

## Authentication (Email OTP)

### Request OTP

```bash
curl -s -X POST "$REMARKBOX/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com"}' | python3 -m json.tool
```

### Verify OTP

Check your inbox for the 6-digit code, then:

```bash
curl -s -X POST "$REMARKBOX/api/v1/auth/verify" \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{"email": "you@example.com", "otp": "123456"}' | python3 -m json.tool
```

The `-c cookies.txt` saves the session cookie for subsequent requests.

### Create Authenticated Thread

```bash
curl -s -X POST "$REMARKBOX/api/v1/threads" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "namespace": "meta.remarkbox.com",
    "title": "Authenticated thread",
    "data": "Posted with a verified session."
  }' | python3 -m json.tool
```

### Edit a Node

```bash
curl -s -X PATCH "$REMARKBOX/api/v1/nodes/$NODE_ID" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"data": "Updated content."}' | python3 -m json.tool
```

## Multi-Syntax Input

### Create Thread with RST

```bash
curl -s -X POST "$REMARKBOX/api/v1/threads" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "namespace": "meta.remarkbox.com",
    "title": "RST thread",
    "data": "Title\n=====\n\nA paragraph in **reStructuredText**.",
    "source_format": "rst"
  }' | python3 -m json.tool
```

### Reply with HTML

```bash
curl -s -X POST "$REMARKBOX/api/v1/threads/$THREAD_ID/replies" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "data": "<p>A reply in <strong>HTML</strong>.</p>",
    "source_format": "html"
  }' | python3 -m json.tool
```

## Export

### List Available Formats

```bash
curl -s "$REMARKBOX/api/v1/export/formats" | python3 -m json.tool
```

### Export Thread as Markdown

```bash
curl -s "$REMARKBOX/api/v1/export/threads/$THREAD_ID.md"
```

### Export Thread as PDF

```bash
curl -s "$REMARKBOX/api/v1/export/threads/$THREAD_ID.pdf" -o thread.pdf
```

### Export Thread as EPUB

```bash
curl -s "$REMARKBOX/api/v1/export/threads/$THREAD_ID.epub" -o thread.epub
```

### Export Namespace as Book

```bash
curl -s "$REMARKBOX/api/v1/export/namespace/meta.remarkbox.com.epub" -o meta.epub
curl -s "$REMARKBOX/api/v1/export/namespace/meta.remarkbox.com.pdf" -o meta.pdf
curl -s "$REMARKBOX/api/v1/export/namespace/meta.remarkbox.com.md"
```

### Export Node Subtree

```bash
curl -s "$REMARKBOX/api/v1/export/nodes/$NODE_ID.html"
```

## Wiki Mode

### Wiki Edit a Node

```bash
curl -s -X POST "$REMARKBOX/api/v1/nodes/$NODE_ID/wiki-edit" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"data": "Updated wiki content."}' | python3 -m json.tool
```

### Get Revision History

```bash
curl -s "$REMARKBOX/api/v1/nodes/$NODE_ID/revisions" | python3 -m json.tool
```

### Get Specific Revision

```bash
curl -s "$REMARKBOX/api/v1/revisions/$REVISION_ID" | python3 -m json.tool
```

## Themes

### Get Namespace Theme CSS

```bash
curl -s "$REMARKBOX/api/v1/themes/meta.remarkbox.com/css"
```

### Preview Theme Palette

```bash
curl -s "$REMARKBOX/api/v1/themes/meta.remarkbox.com/preview" | python3 -m json.tool
```

## Error Cases

### Missing namespace

```bash
curl -s "$REMARKBOX/api/v1/threads" | python3 -m json.tool
# {"error": "namespace parameter is required"}
```

### Namespace with API access disabled

```bash
curl -s "$REMARKBOX/api/v1/threads?namespace=opted-out.example.com"
# {"error": "API access is disabled for this namespace"}
```

### Edit without auth

```bash
curl -s -X PATCH "$REMARKBOX/api/v1/nodes/$NODE_ID" \
  -H "Content-Type: application/json" \
  -d '{"data": "nope"}'
# {"error": "Authentication required"}
```

## Python Client

Download the Python client directly from the API:

```bash
curl -s "$REMARKBOX/api/v1/clients/python" -o remarkbox_client.py
```

Or with wget:

```bash
wget -q "$REMARKBOX/api/v1/clients/python" -O remarkbox_client.py
```

Then use it:

```python
from remarkbox_client import RemarkboxClient

client = RemarkboxClient("https://my.remarkbox.com")
threads = client.list_threads("meta.remarkbox.com")
for t in threads["threads"]:
    print(t["title"])
```

See `remarkbox_client.py` header comments for full usage.
