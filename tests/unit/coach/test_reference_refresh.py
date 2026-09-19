import hashlib
import pytest
from lorcana.coach import reference_refresh as refresh


def html(extra=""):
    return '''<h2>Comprehensive Rules</h2><a href="https://files.disneylorcana.com/cr.pdf">English</a>
    <a href="https://files.disneylorcana.com/de.pdf">Deutsch</a>
    <h2>Tournament Rules</h2><a href="https://files.disneylorcana.com/tr.pdf">ENGLISH</a>
    <h2>Fabled Set Notes</h2><a href="https://files.disneylorcana.com/set.pdf"><span>English</span></a>''' + extra


def test_discovers_new_sets_and_excludes_unrelated_formats_and_languages():
    documents = refresh.discover(html('''<h2>New Set Set Notes</h2>
        <a href="https://files.disneylorcana.com/new.pdf">English</a>
        <h2>Pack Rush Rules</h2><a href="https://files.disneylorcana.com/pack.pdf">English</a>'''))
    assert len(documents) == 4
    assert documents[-1]["title"] == "New Set Set Notes"
    assert all("de.pdf" not in d["source_url"] for d in documents)


@pytest.mark.parametrize("content", ["<h2>Unavailable</h2>", html().replace("files.disneylorcana.com/cr", "example.com/cr")])
def test_incomplete_or_untrusted_discovery_is_an_error(content):
    with pytest.raises(ValueError):
        refresh.discover(content)


def test_hash_check_detects_changed_bytes_at_same_url(monkeypatch):
    docs = refresh.discover(html())
    baseline = {"documents": {str(i): {**d, "source_sha256": hashlib.sha256(b"%PDF-old").hexdigest()} for i,d in enumerate(docs)}}
    monkeypatch.setattr(refresh, "fetch", lambda session, url: html().encode() if url == refresh.RESOURCES_URL else b"%PDF-new" if url.endswith("tr.pdf") else b"%PDF-old")
    sources, changes = refresh.check_sources(baseline, object())
    assert changes["changed"] == ["Tournament Rules"]
    assert len(changes["unchanged"]) == 2
    assert changes["new"] == []


def test_build_uses_document_effective_dates_and_preserves_unlisted_guides(monkeypatch):
    def pages(raw):
        return {b"cr": ["Version 2.2.0 July 9, 2026"], b"tr": ["Tournament Rules Effective 07/14/2026"], b"set": ["Set text"]}[raw]
    monkeypatch.setattr(refresh, "extract_pages", pages)
    sources = refresh.discover(html())
    for d, raw in zip(sources, [b"cr", b"tr", b"set"]):
        d.update(pdf=raw, source_sha256=hashlib.sha256(raw).hexdigest())
    old = {"documents": {"SET:older": {"kind":"set_release_notes", "title":"Older Set Notes", "source_sha256":"old"}},
           "citations": {"SET:older:p1": {"document_id":"SET:older", "page":1, "text":"Old notes"}}}
    bundle = refresh.build_bundle(old, sources, "2026-09-19")
    assert bundle["effective_from"] == "2026-07-09"
    assert bundle["documents"]["TR:2026-07-14"]["effective_from"] == "2026-07-14"
    assert bundle["documents"]["SET:older"]["currently_listed"] is False
    assert "SET:older:p1" in bundle["citations"]
    assert bundle["documents"]["SET:fabled"]["effective_from"] is None


def test_build_rejects_unrecognized_cover_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(refresh, "extract_pages", lambda raw: ["Unrecognized cover"])
    source = {"title":"Comprehensive Rules", "kind":"comprehensive_rules", "source_url":"https://files.disneylorcana.com/cr.pdf", "source_sha256":"new", "pdf":b"test"}
    with pytest.raises(ValueError, match="cover"):
        refresh.build_bundle({"documents":{}}, [source], "2026-09-19")
