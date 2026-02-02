# Thread URI: How Comments Are Tied to Page URLs

## How It Works

Remarkbox threads are keyed by the **page URL** (called the `thread_uri`).
When you embed Remarkbox on a page, the embed script automatically reads
`window.location.href` from the parent page and uses it as the thread
identifier. All comments posted on that page are stored under that URL.

This means:

- Each unique URL gets its own comment thread.
- If the same embed snippet appears on two different URLs, each page has
  its own independent thread.
- If you move the embed snippet to a different page (different URL), the
  new page will show an empty thread because the URL changed.

## "My Comments Disappeared After Moving the Embed"

This is the most common cause of "missing" comments. Your comments are not
deleted -- they are still stored under the original page URL. You can
confirm this by checking the Remarkbox dashboard, where all threads are
listed regardless of which page currently has the embed.

When you move the embed snippet from `https://example.com/old-page` to
`https://example.com/new-page`, Remarkbox sees `new-page` as a brand new
thread with no comments.

## How to Preserve Comments When Moving an Embed

Use the `thread_uri` parameter in your embed snippet to manually set the
thread identifier. This overrides the automatic URL detection.

### Standard Embed (automatic URL detection)

```html
<div id="remarkbox-div">
  <noscript disabled>
    <i>JavaScript is required to load the comments.</i>
  </noscript>
</div>
<script src="https://my.remarkbox.com/static/js/iframe-resizer/iframeResizer.min.js"></script>
<script>
  var defined_thread_uri = window.location.href;
  // ...
</script>
```

### Pinned Embed (manual thread_uri)

To keep the same comment thread even after moving the embed, set
`defined_thread_uri` to the original page URL:

```html
<script>
  // Pin this embed to the original page URL so comments follow the embed
  var defined_thread_uri = "https://example.com/old-page";
  // ...
</script>
```

With this change, no matter where you place the embed snippet, it will
always load and display the comments from `https://example.com/old-page`.

## When to Use Manual thread_uri

- **Moving content between URLs**: Pin `thread_uri` to the original URL.
- **Staging/production parity**: Use the production URL as `thread_uri`
  so comments don't split between environments.
- **URL canonicalization**: If your site is accessible at both `www.` and
  non-`www.` URLs, set a canonical `thread_uri` to avoid duplicate threads.
- **Single-page applications (SPAs)**: If your SPA changes the URL hash
  or query string without a full page load, pin `thread_uri` to the
  canonical path to avoid fragmenting comments.

## Related: Namespace Settings

The **Ignore Query String** setting in namespace settings can also help.
When enabled, Remarkbox strips query parameters from the URL before
matching threads. This prevents URLs like `?utm_source=twitter` from
creating separate threads.

## Summary

| Scenario | What Happens | Fix |
|----------|-------------|-----|
| Move embed to new URL | New empty thread appears | Set `thread_uri` to original URL |
| Same page, URL query changes | May create new thread | Enable "Ignore Query String" in namespace settings |
| Same page, URL fragment changes | Fragment is stripped automatically | No action needed |
| Different environments (staging/prod) | Separate threads per environment | Set `thread_uri` to canonical production URL |
