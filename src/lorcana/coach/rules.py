"""Pinned official rules references; citation validation is not a legality engine."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

OFFICIAL_RULES_URL = "https://files.disneylorcana.com/Comprehensive-Rules_2.2.0-EN.pdf"


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_bundle(path: Path | None) -> dict | None:
    if path is None:
        return None
    data = json.loads(path.read_text())
    expected = data.pop("bundle_sha256", None)
    if digest(data) != expected:
        raise ValueError("Rules bundle checksum mismatch")
    start, end = date.fromisoformat(data["effective_from"]), date.fromisoformat(data["verified_through"])
    if end < start or not data.get("citations"):
        raise ValueError("Rules bundle has invalid coverage")
    parsed = urlsplit(data["source_url"])
    if parsed.scheme != "https" or parsed.hostname != "files.disneylorcana.com":
        raise ValueError("Rules source must be the official Disney Lorcana document host")
    for citation in data["citations"].values():
        if not isinstance(citation.get("text"), str) or not citation["text"].strip():
            raise ValueError("Rules reference has an empty passage")
    return {**data, "bundle_sha256": expected}


def for_game(bundle: dict | None, played_at: str | None) -> dict:
    if bundle is None:
        return {"status": "unavailable", "citations": {}}
    try:
        played = date.fromisoformat(str(played_at)[:10])
    except ValueError:
        return {"status": "game_date_unknown", "citations": {}}
    if not date.fromisoformat(bundle["effective_from"]) <= played <= date.fromisoformat(bundle["verified_through"]):
        return {"status": "outside_verified_dates", "citations": {}}
    return {**bundle, "status": "available"}


def import_pdf(pdf: bytes, *, source_url: str, version: str, effective_from: str, verified_through: str) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf))
    pages = [page.extract_text() or "" for page in reader.pages]
    if not pages or any(not page.strip() for page in pages):
        raise ValueError("PDF has empty/unreadable pages; review extraction before importing")
    if f"Version {version}" not in pages[0]:
        raise ValueError("PDF version does not match requested rules version")
    effective = date.fromisoformat(effective_from)
    expected_date = f"{effective.strftime('%B')} {effective.day}, {effective.year}"
    if expected_date not in pages[0]:
        raise ValueError("PDF effective date does not match requested effective date")
    data = {
        "schema_version": 1, "version": version, "source_url": source_url,
        "source_sha256": hashlib.sha256(pdf).hexdigest(),
        "effective_from": effective_from, "verified_through": verified_through,
        "scope": "Comprehensive Rules only; set-specific rulings and errata require separate review",
        "citations": {f"CR:{version}:p{i}": {"page": i, "text": text.strip()}
                      for i, text in enumerate(pages, 1)},
    }
    return {**data, "bundle_sha256": digest(data)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a reviewed official rules PDF into an immutable bundle")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--source-url", default=OFFICIAL_RULES_URL)
    parser.add_argument("--version", required=True)
    parser.add_argument("--effective-from", required=True)
    parser.add_argument("--verified-through", required=True,
                        help="Last game date for which an operator verified this reference applies")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bundle = import_pdf(args.pdf.read_bytes(), source_url=args.source_url, version=args.version,
                        effective_from=args.effective_from, verified_through=args.verified_through)
    # Validate metadata before writing; never overwrite an existing reference.
    if date.fromisoformat(args.verified_through) < date.fromisoformat(args.effective_from):
        parser.error("verified-through precedes effective-from")
    if urlsplit(args.source_url).hostname != "files.disneylorcana.com" or not args.source_url.startswith("https://"):
        parser.error("source-url must use the official HTTPS document host")
    with args.output.open("x") as handle:
        json.dump(bundle, handle, ensure_ascii=False, indent=2)
    print(f"Rules bundle: {args.output}; {len(bundle['citations'])} pages; SHA-256: {bundle['bundle_sha256']}")


if __name__ == "__main__":
    main()
