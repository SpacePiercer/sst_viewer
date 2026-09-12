"""Account admin for sst_viewer. Run it on the machine that hosts the app.

    python scripts/users.py list
    python scripts/users.py add georgii
    python scripts/users.py passwd polina
    python scripts/users.py remove konstantin

The password is always typed at a getpass prompt, never passed as an argument:
a command line ends up in shell history, in `ps`, and in log files. It is
stored as a salted scrypt hash, so nobody -- including whoever runs this
script -- can read it back out of users.json afterwards.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auth as AU  # noqa: E402


def _ask_new_password(who):
    first = getpass.getpass(f"new password for {who}: ")
    if len(first) < 8:
        sys.exit("password must be at least 8 characters")
    if first != getpass.getpass("repeat: "):
        sys.exit("passwords do not match")
    return first


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for cmd in ("add", "passwd", "remove"):
        sub.add_parser(cmd).add_argument("name")
    args = ap.parse_args()

    try:
        if args.cmd == "list":
            users = AU.list_users()
            print("\n".join(users) if users else "(no accounts yet)")
            print(f"\n{AU.USERS_FILE}")
        elif args.cmd == "add":
            AU.add_user(args.name, _ask_new_password(args.name))
            print(f"created {args.name}; data goes to {AU.user_dir(args.name)}")
        elif args.cmd == "passwd":
            AU.set_password(args.name, _ask_new_password(args.name))
            print(f"password changed for {args.name}")
        elif args.cmd == "remove":
            if input(f"remove account {args.name}? their files are kept. [y/N] ").lower() != "y":
                sys.exit("cancelled")
            AU.remove_user(args.name)
            print(f"removed {args.name}")
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
