/*
 * rb.h — Remarkbox C library (single-header, libcurl only)
 *
 * Download:
 *     curl -s https://REMARKBOX/api/v1/clients/c?file=rb.h -o rb.h
 *
 * Usage as a library:
 *     // In exactly ONE .c file, before including:
 *     #define RB_IMPLEMENTATION
 *     #include "rb.h"
 *
 *     // In all other .c files, just:
 *     #include "rb.h"
 *
 * Quick start:
 *     rb_client_t *c = rb_client_new("https://my.remarkbox.com", NULL);
 *     rb_response_t r = rb_version(c);
 *     if (r.ok) printf("%s\n", r.body);
 *     rb_response_free(&r);
 *     rb_client_free(c);
 *
 * Requires: libcurl (link with -lcurl)
 * License: Same as Remarkbox
 */

#ifndef RB_H
#define RB_H

#include <stdlib.h>
#include <curl/curl.h>

#define RB_LIB_VERSION "0.1.0"
#define RB_MAX_URI  2048
#define RB_MAX_BODY 1048576  /* 1 MB response limit */

/* ---------------------------------------------------------------------------
 * Types
 * ------------------------------------------------------------------------- */

typedef struct {
    char  *base_uri;       /* e.g. "https://my.remarkbox.com" */
    char  *cookie_path;    /* path to Netscape cookie jar     */
} rb_client_t;

typedef struct {
    int    ok;             /* 1 if HTTP 2xx, 0 otherwise */
    long   status;         /* HTTP status code            */
    char  *body;           /* raw JSON response (caller must rb_response_free) */
    size_t body_len;
} rb_response_t;

/* ---------------------------------------------------------------------------
 * Client lifecycle
 * ------------------------------------------------------------------------- */

/* Create a client. cookie_path may be NULL for default
   (~/.config/remarkbox/cookies.txt or REMARKBOX_COOKIES). */
rb_client_t *rb_client_new(const char *base_uri, const char *cookie_path);

/* Free a client. */
void rb_client_free(rb_client_t *c);

/* Free response body. */
void rb_response_free(rb_response_t *r);

/* ---------------------------------------------------------------------------
 * API methods — each returns rb_response_t with raw JSON in body
 * ------------------------------------------------------------------------- */

/* Version */
rb_response_t rb_version(rb_client_t *c);

/* Threads */
rb_response_t rb_list_threads(rb_client_t *c, const char *ns);
rb_response_t rb_get_thread(rb_client_t *c, const char *node_id);
rb_response_t rb_search_threads(rb_client_t *c, const char *ns, const char *query);
rb_response_t rb_create_thread(rb_client_t *c, const char *ns, const char *title,
                                const char *data, const char *anon_name);

/* Replies */
rb_response_t rb_reply(rb_client_t *c, const char *node_id, const char *data,
                        const char *anon_name);

/* Nodes */
rb_response_t rb_get_node(rb_client_t *c, const char *node_id);
rb_response_t rb_edit_node(rb_client_t *c, const char *node_id, const char *data);
rb_response_t rb_disable_node(rb_client_t *c, const char *node_id);
rb_response_t rb_enable_node(rb_client_t *c, const char *node_id);
rb_response_t rb_approve_node(rb_client_t *c, const char *node_id);
rb_response_t rb_lock_node(rb_client_t *c, const char *node_id);
rb_response_t rb_unlock_node(rb_client_t *c, const char *node_id);
rb_response_t rb_delete_node(rb_client_t *c, const char *node_id);

/* Auth */
rb_response_t rb_login(rb_client_t *c, const char *email);
rb_response_t rb_verify(rb_client_t *c, const char *email, const char *otp);

/* Profile */
rb_response_t rb_get_profile(rb_client_t *c);

/* ---------------------------------------------------------------------------
 * Utility
 * ------------------------------------------------------------------------- */

/* Pretty-print JSON to stdout. */
void rb_json_pretty(const char *json);

/* Escape a string for use inside a JSON string value.
   Writes to out (must be at least out_size bytes). */
void rb_json_escape(const char *s, char *out, size_t out_size);


/* =========================================================================
 * IMPLEMENTATION — include this in exactly one .c file
 * ========================================================================= */

#ifdef RB_IMPLEMENTATION

#include <stdio.h>
#include <string.h>

/* ---------------------------------------------------------------------------
 * Internal: response buffer
 * ------------------------------------------------------------------------- */

struct rb__buf {
    char  *data;
    size_t len;
    size_t cap;
};

