"""Fetch the newest PubMed papers for one affiliation and save them to data/papers.json.

Runs every day on GitHub Actions. Uses only Python's standard library.
"""
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# ---- Settings you can change -------------------------------------------
AFFILIATION = "Gulf Medical University"   # the name PubMed should look for
HOW_MANY = 30                               # number of papers to show
OUTPUT = Path("data/papers.json")

# Subjects shown as filters on the page. A paper gets the subject whose words
# appear most often in its title, keywords and abstract. To add a subject, add
# a line. To improve the sorting, add words to a line. Words are matched from
# their start, so "cancer" also matches "cancers" and "diabet" matches "diabetes".
TOPICS = {
    "Medical education": ["medical education", "medical student", "curricul", "simulation-based", "teaching", "learner", "undergraduate", "residency training", "assessment of students", "interprofessional education"],
    "Cancer research": ["cancer", "tumor", "tumour", "carcinoma", "oncolog", "neoplas", "leukemia", "leukaemia", "lymphoma", "metasta", "chemotherap"],
    "Diabetes and metabolism": ["diabet", "insulin", "glycemi", "glycaemi", "glycation", "obesity", "metabolic syndrome", "adipokine", "myokine", "thyroid", "testosterone"],
    "Heart and circulation": ["cardiac", "cardio", "coronary", "stent", "heart", "hypertens", "myocardial", "stroke", "atrial", "vascular"],
    "Mental health": ["mental health", "depress", "anxiety", "psycholog", "psychiatr", "nightmare", "addiction", "stress", "well-being", "wellbeing", "burnout"],
    "Infectious disease": ["infect", "antibiotic", "antimicrobial", "bacteri", "virus", "viral", "covid", "sars-cov", "tubercul", "vaccin", "pathogen"],
    "Dentistry and oral health": ["dental", "dentist", "oral health", "intraoral", "prosthodont", "periodont", "endodont", "orthodont", "tooth", "teeth", "implant"],
    "Reproductive health": ["sperm", "fertil", "pregnan", "reproduct", "obstetric", "gynecolog", "gynaecolog", "ovarian", "neonat", "maternal"],
    "Surgery and anaesthesia": ["surg", "anaesthe", "anesthe", "perioperative", "postoperative", "neuraxial", "operative"],
    "Pharmacy and drug research": ["pharmac", "drug discovery", "drug delivery", "formulation", "nanoparticle", "medication adherence", "prescri"],
    "Brain and nervous system": ["neuro", "brain", "alzheimer", "parkinson", "epilep", "cognitive", "dementia", "pain"],
    "Public health": ["public health", "prevalence", "epidemiolog", "population-based", "cross-sectional", "health policy", "ageism", "community", "survey"],
}
OTHER_TOPIC = "Other research"
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


def count_hits(words, text):
    return sum(len(re.findall(r"\b" + re.escape(word), text)) for word in words)


def classify(title, keywords, abstract):
    """Pick the subject whose words appear most. The title counts most, then keywords."""
    title, keywords, abstract = title.lower(), " ; ".join(keywords).lower(), " ".join(abstract).lower()
    best, best_score = OTHER_TOPIC, 0
    for topic, words in TOPICS.items():
        score = 5 * count_hits(words, title) + 3 * count_hits(words, keywords) + count_hits(words, abstract)
        if score > best_score:
            best, best_score = topic, score
    return best


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
    title = text_of(article.find("ArticleTitle")).rstrip(".")
    keywords = [text_of(k) for k in node.findall(".//MeshHeading/DescriptorName")]
    keywords += [text_of(k) for k in node.findall(".//KeywordList/Keyword")]
    return {
        "pmid": pmid,
        "title": title,
        "topic": classify(title, keywords, abstract),
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
