"""Command-line interface: kv-store get/set/del/compact."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .store import KVStore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kv-store", description="Persistent key-value store.")
    p.add_argument(
        "--db",
        default=os.environ.get("KV_STORE_PATH", "kv.db"),
        help="path to the log file (default: $KV_STORE_PATH or ./kv.db)",
    )
    sub = p.add_subparsers(dest="command", required=True)
    g = sub.add_parser("get", help="print the value for a key")
    g.add_argument("key")
    s = sub.add_parser("set", help="set a key")
    s.add_argument("key")
    s.add_argument("value")
    s.add_argument("--ttl", type=float, help="seconds until the key expires")
    d = sub.add_parser("del", help="delete a key")
    d.add_argument("key")
    sub.add_parser("compact", help="rewrite the log, dropping dead records")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with KVStore(args.db) as store:
            if args.command == "get":
                value = store.get(args.key)
                if value is None:
                    print(f"key not found: {args.key}", file=sys.stderr)
                    return 1
                sys.stdout.buffer.write(value + b"\n")
                sys.stdout.buffer.flush()
            elif args.command == "set":
                store.set(args.key, args.value.encode("utf-8"), ttl=args.ttl)
            elif args.command == "del":
                if not store.delete(args.key):
                    print(f"key not found: {args.key}", file=sys.stderr)
                    return 1
            elif args.command == "compact":
                print(f"reclaimed {store.compact()} bytes")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
