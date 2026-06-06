// post_preview
// previewTimer must live outside the functions.
var previewTimer = null;

function updatePreviewAuthor(previewDiv) {
    // Show the preview-author header and build the avatar via DOM API.
    // The avatar img is created dynamically (not in the template) because
    // browsers skip rendering images inside display:none containers.
    var author = previewDiv.querySelector('.preview-author');
    if (!author) return;

    var authorName = previewDiv.dataset.authorName;
    if (!authorName) return;

    // Show the header first.
    author.style.display = '';

    // Set author name.
    var strong = author.querySelector('.preview-anon-name');
    if (strong) {
        var form = previewDiv.closest('form');
        if (form && previewDiv.dataset.authorAnon) {
            var nameInput = form.querySelector('[name="anonymous_name"]');
            var name = (nameInput && nameInput.value.trim()) || 'Anonymous';
            strong.textContent = name;
        } else {
            strong.textContent = authorName;
        }
    }

    // Create avatar img once, via DOM API on visible parent.
    // Use class 'avatar' only (not 'nested-avatar') because the dynamic CSS
    // sets margin-left: -48px on nested-avatar to hang into .node padding,
    // which would push the image off-screen inside the preview container.
    if (previewDiv.dataset.avatarSrc && !author.querySelector('img.avatar')) {
        var size = parseInt(previewDiv.dataset.avatarSize) || 35;
        var gap = 10;
        var img = document.createElement('img');
        img.className = 'avatar';
        img.align = 'left';
        img.style.marginTop = '6px';
        img.style.marginRight = gap + 'px';
        img.width = size;
        img.height = size;
        img.src = previewDiv.dataset.avatarSrc;
        author.insertBefore(img, author.firstChild);
        // Indent author text and content so they stay to the right of the avatar.
        var indent = (size + gap) + 'px';
        author.style.paddingLeft = indent;
        img.style.marginLeft = '-' + indent;
        var contentDiv = previewDiv.querySelector('.preview-content');
        if (contentDiv) contentDiv.style.marginLeft = indent;
    }
}

function previewAjax(textarea, div, show_raw, mathjax) {
    // set div to raw textarea while waiting for remote Markdown rendering.
    if (show_raw) {
        // bust HTML tags like <script> to prevent running evil code.
        var el = document.getElementById(textarea);
        var busted_textarea = el.value.replace(/&/g, '&amp;').replace(/</g, '&lt;');
        var rawHtml = '<span class="preview-raw-markdown">' + busted_textarea + '</span>';
        var previewDiv = document.getElementById(div);
        var contentDiv = previewDiv.querySelector('.preview-content');
        if (contentDiv) {
            contentDiv.innerHTML = rawHtml;
            updatePreviewAuthor(previewDiv);
        } else {
            previewDiv.innerHTML = rawHtml;
        }
    }
    if (previewTimer) {
        clearTimeout(previewTimer);
    }
    previewTimer = setTimeout(
        function() { sendPreview(textarea, div, mathjax); },
        800
    );
}

