/*
 * rb.c — Remarkbox CLI client (uses rb.h library)
 *
 * Compile:
 *     gcc rb.c -o rb -lcurl
 *
 * Download both files:
 *     curl -s https://REMARKBOX/api/v1/clients/c -o rb.c
 *     curl -s https://REMARKBOX/api/v1/clients/c?file=rb.h -o rb.h
 *     gcc rb.c -o rb -lcurl
 *
 * Usage:
 *     rb [uri] <command> [args...]
 *
 * If uri is omitted, uses REMARKBOX_URL environment variable.
 * Session cookies stored at REMARKBOX_COOKIES or ~/.config/remarkbox/cookies.txt
 *
 * License: Same as Remarkbox
 */

#define RB_IMPLEMENTATION
#include "rb.h"

#include <stdio.h>
#include <string.h>

#define CLI_VERSION RB_LIB_VERSION

static void usage(void)
{
    fprintf(stderr,
        "rb %s — Remarkbox CLI client\n"
        "\n"
        "Usage: rb [uri] <command> [args...]\n"
        "\n"
        "If uri is omitted, uses REMARKBOX_URL environment variable.\n"
        "Session cookies are stored at REMARKBOX_COOKIES or\n"
        "~/.config/remarkbox/cookies.txt\n"
        "\n"
        "Commands:\n"
        "  version                                 Deployed version\n"
        "  threads <namespace>                     List threads\n"
        "  thread <node_id>                        Get thread with replies\n"
        "  search <namespace> <query>              Search threads\n"
        "  node <node_id>                          Get a single node\n"
        "  post <namespace> <title> <data> [name]  Create thread\n"
        "  reply <node_id> <data> [name]           Reply to node\n"
        "  edit <node_id> <data>                   Edit a node\n"
        "  disable <node_id>                       Disable a node\n"
        "  enable <node_id>                        Enable a node\n"
        "  approve <node_id>                       Approve a node\n"
        "  lock <node_id>                          Lock a thread\n"
        "  unlock <node_id>                        Unlock a thread\n"
        "  delete <node_id>                        Delete a node\n"
        "  login <email>                           Request OTP\n"
        "  verify <email> <otp>                    Verify OTP\n"
        "  profile                                 Show current user\n"
        "\n"
        "Examples:\n"
        "  rb https://my.remarkbox.com threads meta.remarkbox.com\n"
        "  rb threads meta.remarkbox.com          # uses REMARKBOX_URL\n"
        "  rb login user@example.com\n"
        "  rb verify user@example.com 123456\n"
        "  rb post meta.remarkbox.com \"Title\" \"Body\" MyBot\n"
        "\n"
        "Compile: gcc rb.c -o rb -lcurl\n"
        "\n", CLI_VERSION);
}

/* Run a command, print the response, return exit code. */
static int run(rb_response_t r)
{
    if (r.body && r.body_len > 0)
        rb_json_pretty(r.body);
    int rc = r.ok ? 0 : 1;
    rb_response_free(&r);
    return rc;
}

int main(int argc, char *argv[])
{
    const char *base_uri;
    int cmd_start;

    if (argc < 2) { usage(); return 1; }

    /* Determine if first arg is a URI or a command */
    if (strncmp(argv[1], "http://", 7) == 0 || strncmp(argv[1], "https://", 8) == 0) {
        base_uri = argv[1];
        cmd_start = 2;
    } else {
        base_uri = getenv("REMARKBOX_URL");
        if (!base_uri || !*base_uri) {
            fprintf(stderr, "rb: no URI provided and REMARKBOX_URL not set\n");
            return 1;
        }
        cmd_start = 1;
    }

    if (cmd_start >= argc) { usage(); return 1; }

    curl_global_init(CURL_GLOBAL_DEFAULT);

    rb_client_t *c = rb_client_new(base_uri, NULL);
    const char *cmd = argv[cmd_start];
    int nargs = argc - cmd_start - 1;
    char **args = argv + cmd_start + 1;
    int rc = 1;

    if (strcmp(cmd, "version") == 0) {
        rc = run(rb_version(c));
    } else if (strcmp(cmd, "threads") == 0 && nargs >= 1) {
        rc = run(rb_list_threads(c, args[0]));
    } else if (strcmp(cmd, "thread") == 0 && nargs >= 1) {
        rc = run(rb_get_thread(c, args[0]));
    } else if (strcmp(cmd, "search") == 0 && nargs >= 2) {
        rc = run(rb_search_threads(c, args[0], args[1]));
    } else if (strcmp(cmd, "node") == 0 && nargs >= 1) {
        rc = run(rb_get_node(c, args[0]));
    } else if (strcmp(cmd, "post") == 0 && nargs >= 3) {
        rc = run(rb_create_thread(c, args[0], args[1], args[2],
                                   nargs >= 4 ? args[3] : NULL));
    } else if (strcmp(cmd, "reply") == 0 && nargs >= 2) {
        rc = run(rb_reply(c, args[0], args[1], nargs >= 3 ? args[2] : NULL));
    } else if (strcmp(cmd, "edit") == 0 && nargs >= 2) {
        rc = run(rb_edit_node(c, args[0], args[1]));
    } else if (strcmp(cmd, "disable") == 0 && nargs >= 1) {
        rc = run(rb_disable_node(c, args[0]));
    } else if (strcmp(cmd, "enable") == 0 && nargs >= 1) {
        rc = run(rb_enable_node(c, args[0]));
    } else if (strcmp(cmd, "approve") == 0 && nargs >= 1) {
        rc = run(rb_approve_node(c, args[0]));
    } else if (strcmp(cmd, "lock") == 0 && nargs >= 1) {
        rc = run(rb_lock_node(c, args[0]));
    } else if (strcmp(cmd, "unlock") == 0 && nargs >= 1) {
        rc = run(rb_unlock_node(c, args[0]));
    } else if (strcmp(cmd, "delete") == 0 && nargs >= 1) {
        rc = run(rb_delete_node(c, args[0]));
    } else if (strcmp(cmd, "login") == 0 && nargs >= 1) {
        rc = run(rb_login(c, args[0]));
    } else if (strcmp(cmd, "verify") == 0 && nargs >= 2) {
        rc = run(rb_verify(c, args[0], args[1]));
    } else if (strcmp(cmd, "profile") == 0) {
        rc = run(rb_get_profile(c));
    } else if (strcmp(cmd, "help") == 0 || strcmp(cmd, "--help") == 0 ||
               strcmp(cmd, "-h") == 0) {
        usage(); rc = 0;
    } else {
        fprintf(stderr, "rb: unknown command '%s'\n\n", cmd);
        usage(); rc = 1;
    }

    rb_client_free(c);
    curl_global_cleanup();
    return rc;
}
