"""Platform-neutral command line and fbvw:// URI contract.

Win32 registry, mutex and pipe operations belong in platform adapters.  This
module only validates/normalises payloads so the application never executes
untrusted command strings.
"""

from dataclasses import dataclass
import argparse
import urllib.parse
from typing import Iterable


@dataclass(frozen=True, slots=True)
class LaunchRequest:
    action: str = "play"
    items: tuple[str, ...] = ()
    privacy: bool = False
    no_focus: bool = False


def parse_fbvw_uri(value: str) -> LaunchRequest:
    parsed = urllib.parse.urlparse(str(value).strip())
    if parsed.scheme.lower() != "fbvw" or parsed.netloc.lower() not in {"play", "queue"}:
        raise ValueError("URI fbvw không hợp lệ")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    urls = tuple(item.strip() for item in query.get("url", ()) if item.strip())
    if not urls:
        raise ValueError("URI fbvw thiếu tham số url")
    if any(not (item.startswith(("http://", "https://", "file:///")) or len(item) > 2 and item[1] == ":") for item in urls):
        raise ValueError("URI fbvw chứa input không được hỗ trợ")
    return LaunchRequest(
        action="queue" if parsed.netloc.lower() == "queue" else "play",
        items=urls,
        privacy=query.get("privacy", ("0",))[0].lower() in {"1", "true", "yes"},
    )


def parse_launch_args(argv: Iterable[str]) -> LaunchRequest:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("items", nargs="*")
    parser.add_argument("--add-to-queue", action="store_true")
    parser.add_argument("--play-now", action="store_true")
    parser.add_argument("--privacy", action="store_true")
    parser.add_argument("--no-focus", action="store_true")
    args, _unknown = parser.parse_known_args(list(argv))
    items = tuple(item.strip() for item in args.items if item.strip())
    if len(items) == 1 and items[0].lower().startswith("fbvw://"):
        uri_request = parse_fbvw_uri(items[0])
        return LaunchRequest(
            action=uri_request.action,
            items=uri_request.items,
            privacy=args.privacy or uri_request.privacy,
            no_focus=args.no_focus or uri_request.no_focus,
        )
    return LaunchRequest(
        action="queue" if args.add_to_queue and not args.play_now else "play",
        items=items,
        privacy=args.privacy,
        no_focus=args.no_focus,
    )

