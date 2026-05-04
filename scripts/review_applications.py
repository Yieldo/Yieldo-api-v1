"""Review queue for wallet + creator applications.

Usage:
    venv/Scripts/python.exe scripts/review_applications.py list
    venv/Scripts/python.exe scripts/review_applications.py list --pending
    venv/Scripts/python.exe scripts/review_applications.py approve <address> wallet
    venv/Scripts/python.exe scripts/review_applications.py approve <address> creator [--note "..."]
    venv/Scripts/python.exe scripts/review_applications.py reject  <address> wallet  [--note "..."]
"""
import asyncio
import argparse
import json
from app.services import database
from app.config import get_settings


async def cmd_list(args):
    settings = get_settings()
    await database.connect(settings.mongodb_url)
    docs = await database.list_applications(
        status="pending" if args.pending else None,
        limit=200,
    )
    if not docs:
        print("(no applications)")
    for d in docs:
        addr = d.get("address")
        aud = d.get("audience")
        status = d.get("status")
        created = d.get("created_at")
        form = d.get("form_data") or {}
        ident = form.get("company") or form.get("handle") or "-"
        email = form.get("email", "-")
        print(f"  [{status:9}] {aud:8} {addr}  {ident}  <{email}>  ({created})")
    await database.disconnect()


async def cmd_approve(args):
    settings = get_settings()
    await database.connect(settings.mongodb_url)
    doc = await database.get_application(args.address, args.audience)
    if not doc:
        print(f"❌ Not found: {args.audience} application for {args.address}")
        return
    print(f"Application:")
    print(json.dumps({k: str(v) for k, v in doc.items() if k != "_id"}, indent=2))
    confirm = input(f"\nApprove this {args.audience} application? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return
    ok = await database.update_application_status(args.address, args.audience, "approved", note=args.note or "")
    print("✓ approved" if ok else "❌ failed")
    await database.disconnect()


async def cmd_reject(args):
    settings = get_settings()
    await database.connect(settings.mongodb_url)
    doc = await database.get_application(args.address, args.audience)
    if not doc:
        print(f"❌ Not found: {args.audience} application for {args.address}")
        return
    confirm = input(f"Reject {args.audience} application for {args.address}? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return
    ok = await database.update_application_status(args.address, args.audience, "rejected", note=args.note or "")
    print("✓ rejected" if ok else "❌ failed")
    await database.disconnect()


def main():
    parser = argparse.ArgumentParser()
    sp = parser.add_subparsers(dest="cmd", required=True)

    p_list = sp.add_parser("list")
    p_list.add_argument("--pending", action="store_true", help="Only pending")
    p_list.set_defaults(func=cmd_list)

    p_app = sp.add_parser("approve")
    p_app.add_argument("address")
    p_app.add_argument("audience", choices=["wallet", "creator"])
    p_app.add_argument("--note", default="")
    p_app.set_defaults(func=cmd_approve)

    p_rej = sp.add_parser("reject")
    p_rej.add_argument("address")
    p_rej.add_argument("audience", choices=["wallet", "creator"])
    p_rej.add_argument("--note", default="")
    p_rej.set_defaults(func=cmd_reject)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
