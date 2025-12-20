JavaScript Usage in Remarkbox
=============================

This document catalogs all JavaScript usage in the Remarkbox codebase.

Standalone JavaScript Files
---------------------------

remarkbox/static/js/custom.js
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Main application JavaScript containing core functionality.

**previewAjax()** (Lines 5-20)
    Debounced preview function with 800ms timer. Escapes HTML in raw mode
    to prevent XSS, then calls sendPreview().

**sendPreview()** (Lines 22-38)
    AJAX request to ``/preview-post`` endpoint for Markdown rendering.
    Optionally triggers MathJax re-rendering.

**toggle()** (Lines 41-57)
    CSS-based toggle animation. Adds/removes ``toggle-open`` and
    ``toggle-closing`` classes. Updates button text after 800ms animation.

**Details close animation** (Lines 60-75)
    Event listener for ``.preview-toggle`` clicks. Animates ``<details>``
    element closure over 800ms using ``closing`` class.

**Document ready handler** (Lines 77-103)
    - Binds vote-up/vote-down button click handlers
    - Fades in alert elements over 2 seconds
    - Highlights URL fragment targets with ``focused`` class

**sendVote()** (Lines 105-118)
    AJAX request to ``/vote-post`` endpoint. Updates vote count on success.

remarkbox/static/js/jquery-2.1.3.min.js
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

jQuery library for DOM manipulation and AJAX.

remarkbox/static/js/iframe-resizer/
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

External library for responsive iframe sizing in embed mode.

- ``iframeResizer.min.js`` - Main resizer script
- ``iframeResizer.contentWindow.min.js`` - Content window script


Inline JavaScript in Templates
------------------------------

Form Submission Protection
~~~~~~~~~~~~~~~~~~~~~~~~~~

Pattern: ``onsubmit="submit.disabled = true; return true;"``

Disables submit button to prevent double submission. Used in:

- ``snippets/forms.j2`` - Reply, edit, pay-what-you-can forms
- ``snippets/create.j2`` - Thread creation form
- ``snippets/snippets.j2`` - Watch, unwatch, lock, unlock, disable, enable, verify, approve, deny forms
- ``snippets/search.j2`` - Search form
- ``join-or-log-in.j2`` - Login form
- ``setup-namespace.j2`` - Namespace setup/cancel forms
- ``namespace-settings.j2`` - Settings forms
- ``user-settings.j2`` - User settings form
- ``user-watching.j2`` - Watching management form

Live Markdown Preview
~~~~~~~~~~~~~~~~~~~~~

Pattern: ``onkeyup="previewAjax(...)"``

Triggers debounced Markdown preview on textarea input.

**snippets/forms.j2** (Line 21)
    Reply textarea with raw preview::

        previewAjax('textarea-{{ node.id }}', 'preview-{{ node.id }}', show_raw=true, mathjax={{ request.mathjax }})

**snippets/forms.j2** (Line 63)
    Edit textarea without raw preview::

        previewAjax('edit-textarea-{{ node.id }}', 'node-data-{{ node.id }}', show_raw=false, mathjax={{ request.mathjax }})

**snippets/create.j2** (Line 14)
    Thread creation textarea::

        previewAjax('thread_data_textarea', 'preview', show_raw=true, mathjax={{ request.mathjax }})

Toggle Functionality
~~~~~~~~~~~~~~~~~~~~

**base.j2** (Line 38)
    Namespace switcher menu::

        onclick="toggle('my-namespaces-div', 'my-namespaces-link', '(switch)', '(switch)'); return false;"

**snippets/snippets.j2** (Line 88)
    Remark button - shows reply form and focuses textarea::

        onclick="toggle('remark-box-{{ node.id }}', 'remark-link-{{ node.id }}', 'remark', 'hide'); document.getElementById('textarea-{{ node.id }}').focus(); return false;"

**snippets/snippets.j2** (Line 103)
    Collapse button - hides/shows child nodes::

        onclick="toggle('node-children-{{ node.id }}', 'collapse-link-{{ node.id }}', 'expand [+]', 'collapse [-]');"

**snippets/snippets.j2** (Line 214)
    Edit button - shows edit form and focuses textarea::

        onclick="toggle('edit-box-{{ node.id }}', 'edit-link-{{ node.id }}', 'edit', 'hide'); document.getElementById('edit-textarea-{{ node.id }}').focus(); return false;"

Alert Dismissal
~~~~~~~~~~~~~~~

**snippets/flash-alerts.j2** (Line 4)
    Click to dismiss alert::

        onclick="this.style.display='none'"

Theme Preview
~~~~~~~~~~~~~

**user-settings.j2** (Lines 56-60)
    Radio buttons for theme mode::

        onchange="previewTheme(this.value)"

**user-settings.j2** (Lines 108-127)
    Theme preview function - applies ``dark-mode`` class to HTML element.


External Scripts
----------------

snippets/javascript-includes.j2
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**CSRF Token** (Line 6)
    Global variable for AJAX requests::

        var csrf_token = "{{ request.session.get_csrf_token() }}";

**Google Analytics v4** (Lines 12-18)
    Conditional loading based on namespace configuration.

**MathJax** (Lines 25-27)
    Mathematical formula rendering. Loaded from CDN when enabled.

embed-iframe.txt.j2
~~~~~~~~~~~~~~~~~~~

Embed script (Lines 8-42) that:

1. Captures parent page URL, title, and fragment
2. Creates Remarkbox iframe with configuration
3. Initializes iframe-resizer for responsive sizing

snippets/stripe.j2
~~~~~~~~~~~~~~~~~~

**Stripe v3** (Line 57)
    Payment processing library from ``https://js.stripe.com/v3/``

**Payment form handling** (Lines 83-132)
    Stripe card element initialization, validation, and token creation.

snippets/google-analytics.j2
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Legacy Universal Analytics (ga.js) for backward compatibility.


CSS Classes Managed by JavaScript
---------------------------------

- ``toggle-open`` - Element is visible with open animation
- ``toggle-closing`` - Element is animating closed
- ``closing`` - Details element is animating closed
- ``focused`` - URL fragment target highlighting
- ``dark-mode`` - Dark theme applied to HTML element


No-JavaScript Fallback
----------------------

Remarkbox functions without JavaScript:

- Toggle links have ``href`` attributes pointing to dedicated pages
  (e.g., ``/{node_id}/edit``, ``/{node_id}/reply``)
- Forms submit normally without AJAX
- ``<details>`` elements work natively for preview toggle
- Voting requires JavaScript (AJAX-only)