static void rb__buf_init(struct rb__buf *b)
{
    b->cap  = 4096;
    b->data = (char *)malloc(b->cap);
    b->len  = 0;
    if (b->data) b->data[0] = '\0';
}

static size_t rb__write_cb(void *ptr, size_t size, size_t nmemb, void *userdata)
{
    struct rb__buf *b = (struct rb__buf *)userdata;
    size_t bytes = size * nmemb;

    if (b->len + bytes + 1 > RB_MAX_BODY)
        bytes = RB_MAX_BODY - b->len - 1;

    if (b->len + bytes + 1 > b->cap) {
        size_t newcap = b->cap * 2;
        while (newcap < b->len + bytes + 1) newcap *= 2;
        if (newcap > RB_MAX_BODY) newcap = RB_MAX_BODY;
        char *tmp = (char *)realloc(b->data, newcap);
        if (!tmp) return 0;
        b->data = tmp;
        b->cap  = newcap;
    }

    memcpy(b->data + b->len, ptr, bytes);
    b->len += bytes;
    b->data[b->len] = '\0';
    return size * nmemb;
}

/* ---------------------------------------------------------------------------
 * Internal: default cookie path
 * ------------------------------------------------------------------------- */

static const char *rb__default_cookie_path(void)
{
    const char *env = getenv("REMARKBOX_COOKIES");
    if (env && *env) return env;

    static char path[1024];
    const char *home = getenv("HOME");
    if (!home) home = ".";
    snprintf(path, sizeof(path), "%s/.config/remarkbox/cookies.txt", home);
    return path;
}

/* ---------------------------------------------------------------------------
 * Client lifecycle
 * ------------------------------------------------------------------------- */

rb_client_t *rb_client_new(const char *base_uri, const char *cookie_path)
{
    rb_client_t *c = (rb_client_t *)calloc(1, sizeof(rb_client_t));
    if (!c) return NULL;

    /* Strip trailing slash */
    size_t len = strlen(base_uri);
    while (len > 0 && base_uri[len - 1] == '/') len--;
    c->base_uri = (char *)malloc(len + 1);
    if (c->base_uri) { memcpy(c->base_uri, base_uri, len); c->base_uri[len] = '\0'; }

    const char *cp = cookie_path ? cookie_path : rb__default_cookie_path();
    c->cookie_path = (char *)malloc(strlen(cp) + 1);
    if (c->cookie_path) strcpy(c->cookie_path, cp);

    return c;
}

void rb_client_free(rb_client_t *c)
{
    if (!c) return;
    free(c->base_uri);
    free(c->cookie_path);
    free(c);
}

void rb_response_free(rb_response_t *r)
{
    free(r->body);
    r->body = NULL;
    r->body_len = 0;
}

/* ---------------------------------------------------------------------------
 * Internal: HTTP request
 * ------------------------------------------------------------------------- */

static rb_response_t rb__request(rb_client_t *c, const char *method,
                                  const char *api_path, const char *json_body,
                                  const char *extra_header)
{
    rb_response_t result = {0, 0, NULL, 0};
    char uri[RB_MAX_URI];
    struct rb__buf resp;

    snprintf(uri, sizeof(uri), "%s%s", c->base_uri, api_path);
    rb__buf_init(&resp);

    CURL *curl = curl_easy_init();
    if (!curl) {
        result.body = (char *)malloc(32);
        if (result.body) { strcpy(result.body, "{\"error\":\"curl init failed\"}"); result.body_len = strlen(result.body); }
        return result;
    }

    curl_easy_setopt(curl, CURLOPT_URL, uri);
    curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, method);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, rb__write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_COOKIEFILE, c->cookie_path);
    curl_easy_setopt(curl, CURLOPT_COOKIEJAR, c->cookie_path);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "rb/" RB_LIB_VERSION);

    struct curl_slist *headers = NULL;
    headers = curl_slist_append(headers, "Accept: application/json");
    if (json_body) {
        headers = curl_slist_append(headers, "Content-Type: application/json");
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body);
    }
    if (extra_header)
        headers = curl_slist_append(headers, extra_header);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

    CURLcode res = curl_easy_perform(curl);
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &result.status);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        free(resp.data);
        result.body = (char *)malloc(128);
        if (result.body) {
            snprintf(result.body, 128, "{\"error\":\"%s\"}", curl_easy_strerror(res));
            result.body_len = strlen(result.body);
        }
        return result;
    }

    result.ok       = (result.status >= 200 && result.status < 400);
    result.body     = resp.data;   /* caller owns this now */
    result.body_len = resp.len;
    return result;
}

