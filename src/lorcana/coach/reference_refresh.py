"""Discover official English references and prepare a reviewable, immutable bundle."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit

import requests

from lorcana.coach.rules import digest, load_bundle

RESOURCES_URL = "https://www.disneylorcana.com/en-US/resources"


def document_kind(title: str) -> str | None:
    title = title.casefold().strip()
    if title == "comprehensive rules":
        return "comprehensive_rules"
    if title == "tournament rules":
        return "tournament_rules"
    if title.endswith((" set notes", " set release notes")):
        return "set_release_notes"
    return None


def identity(document: dict) -> str:
    kind = document["kind"]
    if kind != "set_release_notes":
        return kind
    title = re.sub(r"\s+set (?:release )?notes$", "", document["title"], flags=re.I)
    return "SET:" + re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.heading = ""
        self.heading_parts = None
        self.link = None
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag in {"h1", "h2"}:
            self.heading_parts = []
        elif tag == "a":
            self.link = {"href": dict(attrs).get("href", ""), "text": []}

    def handle_data(self, data):
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        if self.link is not None:
            self.link["text"].append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2"} and self.heading_parts is not None:
            self.heading = " ".join("".join(self.heading_parts).split())
            self.heading_parts = None
        elif tag == "a" and self.link is not None:
            kind = document_kind(self.heading)
            language = "".join(self.link["text"]).strip().casefold()
            if kind and language == "english":
                url = urljoin(RESOURCES_URL, self.link["href"])
                parsed = urlsplit(url)
                if parsed.scheme != "https" or parsed.hostname != "files.disneylorcana.com" or not parsed.path.lower().endswith(".pdf"):
                    raise ValueError("Expected an official HTTPS PDF link for " + self.heading)
                self.documents.append({"title": self.heading, "kind": kind, "source_url": url})
            self.link = None


def discover(html: str) -> list[dict]:
    parser = ResourceParser()
    parser.feed(html)
    documents = {}
    for document in parser.documents:
        key = identity(document)
        if key in documents and documents[key] != document:
            raise ValueError("Ambiguous official resource: " + key)
        documents[key] = document
    kinds = {d["kind"] for d in documents.values()}
    if kinds != {"comprehensive_rules", "tournament_rules", "set_release_notes"}:
        raise ValueError("Official resource discovery incomplete; inspect the page layout")
    return list(documents.values())


def fetch(session, url: str) -> bytes:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    parsed = urlsplit(response.url)
    expected_host = urlsplit(url).hostname
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise ValueError("Unexpected reference download redirect")
    return response.content


def check_sources(baseline: dict, session) -> tuple[list[dict], dict]:
    documents = discover(fetch(session, RESOURCES_URL).decode("utf-8"))
    previous = {identity(d): d for d in baseline.get("documents", {}).values()}
    changes = {"new": [], "changed": [], "unchanged": [], "no_longer_listed": []}
    for document in documents:
        raw = fetch(session, document["source_url"])
        if not raw.startswith(b"%PDF-"):
            raise ValueError("Reference is not a PDF: " + document["source_url"])
        document["pdf"] = raw
        document["source_sha256"] = hashlib.sha256(raw).hexdigest()
        old = previous.get(identity(document))
        status = "new" if old is None else "unchanged" if old["source_sha256"] == document["source_sha256"] and old["source_url"] == document["source_url"] else "changed"
        changes[status].append(document["title"])
    present = {identity(d) for d in documents}
    changes["no_longer_listed"] = [d["title"] for key, d in previous.items() if key not in present]
    return documents, changes


def extract_pages(raw: bytes) -> list[str]:
    from pypdf import PdfReader
    pages = [(p.extract_text() or "").strip() for p in PdfReader(io.BytesIO(raw)).pages]
    if not pages or any(not p for p in pages):
        raise ValueError("Unreadable/empty PDF page; inspect extraction")
    return pages


def build_bundle(baseline: dict, sources: list[dict], checked_on: str) -> dict:
    checked = date.fromisoformat(checked_on)
    if checked > date.today():
        raise ValueError("Reference check date cannot be in the future")
    documents, citations = {}, {}
    old_documents = baseline.get("documents", {})
    previous = {identity(d): (key, d) for key, d in old_documents.items()}
    for source in sources:
        stable_id = identity(source)
        old_id, old = previous.get(stable_id, (None, {}))
        if old.get("source_sha256") == source["source_sha256"]:
            pages = [c["text"] for c in sorted(
                (c for c in baseline["citations"].values() if c.get("document_id") == old_id),
                key=lambda c: c["page"])]
        else:
            pages = extract_pages(source["pdf"])
        if not pages:
            raise ValueError("Reference has no pages")
        document = {k: v for k, v in source.items() if k != "pdf"}
        document.update(checked_on=checked_on, effective_from=None,
                        historical_applicability="Not verified; may describe changes to older rules.")
        if source["kind"] == "comprehensive_rules":
            version = re.search(r"Version\s+(\d+(?:\.\d+)+)", pages[0])
            effective = re.search(r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", pages[0])
            if not version or not effective:
                raise ValueError("Review the comprehensive rules cover: version/date not recognized")
            day = datetime.strptime(effective[1], "%B %d, %Y").date()
            if day > checked:
                raise ValueError("Comprehensive rules are not effective yet")
            document.update(version=version[1], effective_from=day.isoformat())
            key = "CR:" + version[1]
        elif source["kind"] == "tournament_rules":
            effective = re.search(r"Effective\s+(\d{2}/\d{2}/\d{4})", pages[0], re.I)
            if not effective:
                raise ValueError("Review tournament rules cover: effective date not recognized")
            day = datetime.strptime(effective[1], "%m/%d/%Y").date()
            if day > checked:
                raise ValueError("Tournament rules are not effective yet")
            document["effective_from"] = day.isoformat()
            key = "TR:" + day.isoformat()
        else:
            key = stable_id
        documents[key] = document
        for number, page in enumerate(pages, 1):
            citations[f"{key}:p{number}"] = {"document_id": key, "page": number, "text": page}
    # Preserve older set notes if removed from the landing page, clearly marked.
    present = {identity(d) for d in sources}
    for key, old in old_documents.items():
        if old["kind"] == "set_release_notes" and identity(old) not in present:
            documents[key] = {**old, "currently_listed": False}
            citations.update({k: v for k, v in baseline["citations"].items() if v.get("document_id") == key})
    core = next(d for d in documents.values() if d["kind"] == "comprehensive_rules")
    data = {"schema_version": 2, "version": core["version"], "source_url": core["source_url"],
            "source_sha256": core["source_sha256"], "effective_from": core["effective_from"],
            "verified_through": checked_on, "documents": documents, "citations": citations,
            "scope": "Current-reference coaching: comprehensive rules, available set notes, and tournament rules. Historical applicability and complete errata coverage are not verified."}
    return {**data, "bundle_sha256": digest(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, help="Defaults to packaged references")
    parser.add_argument("--output", type=Path, help="New bundle to review; never overwrites an existing file")
    parser.add_argument("--checked-on", default=date.today().isoformat())
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output already exists; use a new filename")
    baseline = load_bundle(args.baseline)
    with requests.Session() as session:
        sources, changes = check_sources(baseline, session)
    print(json.dumps(changes, indent=2))
    if args.output:
        result = build_bundle(baseline, sources, args.checked_on)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"Prepared {args.output}. Review the changes, commit the bundle, and deploy to activate.")
        print("Suggested analyzer generation: references-" + result["bundle_sha256"][:16])


if __name__ == "__main__":
    main()
