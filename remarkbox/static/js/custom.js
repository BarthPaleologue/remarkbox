// post_preview
// previewTimer must live outside the functions.
var previewTimer = null;

function previewAjax(textarea, div, show_raw, mathjax) {
    // set div to raw textarea while waiting for remote Markdown rendering.
    if (show_raw) {
        // bust HTML tags like <script> to prevent running evil code.
        var el = document.getElementById(textarea);
        var busted_textarea = el.value.replace(/&/g, '&amp;').replace(/</g, '&lt;');
        document.getElementById(div).innerHTML = '<span class="preview-raw-markdown">' + busted_textarea + '</span>';
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
        document.getElementById(div).innerHTML = html;
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

// Animate <details> close for preview-details elements.
if (typeof document.addEventListener === 'function') {
    document.addEventListener('click', function(e) {
        var summary = e.target.closest('.preview-toggle');
        if (!summary) return;
        var details = summary.parentElement;
        if (!details || !details.classList.contains('preview-details')) return;
        if (details.open && !details.classList.contains('closing')) {
            e.preventDefault();
            details.classList.add('closing');
            setTimeout(function() {
                details.open = false;
                details.classList.remove('closing');
            }, 800);
        }
    }, true);
}

// Auto-grow textarea as content is added
function autoGrow(el) {
    el.style.height = 'auto';
    var newHeight = Math.min(el.scrollHeight, 400);
    el.style.height = newHeight + 'px';
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {

    // Auto-grow textareas on input
    document.querySelectorAll('.common-textarea').forEach(function(textarea) {
        textarea.addEventListener('input', function() {
            autoGrow(this);
        });
    });

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
