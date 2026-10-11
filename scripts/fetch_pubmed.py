"""Fetch the newest PubMed papers for one affiliation and save them to data/papers.json.

Runs every day on GitHub Actions. Uses only Python's standard library.
"""
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# ---- Settings you can change -------------------------------------------
AFFILIATION = "Gulf Medical University"   # the name PubMed should look for
HOW_MANY = 8                               # number of papers to show
OUTPUT = Path("data/papers.json")
# ------------------------------------------------------------------------

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
COMMON = {"tool": "research-highlights-demo"}


def get(endpoint, params):
    url = BASE + endpoint + "?" + urllib.parse.urlencode({**COMMON, **params})
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def text_of(element):
    """All the text inside an XML element, including text inside italics etc."""
    return "".join(element.itertext()).strip() if element is not None else ""


def parse_date(article):
    pub = article.find(".//Journal/JournalIssue/PubDate")
    if pub is None:
        return ""
    year, month, day = pub.findtext("Year"), pub.findtext("Month"), pub.findtext("Day")
    if year:
        return " ".join(part for part in [month, day + "," if day and month else None, year] if part)
    return pub.findtext("MedlineDate") or ""


def parse_paper(node):
    article = node.find(".//Article")
    pmid = node.findtext(".//PMID")
    abstract = []
    for part in article.findall(".//Abstract/AbstractText"):
        label = part.get("Label")
        body = text_of(part)
        if body:
            abstract.append(f"{label.capitalize()}: {body}" if label else body)
    authors = []
    for author in article.findall(".//AuthorList/Author"):
        last, initials = author.findtext("LastName"), author.findtext("Initials")
        if last:
            authors.append(f"{last} {initials}".strip() if initials else last)
    doi = ""
    for item in node.findall(".//ArticleIdList/ArticleId"):
        if item.get("IdType") == "doi":
            doi = (item.text or "").strip()
            break
    return {
        "pmid": pmid,
        "title": text_of(article.find("ArticleTitle")).rstrip("."),
        "abstract": abstract,
        "journal": article.findtext(".//Journal/Title") or "",
        "date": parse_date(article),
        "authors": authors,
        "doi": doi,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }


def main():
    search = json.loads(get("esearch.fcgi", {
        "db": "pubmed",
        "term": f'"{AFFILIATION}"[Affiliation]',
        "sort": "pub_date",
        "retmax": HOW_MANY * 2,   # ask for extra, some have no abstract
        "retmode": "json",
    }))
    ids = search["esearchresult"]["idlist"]
    print(f"PubMed returned {len(ids)} paper IDs")
    if not ids:
        raise SystemExit("No papers found. Keeping the existing file.")

    time.sleep(1)  # be polite to PubMed
    xml = get("efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    root = ET.fromstring(xml)

    papers = []
    for node in root.findall("PubmedArticle"):
        paper = parse_paper(node)
        if paper["title"] and paper["abstract"]:
            papers.append(paper)
    papers = papers[:HOW_MANY]
    print(f"Keeping {len(papers)} papers that have an abstract")

    old = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    if old.get("papers") == papers:
        print("Nothing new today.")
        return

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "affiliation": AFFILIATION,
        "papers": papers,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {OUTPUT}")


if __name__ == "__main__":
    main()