/* ---------------------------------------------------------------------------
 * Utility
 * ------------------------------------------------------------------------- */

void rb_json_escape(const char *s, char *out, size_t out_size)
{
    size_t j = 0;
    for (size_t i = 0; s[i] && j + 6 < out_size; i++) {
        switch (s[i]) {
        case '"':  out[j++] = '\\'; out[j++] = '"';  break;
        case '\\': out[j++] = '\\'; out[j++] = '\\'; break;
        case '\n': out[j++] = '\\'; out[j++] = 'n';  break;
        case '\r': out[j++] = '\\'; out[j++] = 'r';  break;
        case '\t': out[j++] = '\\'; out[j++] = 't';  break;
        default:
            if ((unsigned char)s[i] < 0x20)
                j += snprintf(out + j, out_size - j, "\\u%04x", (unsigned char)s[i]);
            else
                out[j++] = s[i];
            break;
        }
    }
    out[j] = '\0';
}

void rb_json_pretty(const char *s)
{
    int indent = 0, in_string = 0, escaped = 0;
    for (; *s; s++) {
        if (escaped)        { putchar(*s); escaped = 0; continue; }
        if (*s == '\\' && in_string) { putchar(*s); escaped = 1; continue; }
        if (*s == '"')      { in_string = !in_string; putchar(*s); continue; }
        if (in_string)      { putchar(*s); continue; }
        switch (*s) {
        case '{': case '[':
            putchar(*s); putchar('\n'); indent += 2;
            for (int i = 0; i < indent; i++) putchar(' ');
            break;
        case '}': case ']':
            putchar('\n'); indent -= 2; if (indent < 0) indent = 0;
            for (int i = 0; i < indent; i++) putchar(' ');
            putchar(*s); break;
        case ',':
            putchar(*s); putchar('\n');
            for (int i = 0; i < indent; i++) putchar(' ');
            break;
        case ':': putchar(*s); putchar(' '); break;
        default:
            if (*s != ' ' && *s != '\t' && *s != '\n' && *s != '\r')
                putchar(*s);
            break;
        }
    }
    putchar('\n');
}

/* ---------------------------------------------------------------------------
 * Internal: URI encoding helper
 * ------------------------------------------------------------------------- */

static void rb__uri_encode(const char *s, char *out, size_t out_size)
{
    CURL *curl = curl_easy_init();
    if (curl) {
        char *enc = curl_easy_escape(curl, s, 0);
        if (enc) { snprintf(out, out_size, "%s", enc); curl_free(enc); }
        else     { snprintf(out, out_size, "%s", s); }
        curl_easy_cleanup(curl);
    } else {
        snprintf(out, out_size, "%s", s);
    }
}

/* ---------------------------------------------------------------------------
 * API methods
 * ------------------------------------------------------------------------- */

rb_response_t rb_version(rb_client_t *c)
{
    return rb__request(c, "GET", "/api/v1/version", NULL, NULL);
}

rb_response_t rb_list_threads(rb_client_t *c, const char *ns)
{
    char path[RB_MAX_URI], enc[1024];
    rb__uri_encode(ns, enc, sizeof(enc));
    snprintf(path, sizeof(path), "/api/v1/threads?namespace=%s", enc);
    return rb__request(c, "GET", path, NULL, NULL);
}

rb_response_t rb_get_thread(rb_client_t *c, const char *node_id)
{
    char path[RB_MAX_URI];
    snprintf(path, sizeof(path), "/api/v1/threads/%s", node_id);
    return rb__request(c, "GET", path, NULL, NULL);
}

rb_response_t rb_search_threads(rb_client_t *c, const char *ns, const char *query)
{
    char path[RB_MAX_URI], enc_ns[512], enc_q[512];
    rb__uri_encode(ns, enc_ns, sizeof(enc_ns));
    rb__uri_encode(query, enc_q, sizeof(enc_q));
    snprintf(path, sizeof(path), "/api/v1/threads/search?namespace=%s&q=%s",
             enc_ns, enc_q);
    return rb__request(c, "GET", path, NULL, NULL);
}

