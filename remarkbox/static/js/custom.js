// post_preview
// previewTimer must live outside the functions.
var previewTimer = null;

function previewAjax(textarea, div, show_raw, mathjax) {
    // set div to raw textarea while waiting for remote Markdown rendering.
    if (show_raw) {
        // bust HTML tags like <script> to prevent running evil code.
        var el = document.getElementById(textarea);
        var busted_textarea = el.value.replace(/&/g, '&amp;').replace(/</g, '&lt;');
        var rawHtml = '<span class="preview-raw-markdown">' + busted_textarea + '</span>';
        // Wrap raw preview as a live node for reply forms.
        var form = el.closest('form');
        if (form && isReplyForm(form)) {
            rawHtml = wrapPreviewAsNode(rawHtml, form);
        }
        document.getElementById(div).innerHTML = rawHtml;
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
    var data = new FormData();
    data.append('data', document.getElementById(textarea).value);
    data.append('csrf_token', csrf_token);

    fetch(url, {
        method: 'POST',
        body: data,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function(response) { return response.text(); })
    .then(function(html) {
        // Wrap rendered preview as a live node for reply forms.
        var textareaEl = document.getElementById(textarea);
        var form = textareaEl ? textareaEl.closest('form') : null;
        if (form && isReplyForm(form)) {
            html = wrapPreviewAsNode(html, form);
        }
        document.getElementById(div).innerHTML = html;
        if (mathjax && typeof MathJax !== 'undefined') {
            setTimeout(function() {
                MathJax.Hub.Queue(["Typeset", MathJax.Hub, div]);
            }, 100);
        }
    });
}

function isReplyForm(form) {
    var action = form.getAttribute('action') || '';
    return action.indexOf('/reply') !== -1;
}

function wrapPreviewAsNode(html, form) {
    // Clone the hidden preview header (avatar + author + "just now")
    // and wrap content in node-data div so it looks like a live comment.
    var header = form.querySelector('.preview-header');
    if (!header || !header.innerHTML.trim()) return html;

    var headerHtml = header.innerHTML;

    // For anonymous users, update the displayed name from the input field.
    var nameInput = form.querySelector('[name="anonymous_name"]');
    if (nameInput) {
        var name = nameInput.value.trim() || 'Anonymous';
        headerHtml = headerHtml.replace('>Anonymous<', '>' + escapeHtml(name) + '<');
    }

    return headerHtml + '<div class="node-data">' + html + '</div>';
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
                if (preview) preview.innerHTML = '';
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
    }

    // Wire up AJAX on any new reply forms.
    initAjaxCommentForms();
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
