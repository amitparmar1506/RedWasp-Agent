import argparse
import csv
import json
import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import error, parse, request, robotparser


DEFAULT_INPUT = Path("marketing/texas_top_100_restaurants_contacts_seed.csv")
DEFAULT_OUTPUT = Path("marketing/texas_top_100_restaurants_enriched.csv")
GOOGLE_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.+-])", re.I)
PHONE_RE = re.compile(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
BAD_EMAIL_PARTS = (
    "example.com",
    "sentry.io",
    "wixpress.com",
    "domain.com",
    "your-email",
    "email.com",
)
CONTACT_PATH_HINTS = (
    "/contact",
    "/contact-us",
    "/about",
    "/locations",
    "/visit",
    "/private-events",
    "/events",
)


@dataclass
class PlaceMatch:
    name: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    google_maps_url: str = ""
    rating: str = ""
    review_count: str = ""
    business_status: str = ""
    confidence: str = "unmatched"


class LinkAndTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[str] = []
        self.text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value for key, value in attrs if value}
        href = attr_map.get("href")
        if href:
            self.links.append(href)

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if cleaned:
            self.text_parts.append(cleaned)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def http_json(url: str, headers: Dict[str, str], payload: Dict[str, object], timeout: int = 25) -> Dict[str, object]:
    req = request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_text(url: str, timeout: int = 18) -> str:
    req = request.Request(
        url=url,
        headers={
            "User-Agent": "MITEXLeadResearch/1.0 (+business-contact-research)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return ""
        raw = response.read(500_000)
    return raw.decode("utf-8", errors="ignore")


def normalize_domain(url: str) -> str:
    parsed = parse.urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def same_site(base_url: str, candidate_url: str) -> bool:
    return normalize_domain(base_url) == normalize_domain(candidate_url)


def can_fetch(url: str) -> bool:
    parsed = parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch("MITEXLeadResearch/1.0", url)
    except Exception:
        return True


def clean_email(email: str) -> str:
    return email.strip().strip(".,;:()[]{}<>").lower()


def valid_email(email: str) -> bool:
    lowered = email.lower()
    if any(part in lowered for part in BAD_EMAIL_PARTS):
        return False
    if lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")):
        return False
    return True


def extract_emails(text: str) -> List[str]:
    found = []
    seen = set()
    for match in EMAIL_RE.findall(text):
        email = clean_email(match)
        if email not in seen and valid_email(email):
            seen.add(email)
            found.append(email)
    return found


def extract_phone(text: str) -> str:
    match = PHONE_RE.search(text)
    return match.group(0).strip() if match else ""


def parse_html(html: str) -> LinkAndTextParser:
    parser = LinkAndTextParser()
    parser.feed(html)
    return parser


def candidate_contact_urls(base_url: str, html: str) -> List[str]:
    parsed_base = parse.urlparse(base_url)
    root = f"{parsed_base.scheme}://{parsed_base.netloc}"
    parser = parse_html(html)
    candidates = [base_url]

    for href in parser.links:
        absolute = parse.urljoin(base_url, href)
        if not same_site(base_url, absolute):
            continue
        lowered = parse.urlparse(absolute).path.lower()
        if any(hint in lowered for hint in CONTACT_PATH_HINTS):
            candidates.append(absolute)

    for hint in CONTACT_PATH_HINTS:
        candidates.append(parse.urljoin(root, hint))

    deduped = []
    seen = set()
    for url in candidates:
        clean = url.split("#", 1)[0]
        if clean not in seen:
            seen.add(clean)
            deduped.append(clean)
    return deduped[:8]


def search_google_place(api_key: str, restaurant_name: str, city: str, state: str) -> PlaceMatch:
    query = f"{restaurant_name} restaurant {city} {state}"
    field_mask = ",".join(
        [
            "places.displayName",
            "places.formattedAddress",
            "places.nationalPhoneNumber",
            "places.websiteUri",
            "places.googleMapsUri",
            "places.rating",
            "places.userRatingCount",
            "places.businessStatus",
        ]
    )
    data = http_json(
        GOOGLE_TEXT_SEARCH_URL,
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": field_mask,
        },
        payload={
            "textQuery": query,
            "includedType": "restaurant",
            "regionCode": "US",
            "pageSize": 3,
        },
    )

    places = data.get("places", [])
    if not isinstance(places, list) or not places:
        return PlaceMatch()

    first = places[0]
    if not isinstance(first, dict):
        return PlaceMatch()

    name = (first.get("displayName") or {}).get("text", "") if isinstance(first.get("displayName"), dict) else ""
    address = str(first.get("formattedAddress", ""))
    confidence = "high" if restaurant_name.lower().split()[0] in name.lower() and city.lower() in address.lower() else "review"

    return PlaceMatch(
        name=name,
        address=address,
        phone=str(first.get("nationalPhoneNumber", "")),
        website=str(first.get("websiteUri", "")),
        google_maps_url=str(first.get("googleMapsUri", "")),
        rating=str(first.get("rating", "")),
        review_count=str(first.get("userRatingCount", "")),
        business_status=str(first.get("businessStatus", "")),
        confidence=confidence,
    )


def enrich_from_website(website: str, delay_seconds: float) -> Tuple[str, str, List[str]]:
    if not website:
        return "", "", []
    if not website.startswith(("http://", "https://")):
        website = f"https://{website}"
    if not can_fetch(website):
        return "", "", ["robots_blocked"]

    visited = []
    emails: List[str] = []
    fallback_phone = ""

    try:
        home_html = http_text(website)
    except (error.URLError, TimeoutError, ValueError):
        return "", "", ["site_unreachable"]

    for url in candidate_contact_urls(website, home_html):
        if not can_fetch(url):
            visited.append(f"{url} robots_blocked")
            continue
        try:
            html = home_html if url == website else http_text(url)
        except (error.URLError, TimeoutError, ValueError):
            visited.append(f"{url} failed")
            continue

        parser = parse_html(html)
        text = " ".join(parser.text_parts)
        page_emails = extract_emails(html + " " + text)
        for email in page_emails:
            if email not in emails:
                emails.append(email)

        if not fallback_phone:
            fallback_phone = extract_phone(text)

        visited.append(url)
        if emails:
            break
        time.sleep(delay_seconds)

    return ";".join(emails), fallback_phone, visited


def read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as file_obj:
        return list(csv.DictReader(file_obj))


def write_rows(path: Path, rows: List[Dict[str, str]], fieldnames: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def enrich_rows(rows: List[Dict[str, str]], limit: int, delay_seconds: float) -> List[Dict[str, str]]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is required. Add it to .env or your shell environment.")

    enriched = []
    for index, row in enumerate(rows[:limit], start=1):
        name = row.get("restaurant_name", "")
        city = row.get("city", "")
        state = row.get("state", "TX")
        print(f"[{index}/{min(limit, len(rows))}] Enriching {name} - {city}, {state}")

        place = search_google_place(api_key, name, city, state)
        website = row.get("website") or place.website
        email, website_phone, visited = enrich_from_website(website, delay_seconds)
        phone = row.get("phone_number") or place.phone or website_phone

        updated = {
            **row,
            "phone_number": phone,
            "website": website,
            "email_address": row.get("email_address") or email,
            "google_maps_url": place.google_maps_url,
            "address": place.address,
            "rating": place.rating,
            "review_count": place.review_count,
            "business_status": place.business_status,
            "match_name": place.name,
            "match_confidence": place.confidence,
            "website_pages_checked": " | ".join(visited),
            "verification_status": "enriched_review_needed" if place.confidence == "review" else "enriched",
        }
        enriched.append(updated)
        time.sleep(delay_seconds)

    return enriched


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich restaurant leads using Google Places and official websites.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Seed CSV path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Enriched CSV path.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of rows to enrich.")
    parser.add_argument("--delay", type=float, default=1.2, help="Delay between web requests in seconds.")
    parser.add_argument("--env-file", default=".env", help="Optional env file containing GOOGLE_MAPS_API_KEY.")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    input_path = Path(args.input)
    output_path = Path(args.output)
    rows = read_rows(input_path)
    enriched = enrich_rows(rows, min(args.limit, len(rows)), args.delay)

    base_fields = list(rows[0].keys()) if rows else []
    extra_fields = [
        "google_maps_url",
        "address",
        "rating",
        "review_count",
        "business_status",
        "match_name",
        "match_confidence",
        "website_pages_checked",
    ]
    fieldnames = base_fields + [field for field in extra_fields if field not in base_fields]
    write_rows(output_path, enriched, fieldnames)
    print(f"Saved {len(enriched)} enriched rows to {output_path}")


if __name__ == "__main__":
    main()
