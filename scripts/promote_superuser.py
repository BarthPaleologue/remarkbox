#!/usr/bin/env python3
"""
Promote or demote a user to/from superuser status.

This is a direct database script for bootstrapping the first superuser.
After that, use the /topsecret/users web UI to manage superusers.

Usage:
    python scripts/promote_superuser.py --ini development.ini --email user@example.com
    python scripts/promote_superuser.py --ini development.ini --email user@example.com --demote
"""

import argparse
import sys

from pyramid.paster import bootstrap


def main():
    parser = argparse.ArgumentParser(description="Promote/demote superuser")
    parser.add_argument("--ini", required=True, help="Path to .ini config file")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument("--demote", action="store_true", help="Demote instead of promote")
    args = parser.parse_args()

    env = bootstrap(args.ini)
    request = env["request"]
    dbsession = request.dbsession

    from remarkbox.models.user import get_user_by_email

    user = get_user_by_email(dbsession, args.email)
    if user is None:
        print("No user found with email: {}".format(args.email), file=sys.stderr)
        sys.exit(1)

    if args.demote:
        user.is_superuser = False
        dbsession.add(user)
        import transaction
        transaction.commit()
        print("Demoted {} ({}) from superuser.".format(user.name, user.email))
    else:
        user.is_superuser = True
        dbsession.add(user)
        import transaction
        transaction.commit()
        print("Promoted {} ({}) to superuser.".format(user.name, user.email))

    env["closer"]()


if __name__ == "__main__":
    main()