function sendPreview(textarea, div, mathjax) {
    var url = '/preview-post';
    var ta = document.getElementById(textarea);
    var data = new FormData();
    data.append('data', ta.value);
    data.append('csrf_token', csrf_token);
    // textarea declares its source_format via data-source-format; the
    // endpoint dispatches to pandoc for rst/html/mediawiki/latex when set.
    var fmt = ta.dataset.sourceFormat;
    if (fmt) data.append('source_format', fmt);

    fetch(url, {
        method: 'POST',
        body: data,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function(response) { return response.text(); })
    .then(function(html) {
        var previewDiv = document.getElementById(div);
        var contentDiv = previewDiv.querySelector('.preview-content');
        if (contentDiv) {
            contentDiv.innerHTML = html;
            updatePreviewAuthor(previewDiv);
        } else {
            previewDiv.innerHTML = html;
        }
        if (mathjax && typeof MathJax !== 'undefined') {
            setTimeout(function() {
                MathJax.Hub.Queue(["Typeset", MathJax.Hub, div]);
            }, 100);
        }
    });
}

// CSS-based toggle for smoother animations.
function toggle(target, button, off_text, on_text) {
    if (typeof on_text === 'undefined') on_text = 'hide';
    var el = document.getElementById(target);
    var btn = document.getElementById(button);

    // Handle node-children collapse (visible by default, toggle to hide)
    if (target.indexOf('node-children-') === 0) {
        if (el.classList.contains('toggle-collapsed')) {
            // Expanding: set max-height to scrollHeight, animate, then remove classes
            el.classList.add('toggle-expanding');
            el.style.maxHeight = el.scrollHeight + 'px';
            el.classList.remove('toggle-collapsed');
            btn.textContent = on_text;
            setTimeout(function() {
                el.classList.remove('toggle-expanding');
                el.style.maxHeight = '';
            }, 800);
        } else {
            // Collapsing: set max-height to current height, then collapse
            el.style.maxHeight = el.scrollHeight + 'px';
            el.offsetHeight; // force reflow
            el.classList.add('toggle-collapsed');
            el.style.maxHeight = '';
            btn.textContent = off_text;
        }
        return;
    }

    if (el.classList.contains('toggle-open')) {
        // Animate close, then update text
        el.classList.add('toggle-closing');
        setTimeout(function() {
            el.classList.remove('toggle-open');
            el.classList.remove('toggle-closing');
            btn.textContent = off_text;
        }, 800);
    } else {
        // Update text immediately when opening
        btn.textContent = on_text;
        el.classList.add('toggle-open');
        // Auto-grow any textareas that have content
        var textarea = el.querySelector('.common-textarea');
        if (textarea && textarea.value) {
            setTimeout(function() { autoGrow(textarea); }, 10);
        }
    }
}

// Animate <details> close for preview-details elements and persist state in localStorage.
if (typeof document.addEventListener === 'function') {
    document.addEventListener('click', function(e) {
        var summary = e.target.closest('.preview-toggle');
        if (!summary) return;
        var details = summary.parentElement;
        if (!details || !details.classList.contains('preview-details')) return;
        if (details.open && !details.classList.contains('closing')) {
            e.preventDefault();
            details.classList.add('closing');
            localStorage.setItem('remarkbox-preview-hidden', 'true');
            setTimeout(function() {
                details.open = false;
                details.classList.remove('closing');
            }, 800);
        } else if (!details.open) {
            localStorage.removeItem('remarkbox-preview-hidden');
        }
    }, true);
}

// Auto-grow textarea as content is added
function autoGrow(el) {
    el.style.height = 'auto';
    var newHeight = Math.min(el.scrollHeight, 400);
    el.style.height = newHeight + 'px';
}

// Thread title typeahead for duplicate prevention (T9).
var threadSearchTimer = null;

function initThreadTitleTypeahead() {
    var titleInput = document.getElementById('thread_title_input');
    if (!titleInput) return;

    // Create the suggestions container right after the title input.
    var suggestionsDiv = document.createElement('div');
    suggestionsDiv.id = 'thread-title-suggestions';
    suggestionsDiv.className = 'thread-title-suggestions';
    suggestionsDiv.style.display = 'none';
    titleInput.parentNode.insertBefore(suggestionsDiv, titleInput.nextSibling);

    titleInput.addEventListener('input', function() {
        var query = titleInput.value.trim();
        if (query.length < 2) {
            suggestionsDiv.style.display = 'none';
            suggestionsDiv.innerHTML = '';
            return;
        }
        if (threadSearchTimer) {
            clearTimeout(threadSearchTimer);
        }
        threadSearchTimer = setTimeout(function() {
            searchThreads(query, suggestionsDiv);
        }, 400);
    });

    // Clicking a suggestion navigates to that thread.
    suggestionsDiv.addEventListener('click', function(e) {
        var link = e.target.closest('.suggestion-item');
        if (link && link.href) {
            e.preventDefault();
            e.stopPropagation();
            window.location.href = link.href;
        }
    });

    // Hide suggestions when clicking outside.
    document.addEventListener('click', function(e) {
        if (e.target !== titleInput && !suggestionsDiv.contains(e.target)) {
            suggestionsDiv.style.display = 'none';
        }
    });

    // Show suggestions again on focus if they have content.
    titleInput.addEventListener('focus', function() {
        if (suggestionsDiv.innerHTML) {
            suggestionsDiv.style.display = '';
        }
    });
}

function searchThreads(query, suggestionsDiv) {
    // Derive namespace from the current page URL or a data attribute.
    var namespace = document.body.getAttribute('data-namespace') || '';
    if (!namespace) return;

    var url = '/api/v1/threads/search?q=' + encodeURIComponent(query) +
              '&namespace=' + encodeURIComponent(namespace);

    fetch(url, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function(response) { return response.json(); })
    .then(function(data) {
        if (!data.threads || data.threads.length === 0) {
            suggestionsDiv.style.display = 'none';
            suggestionsDiv.innerHTML = '';
            return;
        }

        var html = '<div class="suggestions-header">Existing threads:</div>';
        data.threads.forEach(function(thread) {
            html += '<a href="' + thread.path + '" class="suggestion-item">' +
                    escapeHtml(thread.title) +
                    '<span class="suggestion-meta"> &mdash; ' + thread.created_ago + '</span>' +
                    '</a>';
        });
        suggestionsDiv.innerHTML = html;
        suggestionsDiv.style.display = '';
    })
    .catch(function() {
        suggestionsDiv.style.display = 'none';
    });
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

// AJAX comment submission — capability-driven presentation.
// When JS is available, intercepts reply form POSTs and submits
// via fetch so the page does not reload. When JS is disabled,
// the form falls back to the normal POST + redirect.
function initAjaxCommentForms() {
    document.querySelectorAll('form[action*="/reply"]').forEach(function(form) {
        // Skip forms that are already wired up.
        if (form.dataset.ajaxBound) return;
        form.dataset.ajaxBound = '1';

        form.addEventListener('submit', function(e) {
            var submitBtn = form.querySelector('.rb-submit');
            if (!submitBtn) return; // let normal submit proceed

            e.preventDefault();
            var formData = new FormData(form);
            var originalLabel = submitBtn.value;
            submitBtn.disabled = true;
            submitBtn.value = 'Sending...';

            fetch(form.action, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(function(response) {
                if (!response.ok || response.status !== 201) {
                    // Auth redirect, validation error, or server error
                    // — fall back to regular form submit.
                    submitBtn.disabled = false;
                    submitBtn.value = originalLabel;
                    form.submit();
                    return;
                }
                return response.json();
            })
            .then(function(data) {
                if (!data) return;
                insertReply(data, form);
                // Clear the textarea.
                var textarea = form.querySelector('.common-textarea');
                if (textarea) textarea.value = '';
                // Clear the preview.
                var preview = form.querySelector('.preview');
                if (preview) {
                    var contentDiv = preview.querySelector('.preview-content');
                    if (contentDiv) {
                        contentDiv.innerHTML = '';
                    }
                    var authorDiv = preview.querySelector('.preview-author');
                    if (authorDiv) {
                        authorDiv.style.display = 'none';
                    }
                }
                submitBtn.disabled = false;
                submitBtn.value = originalLabel;
            })
            .catch(function() {
                // Network error — fall back to regular form submit.
                submitBtn.disabled = false;
                submitBtn.value = originalLabel;
                form.submit();
            });
        });
    });
}

function insertReply(data, form) {
    // Insert server-rendered node HTML into the correct position.
    var parentNodeDiv = form.closest('.node');

    if (parentNodeDiv) {
        // Replying to a child node — append to parent's children container.
        var childrenContainer = parentNodeDiv.querySelector('[id^="node-children-"]');
        if (childrenContainer) {
            childrenContainer.insertAdjacentHTML('beforeend', data.node_html);
        }
    } else {
        // Replying to root — insert into .thread container.
        var threadDiv = document.querySelector('.thread');
        if (threadDiv) {
            threadDiv.insertAdjacentHTML('afterbegin', data.node_html);
        } else {
            // First comment — replace .no-comments placeholder.
            var noComments = document.querySelector('.no-comments');
            if (noComments) {
                var newThread = document.createElement('div');
                newThread.className = 'thread';
                newThread.innerHTML = data.node_html;
                noComments.replaceWith(newThread);
            }
        }
    }

    // Scroll to and highlight the new node.
    var newNode = document.getElementById('node-' + data.id);
    if (newNode) {
        newNode.scrollIntoView({ behavior: 'smooth', block: 'center' });
        newNode.classList.add('focused');
        setTimeout(function() { newNode.classList.remove('focused'); }, 3000);

        // Bind auto-grow on new textareas.
        newNode.querySelectorAll('.common-textarea').forEach(function(textarea) {
            textarea.addEventListener('input', function() {
                autoGrow(this);
            });
        });

        // Respect user's preview visibility preference.
        if (localStorage.getItem('remarkbox-preview-hidden') === 'true') {
            newNode.querySelectorAll('.preview-details').forEach(function(details) {
                details.open = false;
            });
        }
    }

    // Wire up AJAX on any new reply forms and action buttons.
    initAjaxCommentForms();
    initAjaxActionForms();
}

// AJAX action buttons — capability-driven presentation.
// When JS is available, intercepts action form POSTs (lock, unlock, watch,
// unwatch, disable, enable, verify, approve, deny) and submits via fetch
// so the page does not reload.  Falls back to normal POST + redirect when
// JS is disabled or on error.
function initAjaxActionForms() {
    document.querySelectorAll('form.ajax-action').forEach(function(form) {
        if (form.dataset.ajaxBound) return;
        form.dataset.ajaxBound = '1';

        form.addEventListener('submit', function(e) {
            var btn = form.querySelector('[type="submit"]');
            if (!btn) return;

            e.preventDefault();
            var formData = new FormData(form);
            btn.disabled = true;

            fetch(form.action, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(function(response) {
                if (!response.ok) {
                    btn.disabled = false;
                    form.submit();
                    return;
                }
                return response.json();
            })
            .then(function(data) {
                if (!data) return;
                handleActionResponse(data, form, btn);
            })
            .catch(function() {
                btn.disabled = false;
                form.submit();
            });
        });
    });
}

function handleActionResponse(data, form, btn) {
    if (!data.ok) {
        btn.disabled = false;
        form.submit();
        return;
    }

    var action = form.action;

    // Top-level toggle pairs: /lock ↔ /unlock, /watch ↔ /unwatch
    if (action.match(/\/lock$/)) {
        form.action = action.replace(/\/lock$/, '/unlock');
        btn.value = 'unlock';
        btn.name = 'unlock';
        btn.className = 'unlock button-small';
        btn.disabled = false;
        return;
    }
    if (action.match(/\/unlock$/)) {
        form.action = action.replace(/\/unlock$/, '/lock');
        btn.value = '\uD83D\uDD12 lock';
        btn.name = 'lock';
        btn.className = 'lock button-small';
        btn.disabled = false;
        return;
    }
    if (action.match(/\/watch$/)) {
        form.action = action.replace(/\/watch$/, '/unwatch');
        btn.value = 'unwatch';
        btn.name = 'unwatch';
        btn.className = 'unwatch button-small';
        btn.disabled = false;
        return;
    }
    if (action.match(/\/unwatch$/)) {
        form.action = action.replace(/\/unwatch$/, '/watch');
        btn.value = '\uD83D\uDC41 watch';
        btn.name = 'watch';
        btn.className = 'watch button-small';
        btn.disabled = false;
        return;
    }

    // Node-level toggle pairs: .../disable ↔ .../enable
    if (action.match(/\/disable$/)) {
        form.action = action.replace(/\/disable$/, '/enable');
        btn.textContent = 'enable';
        btn.name = 'enable';
        btn.value = 'enable';
        btn.disabled = false;
        // Visually mark the node as disabled.
        var nodeDiv = form.closest('.node');
        if (nodeDiv) {
            var statusSpan = nodeDiv.querySelector('.status');
            if (statusSpan) statusSpan.innerHTML = '<span>(waiting for deletion)</span>';
            var authorDate = nodeDiv.querySelector('.author-and-date');
            if (authorDate) authorDate.innerHTML = 'node was disabled';
        }
        return;
    }
    if (action.match(/\/enable$/)) {
        form.action = action.replace(/\/enable$/, '/disable');
        btn.textContent = 'disable';
        btn.name = 'disable';
        btn.value = 'disable';
        btn.disabled = false;
        // Reload to restore full node content since we don't have it client-side.
        window.location.reload();
        return;
    }

    // .../approve ↔ .../deny
    if (action.match(/\/approve$/)) {
        form.action = action.replace(/\/approve$/, '/deny');
        btn.textContent = 'deny';
        btn.name = 'deny';
        btn.value = 'deny';
        btn.disabled = false;
        // Remove the adjacent deny button if present (from the "both" state).
        var sibling = form.nextElementSibling;
        while (sibling && !sibling.matches('form.ajax-action')) {
            sibling = sibling.nextElementSibling;
        }
        if (sibling && sibling.querySelector('[name="deny"]')) {
            sibling.remove();
        }
        return;
    }
    if (action.match(/\/deny$/)) {
        form.action = action.replace(/\/deny$/, '/approve');
        btn.textContent = 'approve';
        btn.name = 'approve';
        btn.value = 'approve';
        btn.disabled = false;
        // Remove the adjacent approve button if present (from the "both" state).
        var sibling = form.previousElementSibling;
        while (sibling && !sibling.matches('form.ajax-action')) {
            sibling = sibling.previousElementSibling;
        }
        if (sibling && sibling.querySelector('[name="approve"]')) {
            sibling.remove();
        }
        return;
    }

    // .../verify — no toggle, just remove the button.
    if (action.match(/\/verify$/)) {
        form.remove();
        return;
    }

    // Unknown action — re-enable and let normal flow handle it.
    btn.disabled = false;
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {

    // Restore preview state from localStorage
    if (localStorage.getItem('remarkbox-preview-hidden') === 'true') {
        document.querySelectorAll('.preview-details').forEach(function(details) {
            details.open = false;
        });
    }

    // Auto-grow textareas on input
    document.querySelectorAll('.common-textarea').forEach(function(textarea) {
        textarea.addEventListener('input', function() {
            autoGrow(this);
        });
    });

    // Initialize AJAX comment forms (capability-driven presentation).
    initAjaxCommentForms();

    // Initialize AJAX action buttons (capability-driven presentation).
    initAjaxActionForms();

    // Vote button handlers
    document.querySelectorAll('button.vote-up').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var post_id = this.closest('div').id;
            sendVote(post_id, 'up');
        });
    });

    document.querySelectorAll('button.vote-down').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var post_id = this.closest('div').id;
            sendVote(post_id, 'down');
        });
    });

    // Fade in alert elements
    document.querySelectorAll('.alert').forEach(function(el) {
        setTimeout(function() {
            el.style.transition = 'opacity 2s';
            el.style.opacity = '1';
        }, 100);
    });

    // Highlight fragment hash div if it exists
    if (window.location.hash) {
        var fragment = document.getElementById('node-data-' + window.location.hash.replace('#', ''));
        if (fragment) {
            fragment.classList.add('focused');
        }
    }

    // Initialize thread title typeahead for duplicate prevention (T9).
    initThreadTitleTypeahead();

});

function sendVote(post_id, direction) {
    var url = '/vote-post';
    var params = new URLSearchParams({
        'post_id': post_id,
        'direction': direction,
        'csrf_token': csrf_token
    });

    fetch(url + '?' + params.toString())
    .then(function(response) { return response.json(); })
    .then(function(r) {
        if (r['status']) {
            var el = document.getElementById(post_id);
            var b = el.querySelector('b');
            if (b) b.innerHTML = r['vote_sum'];
        } else {
            var jsonEl = document.getElementById('json');
            if (jsonEl) jsonEl.innerHTML = r['msg'];
        }
    });
}
