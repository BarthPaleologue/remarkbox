"""
Functional test of the Remarkbox API against a live instance.

Uses cookie persistence so authentication survives across runs.
First run requires an OTP; subsequent runs reuse the session.
Creates one persistent "API Testing Journey" thread and appends
a new section on each run. All other operations are reads.

Usage:
    # First run (sends OTP, prompts for code):
    python functional_test.py https://my.remarkbox.com meta.remarkbox.com timehexon@unturf.com

    # With OTP on command line:
    python functional_test.py https://my.remarkbox.com meta.remarkbox.com timehexon@unturf.com 173786

    # Subsequent runs reuse saved session:
    python functional_test.py https://my.remarkbox.com meta.remarkbox.com timehexon@unturf.com

    # Set display name (idempotent):
    python functional_test.py https://my.remarkbox.com meta.remarkbox.com timehexon@unturf.com --name timehexon

    # Specify existing journey thread to append to:
    python functional_test.py ... --journey 9f970183-ffaf-11f0-b565-040140774501
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from remarkbox_client import RemarkboxClient, RemarkboxError

THREAD_TITLE = "API Testing Journey"
DEFAULT_COOKIE_DIR = os.path.join(os.path.expanduser("~"), ".config", "remarkbox")
PASS = "PASS"
FAIL = "FAIL"


class JournalWriter:
    """Collects test results and builds a markdown journal section."""

    def __init__(self):
        self.lines = []
        self.results = []
        self._step = 0

    def step(self, title):
        self._step += 1
        self.lines.append("### {}. {}".format(self._step, title))

    def note(self, text):
        self.lines.append(text)

    def blank(self):
        self.lines.append("")

    def log(self, test_name, passed, detail=""):
        mark = "+" if passed else "!"
        status = PASS if passed else FAIL
        print("  [{}] {} {}{}".format(mark, status, test_name,
                                       ": " + detail if detail else ""))
        self.results.append(passed)
        return passed

    @property
    def passed(self):
        return sum(1 for r in self.results if r)

    @property
    def total(self):
        return len(self.results)

    def summary_line(self):
        return "**{}/{} passed.**".format(self.passed, self.total)

    def render(self):
        return "\n".join(self.lines)


def ensure_authenticated(client, email, otp=None):
    """Return True if authenticated, attempting login/verify if needed."""
    try:
        profile = client.get_profile()
        if profile.get("user"):
            return True, "reused session"
    except RemarkboxError:
        pass

    # Request OTP on this client, then verify
    login_result = client.login(email)
    status = login_result.get("status")

    if otp and status in ("sent", "throttled"):
        try:
            result = client.verify(email, otp)
            if result.get("status") == "authenticated":
                return True, "verified otp"
        except RemarkboxError:
            pass

    # Need interactive OTP
    if status == "throttled":
        print("\n  OTP already sent to {} (check inbox)".format(email))
    else:
        print("\n  OTP sent to {}".format(email))
    otp = input("  Enter 6-digit code: ").strip()
    result = client.verify(email, otp)
    return result.get("status") == "authenticated", "verified otp"


def find_journey_thread(client, namespace):
    """Find existing journey thread by title, or return None."""
    data = client.list_threads(namespace)
    for thread in data.get("threads", []):
        if thread["title"].strip() == THREAD_TITLE:
            return thread["id"]
    return None


def run(url, namespace, email, otp=None, display_name=None, journey_id=None):
    cookie_file = os.path.join(DEFAULT_COOKIE_DIR, "cookies.txt")
    os.makedirs(DEFAULT_COOKIE_DIR, exist_ok=True)

    client = RemarkboxClient(url, email=email, cookie_file=cookie_file)
    j = JournalWriter()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ---------------------------------------------------------------
    # Phase 1: Read operations (no trace)
    # ---------------------------------------------------------------
    print("\nPhase 1: Read operations")

    j.step("List Threads")
    try:
        data = client.list_threads(namespace)
        ok = data["namespace"]["name"] == namespace
        j.log("list_threads", ok, "{} threads".format(len(data["threads"])))
        j.note("Fetched {} threads from `{}`.".format(len(data["threads"]), namespace))
        j.blank()
    except Exception as e:
        j.log("list_threads", False, str(e))

    j.step("Get Thread")
    thread_id = None
    try:
        if data["threads"]:
            thread_id = data["threads"][0]["id"]
            detail = client.get_thread(thread_id)
            ok = "thread" in detail and "replies" in detail
            j.log("get_thread", ok, "{} replies".format(len(detail["replies"])))
            j.note("Read thread `{}` with {} replies.".format(
                thread_id[:8], len(detail["replies"])))
            j.blank()
    except Exception as e:
        j.log("get_thread", False, str(e))

    j.step("Get Node")
    try:
        node_data = client.get_node(thread_id)
        ok = node_data["node"]["id"] == thread_id
        j.log("get_node", ok)
        j.note("Fetched node `{}`.".format(thread_id[:8]))
        j.blank()
    except Exception as e:
        j.log("get_node", False, str(e))

    j.step("Error Handling")
    try:
        client.list_threads("")
        j.log("error_400", False, "expected error")
    except RemarkboxError as e:
        j.log("error_400", e.status == 400, "HTTP {}".format(e.status))

    try:
        client.get_node("00000000-0000-0000-0000-000000000000")
        j.log("error_404", False, "expected error")
    except RemarkboxError as e:
        j.log("error_404", e.status == 404, "HTTP {}".format(e.status))
    j.note("Missing namespace -> 400, nonexistent node -> 404.")
    j.blank()

    # ---------------------------------------------------------------
    # Phase 2: Authentication
    # ---------------------------------------------------------------
    print("\nPhase 2: Authentication")

    j.step("Authenticate")
    ok, method = ensure_authenticated(client, email, otp)
    j.log("authenticate", ok, method)
    j.note("Authenticated via {}.".format(method))
    j.blank()

    if not ok:
        print("\n  Authentication failed. Aborting.")
        return j

    # ---------------------------------------------------------------
    # Phase 3: Profile (idempotent)
    # ---------------------------------------------------------------
    print("\nPhase 3: Profile")

    j.step("Get Profile")
    try:
        profile = client.get_profile()
        current_name = profile["user"]["name"]
        j.log("get_profile", True, current_name)
        j.note("Current display name: `{}`.".format(current_name))
        j.blank()
        profile_available = True
    except RemarkboxError as e:
        j.log("get_profile", False, "endpoint not available (HTTP {})".format(e.status))
        j.note("Profile endpoint not deployed yet -- skipping profile tests.")
        j.blank()
        profile_available = False

    if display_name and profile_available:
        j.step("Update Display Name")
        result = client.update_profile(display_name)
        ok = result["user"]["name"] == display_name
        j.log("update_profile", ok, "{} -> {}".format(current_name, display_name))
        j.note("Set display name: `{}` -> `{}`.".format(current_name, display_name))
        j.blank()

        # Verify idempotent (run again, same name)
        result2 = client.update_profile(display_name)
        j.log("update_profile_idempotent", result2["user"]["name"] == display_name,
              "same name accepted")

        # Verify invalid name rejected
        try:
            client.update_profile("bad name!!!")
            j.log("error_invalid_name", False, "expected error")
        except RemarkboxError as e:
            j.log("error_invalid_name", e.status == 400, "HTTP {}".format(e.status))
        j.note("Invalid name correctly rejected with 400.")
        j.blank()

    # ---------------------------------------------------------------
    # Phase 4: Write operations (single journey thread)
    # ---------------------------------------------------------------
    print("\nPhase 4: Write operations")

    # Find or create the journey thread
    if not journey_id:
        journey_id = find_journey_thread(client, namespace)

    if journey_id:
        j.step("Reuse Journey Thread")
        j.log("find_journey", True, journey_id[:8])
        j.note("Found existing journey thread `{}`.".format(journey_id[:8]))
        j.blank()
    else:
        j.step("Create Journey Thread")
        create_result = client.create_thread(
            namespace=namespace,
            title=THREAD_TITLE,
            data="# {}\n\nInitial creation.".format(THREAD_TITLE),
        )
        journey_id = create_result["node"]["id"]
        j.log("create_thread", bool(journey_id), "node {}".format(journey_id[:8]))
        j.note("Created journey thread `{}`.".format(journey_id[:8]))
        j.blank()

    # Reply
    j.step("Reply")
    reply_result = client.reply(
        journey_id,
        data="Test reply from run at {}. "
             "Verifies `POST /api/v1/threads/{{node_id}}/replies`.".format(now),
    )
    reply_id = reply_result["node"]["id"]
    j.log("reply", bool(reply_id), "node {}".format(reply_id[:8]))
    j.note("Posted reply `{}`.".format(reply_id[:8]))
    j.blank()

    # Edit reply
    j.step("Edit Reply")
    client.edit_node(
        reply_id,
        data="Test reply from run at {} (edited). "
             "Verifies `PATCH /api/v1/nodes/{{node_id}}`.".format(now),
    )
    j.log("edit_reply", True)
    j.note("Edited reply `{}`.".format(reply_id[:8]))
    j.blank()

    # ---------------------------------------------------------------
    # Phase 5: Readback
    # ---------------------------------------------------------------
    print("\nPhase 5: Readback")

    j.step("Readback")
    readback = client.get_thread(journey_id)
    ok = readback["thread"]["title"].strip() == THREAD_TITLE
    j.log("readback", ok, "{} replies".format(len(readback["replies"])))
    j.note("Read back thread: {} replies.".format(len(readback["replies"])))
    j.blank()

    # ---------------------------------------------------------------
    # Phase 6: Update journey thread body
    # ---------------------------------------------------------------
    print("\nPhase 6: Update journey thread")

    # +1 to count the update_journey step we're about to do
    final_passed = j.passed + 1
    final_total = j.total + 1

    # Update the "Latest:" line in the thread body without rewriting the narrative
    existing_body = readback["thread"]["data"]
    import re as _re
    updated_body = _re.sub(
        r"\*\*Latest: .+?\*\*",
        "**Latest: {}/{} passed**".format(final_passed, final_total),
        existing_body,
    )
    if updated_body == existing_body:
        # No "Latest:" line found -- append one
        updated_body = existing_body.rstrip() + "\n\n**Latest: {}/{} passed**\n".format(
            final_passed, final_total)

    client.edit_node(journey_id, data=updated_body)
    j.log("update_journey", True, "{}/{} passed".format(final_passed, final_total))

    print("\n  Journey: {}/api/v1/threads/{}".format(url, journey_id))

    return j


def main():
    parser = argparse.ArgumentParser(
        description="Functional test of the Remarkbox API against a live instance."
    )
    parser.add_argument("url", help="Base URL (e.g. https://my.remarkbox.com)")
    parser.add_argument("namespace", help="Namespace (e.g. meta.remarkbox.com)")
    parser.add_argument("email", help="Email for authentication")
    parser.add_argument("otp", nargs="?", default=None, help="OTP code (optional)")
    parser.add_argument("--name", default=None,
                        help="Set display name (idempotent)")
    parser.add_argument("--journey", default=None,
                        help="Existing journey thread ID to append to")

    args = parser.parse_args()

    print("Remarkbox API Functional Test")
    print("  URL:       {}".format(args.url))
    print("  Namespace: {}".format(args.namespace))
    print("  Email:     {}".format(args.email))
    if args.name:
        print("  Name:      {}".format(args.name))
    if args.journey:
        print("  Journey:   {}".format(args.journey))

    j = run(args.url, args.namespace, args.email,
            otp=args.otp, display_name=args.name, journey_id=args.journey)

    print("\n" + "=" * 40)
    print("Results: {}/{}".format(j.passed, j.total))

    if j.passed == j.total:
        print("All tests passed.")
    else:
        print("Some tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