rb_response_t rb_create_thread(rb_client_t *c, const char *ns, const char *title,
                                const char *data, const char *anon_name)
{
    char body[RB_MAX_BODY];
    char ens[2048], etitle[2048], edata[524288], ename[512];
    rb_json_escape(ns, ens, sizeof(ens));
    rb_json_escape(title, etitle, sizeof(etitle));
    rb_json_escape(data, edata, sizeof(edata));
    if (anon_name) {
        rb_json_escape(anon_name, ename, sizeof(ename));
        snprintf(body, sizeof(body),
                 "{\"namespace\":\"%s\",\"title\":\"%s\",\"data\":\"%s\","
                 "\"anonymous_name\":\"%s\"}", ens, etitle, edata, ename);
    } else {
        snprintf(body, sizeof(body),
                 "{\"namespace\":\"%s\",\"title\":\"%s\",\"data\":\"%s\"}",
                 ens, etitle, edata);
    }
    return rb__request(c, "POST", "/api/v1/threads", body, NULL);
}

rb_response_t rb_reply(rb_client_t *c, const char *node_id, const char *data,
                        const char *anon_name)
{
    char path[RB_MAX_URI], body[RB_MAX_BODY];
    char edata[524288], ename[512];
    rb_json_escape(data, edata, sizeof(edata));
    snprintf(path, sizeof(path), "/api/v1/threads/%s/replies", node_id);
    if (anon_name) {
        rb_json_escape(anon_name, ename, sizeof(ename));
        snprintf(body, sizeof(body),
                 "{\"data\":\"%s\",\"anonymous_name\":\"%s\"}", edata, ename);
    } else {
        snprintf(body, sizeof(body), "{\"data\":\"%s\"}", edata);
    }
    return rb__request(c, "POST", path, body, NULL);
}

rb_response_t rb_get_node(rb_client_t *c, const char *node_id)
{
    char path[RB_MAX_URI];
    snprintf(path, sizeof(path), "/api/v1/nodes/%s", node_id);
    return rb__request(c, "GET", path, NULL, NULL);
}

rb_response_t rb_edit_node(rb_client_t *c, const char *node_id, const char *data)
{
    char path[RB_MAX_URI], body[RB_MAX_BODY], edata[524288];
    rb_json_escape(data, edata, sizeof(edata));
    snprintf(path, sizeof(path), "/api/v1/nodes/%s", node_id);
    snprintf(body, sizeof(body), "{\"data\":\"%s\"}", edata);
    return rb__request(c, "PATCH", path, body, NULL);
}

static rb_response_t rb__mod_flag(rb_client_t *c, const char *node_id,
                                    const char *field, const char *value)
{
    char path[RB_MAX_URI], body[256];
    snprintf(path, sizeof(path), "/api/v1/nodes/%s", node_id);
    snprintf(body, sizeof(body), "{\"%s\":%s}", field, value);
    return rb__request(c, "PATCH", path, body, NULL);
}

rb_response_t rb_disable_node(rb_client_t *c, const char *id) { return rb__mod_flag(c, id, "disabled", "true"); }
rb_response_t rb_enable_node(rb_client_t *c, const char *id)  { return rb__mod_flag(c, id, "disabled", "false"); }
rb_response_t rb_approve_node(rb_client_t *c, const char *id) { return rb__mod_flag(c, id, "approved", "true"); }
rb_response_t rb_lock_node(rb_client_t *c, const char *id)    { return rb__mod_flag(c, id, "locked", "true"); }
rb_response_t rb_unlock_node(rb_client_t *c, const char *id)  { return rb__mod_flag(c, id, "locked", "false"); }

rb_response_t rb_delete_node(rb_client_t *c, const char *node_id)
{
    char path[RB_MAX_URI];
    snprintf(path, sizeof(path), "/api/v1/nodes/%s", node_id);
    return rb__request(c, "DELETE", path, NULL, NULL);
}

rb_response_t rb_login(rb_client_t *c, const char *email)
{
    char body[512], eemail[256];
    rb_json_escape(email, eemail, sizeof(eemail));
    snprintf(body, sizeof(body), "{\"email\":\"%s\"}", eemail);
    return rb__request(c, "POST", "/api/v1/auth/login", body, NULL);
}

rb_response_t rb_verify(rb_client_t *c, const char *email, const char *otp)
{
    char body[512], eemail[256], eotp[64];
    rb_json_escape(email, eemail, sizeof(eemail));
    rb_json_escape(otp, eotp, sizeof(eotp));
    snprintf(body, sizeof(body), "{\"email\":\"%s\",\"otp\":\"%s\"}", eemail, eotp);
    return rb__request(c, "POST", "/api/v1/auth/verify", body, NULL);
}

rb_response_t rb_get_profile(rb_client_t *c)
{
    return rb__request(c, "GET", "/api/v1/user/profile", NULL, NULL);
}

#endif /* RB_IMPLEMENTATION */
#endif /* RB_H */
