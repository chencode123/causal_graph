"""Scrape the public CSB completed-investigations catalogue.

The scraper creates a raw, auditable catalogue only. It does not match reports to
the local corpus, apply a study cutoff, or classify reports as included/excluded.

Examples
--------
python scripts/scrape_csb_completed_reports.py
python scripts/scrape_csb_completed_reports.py --refresh --delay 0.5
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment


BASE_URL = "https://www.csb.gov"
CATALOGUE_URL = f"{BASE_URL}/investigations/completed-investigations/?Type=2"
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "csb_completed_catalog"
USER_AGENT = "CSB-corpus-audit/1.0 (academic reproducibility; contact via manuscript)"

DATE_PATTERN = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
INVESTIGATION_NUMBER_PATTERN = re.compile(
    r"\bInvestigation\s+(?:Number|No\.?|ID)\s*[:#]?\s*"
    r"([12]\d{3}-\d{2}-[A-Z]-[A-Z]{2})\b",
    re.IGNORECASE,
)
RECOMMENDATION_NUMBER_PATTERN = re.compile(
    r"\b([12]\d{3}-\d{2}-[A-Z]-[A-Z]{2})-\d+\b",
    re.IGNORECASE,
)


@dataclass
class CatalogueEntry:
    csb_catalogue_id: str
    official_title: str
    detail_page_url: str
    location: str
    accident_date: str
    final_report_release_date: str
    accident_type: str
    investigation_number: str
    investigation_number_basis: str
    investigation_number_candidate: str
    report_type: str
    report_type_basis: str
    primary_final_report_title: str
    primary_final_report_url: str
    primary_final_report_filename: str
    final_report_count: int
    all_final_reports_json: str
    catalogue_page: int
    catalogue_release_date: str
    date_consistency: str
    scrape_status: str
    scrape_notes: str
    scraped_at_utc: str


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def iso_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return ""


def extract_first_date(text: str) -> str:
    match = DATE_PATTERN.search(text)
    return iso_date(match.group(1)) if match else ""


def parse_content_disposition_filename(value: str | None) -> str:
    if not value:
        return ""
    message = Message()
    message["content-disposition"] = value
    return message.get_filename() or ""


class CachedClient:
    def __init__(
        self,
        cache_dir: Path,
        delay: float,
        timeout: float,
        refresh: bool,
    ) -> None:
        self.cache_dir = cache_dir
        self.delay = max(0.0, delay)
        self.timeout = timeout
        self.refresh = refresh
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_html(self, url: str, cache_name: str) -> str:
        path = self.cache_dir / cache_name
        if path.exists() and not self.refresh:
            return path.read_text(encoding="utf-8")

        last_error: requests.RequestException | None = None
        response: requests.Response | None = None
        for attempt in range(2):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(max(self.delay, 0.5))
        if response is None or last_error is not None and not response.ok:
            assert last_error is not None
            raise last_error
        if "html" not in response.headers.get("content-type", "").lower():
            raise ValueError(f"Expected HTML from {url}, received {response.headers.get('content-type')}")
        path.write_text(response.text, encoding="utf-8")
        time.sleep(self.delay)
        return response.text

    def resolve_file_metadata(self, url: str) -> tuple[str, str, str]:
        if not url:
            return "", "", ""
        try:
            response = self.session.get(url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            final_url = response.url
            content_type = response.headers.get("content-type", "")
            filename = parse_content_disposition_filename(
                response.headers.get("content-disposition")
            )
            response.close()
            time.sleep(self.delay)
            return final_url, filename, content_type
        except requests.RequestException as exc:
            return url, "", f"ERROR: {exc}"


def page_number_from_url(url: str) -> int:
    values = parse_qs(urlparse(url).query).get("pg", ["1"])
    try:
        return int(values[0])
    except ValueError:
        return 1


def discover_catalogue_pages(first_html: str) -> list[int]:
    soup = BeautifulSoup(first_html, "html.parser")
    pages = {1}
    for anchor in soup.select('a[href*="completed-investigations"][href*="pg="]'):
        pages.add(page_number_from_url(urljoin(CATALOGUE_URL, anchor.get("href", ""))))
    return sorted(pages)


def parse_catalogue_page(html: str, page_number: int) -> list[dict[str, str | int]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str | int]] = []
    for item in soup.select("#invcont .itemList .item"):
        link = item.select_one('a.linkHd[tt="inv"]') or item.select_one("a.linkHd")
        if link is None:
            continue
        title = clean_text(link.get_text(" ", strip=True))
        href = urljoin(BASE_URL, link.get("href", ""))
        catalogue_id = clean_text(link.get("tid", ""))
        text = clean_text(item.get_text(" ", strip=True))

        location_match = re.search(
            r"Location:\s*(.*?)\s*Final Report Released On:", text, re.IGNORECASE
        )
        release_match = re.search(
            r"Final Report Released On:\s*(\d{1,2}/\d{1,2}/\d{4})",
            text,
            re.IGNORECASE,
        )
        rows.append(
            {
                "csb_catalogue_id": catalogue_id,
                "official_title": title,
                "detail_page_url": href,
                "catalogue_page": page_number,
                "catalogue_location": clean_text(location_match.group(1))
                if location_match
                else "",
                "catalogue_release_date": iso_date(release_match.group(1))
                if release_match
                else "",
            }
        )
    return rows


def labelled_value(details: BeautifulSoup, label: str) -> str:
    for paragraph in details.select("p"):
        text = clean_text(paragraph.get_text(" ", strip=True))
        if text.lower().startswith(label.lower()):
            return clean_text(text[len(label) :])
    return ""


def extract_detail_fields(html: str) -> dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one(".pageHeading h1.title") or soup.select_one("h1")
    official_title = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""

    details = soup.select_one(".imageInfoBlock .details")
    location = ""
    accident_date = ""
    release_date = ""
    accident_type = ""
    if details is not None:
        location = labelled_value(details, "Location:")
        location = re.sub(r"^Location:\s*", "", location, flags=re.IGNORECASE)
        accident_type = labelled_value(details, "Accident Type:")
        date_paragraph = next(
            (
                clean_text(p.get_text(" ", strip=True))
                for p in details.select("p")
                if "Accident Occurred On:" in p.get_text(" ")
            ),
            "",
        )
        accident_match = re.search(
            r"Accident Occurred On:\s*(\d{1,2}/\d{1,2}/\d{4})",
            date_paragraph,
            re.IGNORECASE,
        )
        release_match = re.search(
            r"Final Report Released On:\s*(\d{1,2}/\d{1,2}/\d{4})",
            date_paragraph,
            re.IGNORECASE,
        )
        accident_date = iso_date(accident_match.group(1)) if accident_match else ""
        release_date = iso_date(release_match.group(1)) if release_match else ""

    final_reports: list[dict[str, str]] = []
    final_report_container = soup.select_one('div[id$="_dvFinalReport"]')
    if final_report_container is not None:
        for anchor in final_report_container.select("a[href]"):
            report_title = clean_text(anchor.get_text(" ", strip=True))
            report_url = urljoin(BASE_URL, anchor.get("href", ""))
            if report_title and report_url:
                final_reports.append({"title": report_title, "url": report_url})

    # Older pages store report products in a general Documents block. The
    # document category is embedded in an HTML comment immediately before its
    # list. Only report-like categories are accepted here.
    report_category_pattern = re.compile(
        r"final\s+report|investigation\s+report|case\s+study|"
        r"safety\s+bulletin|safety\s+study|study\s+report",
        re.IGNORECASE,
    )
    for documents_block in soup.select(".documentsBlock .inner"):
        current_category = ""
        for node in documents_block.children:
            if isinstance(node, Comment):
                current_category = clean_text(
                    BeautifulSoup(str(node), "html.parser").get_text(" ", strip=True)
                )
                continue
            if getattr(node, "name", None) != "ul":
                continue
            if not report_category_pattern.search(current_category):
                continue
            for anchor in node.select("a[href]"):
                report_title = clean_text(anchor.get_text(" ", strip=True))
                report_url = urljoin(BASE_URL, anchor.get("href", ""))
                if report_title and report_url:
                    final_reports.append(
                        {
                            "title": report_title,
                            "url": report_url,
                            "category": current_category,
                        }
                    )

    if not final_reports:
        for anchor in soup.select('#mainContent a[href*=".pdf"], #mainContent a[href*=".PDF"]'):
            report_title = clean_text(anchor.get_text(" ", strip=True))
            report_url = urljoin(BASE_URL, anchor.get("href", ""))
            searchable = f"{official_title} {report_title} {report_url}".lower()
            if any(term in searchable for term in ("report", "study", "bulletin")):
                final_reports.append(
                    {
                        "title": report_title or official_title,
                        "url": report_url,
                        "category": "Direct PDF document",
                    }
                )

    deduplicated_reports: list[dict[str, str]] = []
    seen_report_urls: set[str] = set()
    for report in final_reports:
        if report["url"] in seen_report_urls:
            continue
        seen_report_urls.add(report["url"])
        deduplicated_reports.append(report)
    final_reports = deduplicated_reports

    visible_text = clean_text(soup.get_text(" ", strip=True))
    explicit_match = INVESTIGATION_NUMBER_PATTERN.search(visible_text)
    explicit_number = explicit_match.group(1).upper() if explicit_match else ""
    recommendation_prefixes = sorted(
        {match.group(1).upper() for match in RECOMMENDATION_NUMBER_PATTERN.finditer(visible_text)}
    )
    candidate = recommendation_prefixes[0] if len(recommendation_prefixes) == 1 else ""

    return {
        "official_title": official_title,
        "location": location,
        "accident_date": accident_date,
        "release_date": release_date,
        "accident_type": accident_type,
        "investigation_number": explicit_number,
        "investigation_number_basis": "explicit detail-page label" if explicit_number else "not explicitly displayed",
        "investigation_number_candidate": candidate,
        "final_reports": final_reports,
    }


def primary_report_score(report: dict[str, str]) -> tuple[int, int]:
    title = report["title"].lower()
    score = 0
    if "final report" in title:
        score += 30
    if "investigation report" in title:
        score += 20
    if "case study" in title or "safety bulletin" in title or "safety study" in title:
        score += 15
    if any(term in title for term in ("spanish", "español", "appendix", "annex")):
        score -= 50
    if any(term in title for term in ("executive summary", "presentation", "transcript")):
        score -= 20
    return score, -len(title)


def infer_report_type(final_reports: list[dict[str, str]]) -> tuple[str, str]:
    combined = " ".join(
        f"{report.get('category', '')} {report['title']} {report['url']}".lower()
        for report in final_reports
    ).replace("_", "-").replace("-", " ")
    for needle, label in (
        ("case study", "Case Study"),
        ("safety bulletin", "Safety Bulletin"),
        ("safety study", "Safety Study"),
        ("investigation report", "Investigation Report"),
        ("final report", "Final Report"),
    ):
        if needle in combined:
            return label, "derived from CSB final-report link label"
    return "", "not explicitly displayed"


def build_entry(
    row: dict[str, str | int],
    detail: dict[str, object],
    client: CachedClient,
    resolve_file_metadata: bool,
    scraped_at: str,
) -> CatalogueEntry:
    final_reports = list(detail["final_reports"])
    primary = max(final_reports, key=primary_report_score) if final_reports else {"title": "", "url": ""}
    primary_url = primary["url"]
    filename = ""
    notes: list[str] = []
    if resolve_file_metadata and primary_url:
        resolved_url, filename, content_type = client.resolve_file_metadata(primary_url)
        primary_url = resolved_url
        if content_type and "pdf" not in content_type.lower():
            notes.append(f"Primary report returned content type {content_type}")

    detail_date = str(detail["release_date"])
    catalogue_date = str(row["catalogue_release_date"])
    if detail_date and catalogue_date:
        date_consistency = "match" if detail_date == catalogue_date else "mismatch"
    else:
        date_consistency = "incomplete"
    if date_consistency == "mismatch":
        notes.append("Catalogue and detail-page release dates differ")
    if not final_reports:
        notes.append("No final-report link was found in the detail-page Final Reports section")
    if not detail["investigation_number"] and detail["investigation_number_candidate"]:
        notes.append("Investigation-number candidate was derived from recommendation numbers and requires review")

    report_type, report_type_basis = infer_report_type(final_reports)
    status = "ok" if final_reports and date_consistency != "mismatch" else "review"
    return CatalogueEntry(
        csb_catalogue_id=str(row["csb_catalogue_id"]),
        official_title=str(detail["official_title"] or row["official_title"]),
        detail_page_url=str(row["detail_page_url"]),
        location=str(detail["location"] or row["catalogue_location"]),
        accident_date=str(detail["accident_date"]),
        final_report_release_date=detail_date or catalogue_date,
        accident_type=str(detail["accident_type"]),
        investigation_number=str(detail["investigation_number"]),
        investigation_number_basis=str(detail["investigation_number_basis"]),
        investigation_number_candidate=str(detail["investigation_number_candidate"]),
        report_type=report_type,
        report_type_basis=report_type_basis,
        primary_final_report_title=primary["title"],
        primary_final_report_url=primary_url,
        primary_final_report_filename=filename,
        final_report_count=len(final_reports),
        all_final_reports_json=json.dumps(final_reports, ensure_ascii=False),
        catalogue_page=int(row["catalogue_page"]),
        catalogue_release_date=catalogue_date,
        date_consistency=date_consistency,
        scrape_status=status,
        scrape_notes=" | ".join(notes),
        scraped_at_utc=scraped_at,
    )


def write_csv(path: Path, entries: Iterable[CatalogueEntry]) -> None:
    rows = [asdict(entry) for entry in entries]
    if not rows:
        raise ValueError("No catalogue entries were extracted")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_compact_table(path: Path, entries: Iterable[CatalogueEntry]) -> None:
    rows = []
    for entry in entries:
        rows.append(
            {
                "CSB catalogue ID": entry.csb_catalogue_id,
                "Official title": entry.official_title,
                "Investigation number": entry.investigation_number,
                "Investigation number candidate": entry.investigation_number_candidate,
                "Investigation number basis": entry.investigation_number_basis,
                "Accident date": entry.accident_date,
                "Final report release date": entry.final_report_release_date,
                "Report type": entry.report_type,
                "Accident type": entry.accident_type,
                "Detail page URL": entry.detail_page_url,
                "Final report PDF URL": entry.primary_final_report_url,
                "Scrape status": entry.scrape_status,
                "Notes": entry.scrape_notes,
            }
        )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-resolve-file-metadata", action="store_true")
    parser.add_argument("--max-pages", type=int, default=None, help="Testing only")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    raw_dir = output_dir / "raw_html"
    output_dir.mkdir(parents=True, exist_ok=True)
    client = CachedClient(raw_dir, args.delay, args.timeout, args.refresh)
    scraped_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    catalogue_rows: list[dict[str, str | int]] = []
    pages: list[int] = []
    first_html = client.get_html(CATALOGUE_URL, "catalogue_page_01.html")
    page = 1
    while True:
        if args.max_pages is not None and page > args.max_pages:
            break
        url = CATALOGUE_URL if page == 1 else f"{CATALOGUE_URL}&pg={page}"
        html = first_html if page == 1 else client.get_html(url, f"catalogue_page_{page:02d}.html")
        parsed = parse_catalogue_page(html, page)
        if not parsed:
            break
        print(f"Catalogue page {page}: {len(parsed)} entries")
        pages.append(page)
        catalogue_rows.extend(parsed)
        page += 1

    seen_ids: set[str] = set()
    entries: list[CatalogueEntry] = []
    for index, row in enumerate(catalogue_rows, start=1):
        catalogue_id = str(row["csb_catalogue_id"])
        if not catalogue_id or catalogue_id in seen_ids:
            raise ValueError(f"Missing or duplicate CSB catalogue ID: {catalogue_id!r}")
        seen_ids.add(catalogue_id)
        detail_error = ""
        try:
            detail_html = client.get_html(
                str(row["detail_page_url"]), f"detail_{catalogue_id}.html"
            )
            detail = extract_detail_fields(detail_html)
        except (requests.RequestException, ValueError) as exc:
            print_url = f"{row['detail_page_url']}?print=y"
            try:
                detail_html = client.get_html(
                    print_url, f"detail_{catalogue_id}_print.html"
                )
                detail = extract_detail_fields(detail_html)
                detail_error = f"Standard detail page failed; print view was used: {exc}"
            except (requests.RequestException, ValueError) as print_exc:
                detail_error = (
                    f"Detail page could not be fetched: {exc}; "
                    f"print view also failed: {print_exc}"
                )
                detail = {
                    "official_title": str(row["official_title"]),
                    "location": str(row["catalogue_location"]),
                    "accident_date": "",
                    "release_date": str(row["catalogue_release_date"]),
                    "accident_type": "",
                    "investigation_number": "",
                    "investigation_number_basis": "detail page unavailable",
                    "investigation_number_candidate": "",
                    "final_reports": [],
                }
        entry = build_entry(
            row,
            detail,
            client,
            not args.no_resolve_file_metadata,
            scraped_at,
        )
        if detail_error:
            entry.scrape_status = "review"
            entry.scrape_notes = " | ".join(
                part for part in (detail_error, entry.scrape_notes) if part
            )
        entries.append(entry)
        print(f"Detail {index}/{len(catalogue_rows)}: {catalogue_id} {entry.scrape_status}")

    entries.sort(
        key=lambda entry: (entry.final_report_release_date, entry.official_title),
        reverse=True,
    )
    csv_path = output_dir / "csb_completed_reports.csv"
    table_path = output_dir / "CSB_completed_reports_table.csv"
    json_path = output_dir / "csb_completed_reports.json"
    write_csv(csv_path, entries)
    write_compact_table(table_path, entries)
    json_path.write_text(
        json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    review_count = sum(entry.scrape_status != "ok" for entry in entries)
    summary = {
        "source_url": CATALOGUE_URL,
        "scraped_at_utc": scraped_at,
        "catalogue_pages": pages,
        "entry_count": len(entries),
        "review_count": review_count,
        "csv_path": str(csv_path),
        "table_path": str(table_path),
        "json_path": str(json_path),
    }
    (output_dir / "scrape_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
