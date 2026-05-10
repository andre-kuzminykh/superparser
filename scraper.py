"""
Concordia Connect directory scraper.

Logs in to the Swoogo-hosted directory, walks all paginated pages, and writes
every member card to a CSV file.

Usage:
    python -m playwright install chromium
    python scraper.py
"""

from __future__ import annotations

import csv
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup
from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

EMAIL = "1@thehumanoid.ai"
PASSWORD = "8Nm&kl5N!"

EVENT_BASE = "https://connect.swoogo.com/concordiaconnect"
ACCESS_TOKEN = "D1KQFyjXYIweQ5WOBl_EBJpout5fxTT7"
ENTRY_URL = f"{EVENT_BASE}/3765355?i={ACCESS_TOKEN}"
DIRECTORY_URL = f"{EVENT_BASE}/Directory?i={ACCESS_TOKEN}"

PER_PAGE = 40
TOTAL_PAGES = 46

OUTPUT_PATH = Path(__file__).parent / "data" / "concordia_directory.csv"

CSV_FIELDS = [
    "full_name",
    "title",
    "organization",
    "bio",
    "industry",
    "city",
    "state",
    "country",
    "website",
    "region_of_interest",
    "twitter",
    "linkedin",
    "photo",
]


@dataclass
class Member:
    full_name: str = ""
    title: str = ""
    organization: str = ""
    bio: str = ""
    industry: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    website: str = ""
    region_of_interest: str = ""
    twitter: str = ""
    linkedin: str = ""
    photo: str = ""


def absolutize(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    return url


def text_of(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def link_or_text(node) -> str:
    if node is None:
        return ""
    a = node.find("a")
    if a and a.get("href"):
        return a["href"].strip()
    return text_of(node)


def parse_cards(html: str) -> list[Member]:
    """Parse one Directory page's HTML. The page is server-rendered; we read
    the DOM *as delivered* before the inline JS rearranges it."""
    soup = BeautifulSoup(html, "html.parser")
    members: list[Member] = []

    for card in soup.select(".reg-list-card .panel-body .content"):
        img = card.select_one("img.profile-picture")
        photo = absolutize(img.get("src", "")) if img else ""

        name_node = card.find("b")
        full_name = text_of(name_node)

        # Direct child <div>s, in render order, after the <b>:
        # 0: Job Title, 1: Organization, 2: Created At (skip),
        # 3: Bio, 4: Industry, 5: City, 6: State, 7: Country,
        # 8: Website (link), 9: Regions of Interest,
        # 10: Twitter, 11: LinkedIn (link)
        divs = card.find_all("div", recursive=False)

        def at(idx: int) -> str:
            return text_of(divs[idx]) if idx < len(divs) else ""

        def link_at(idx: int) -> str:
            return link_or_text(divs[idx]) if idx < len(divs) else ""

        members.append(
            Member(
                full_name=full_name,
                title=at(0),
                organization=at(1),
                bio=at(3),
                industry=at(4),
                city=at(5),
                state=at(6),
                country=at(7),
                website=link_at(8),
                region_of_interest=at(9),
                twitter=at(10),
                linkedin=link_at(11),
                photo=photo,
            )
        )

    return members


def maybe_login(page: Page) -> None:
    """If a login form is present, fill it. Swoogo magic-link tokens often
    auto-authenticate but the flow can demand a password on a fresh device."""
    page.wait_for_load_state("domcontentloaded")

    # Heuristics: a password input or an email input on this page means we
    # need to authenticate.
    email_selector = (
        'input[type="email"], '
        'input[name*="email" i], '
        'input[id*="email" i]'
    )
    password_selector = 'input[type="password"]'

    if page.locator(password_selector).count() == 0:
        return  # already authenticated via the i= token

    print("Login form detected — filling credentials...")
    email_input = page.locator(email_selector).first
    if email_input.count():
        email_input.fill(EMAIL)
    password_input = page.locator(password_selector).first
    password_input.fill(PASSWORD)

    submit = page.locator(
        'button[type="submit"], input[type="submit"], '
        'button:has-text("Sign in"), button:has-text("Log in"), '
        'button:has-text("Login")'
    ).first
    if submit.count():
        submit.click()
    else:
        password_input.press("Enter")

    page.wait_for_load_state("networkidle")


def fetch_page_html(context: BrowserContext, page_num: int) -> str:
    """Fetch a single Directory page using the authenticated context's
    request API (no JS execution → DOM stays as the server delivered it)."""
    url = f"{DIRECTORY_URL}&page={page_num}&per-page={PER_PAGE}"
    response = context.request.get(url)
    if not response.ok:
        raise RuntimeError(
            f"Page {page_num} returned HTTP {response.status} for {url}"
        )
    return response.text()


def scrape(p: Playwright) -> list[Member]:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        locale="en-US",
    )
    page = context.new_page()
    try:
        print(f"Opening {ENTRY_URL}")
        page.goto(ENTRY_URL, wait_until="domcontentloaded")
        maybe_login(page)

        print(f"Navigating to directory: {DIRECTORY_URL}")
        page.goto(DIRECTORY_URL, wait_until="domcontentloaded")
        # Sanity check: the directory has a card grid.
        try:
            page.wait_for_selector(".reg-list-card", timeout=15_000)
        except PlaywrightTimeoutError:
            print(
                "Could not find .reg-list-card on the directory page. "
                "Login may have failed or the directory layout changed.",
                file=sys.stderr,
            )
            html = page.content()
            (Path(__file__).parent / "data" / "_failed_directory.html").write_text(
                html, encoding="utf-8"
            )
            raise

        all_members: list[Member] = []
        for n in range(1, TOTAL_PAGES + 1):
            html = fetch_page_html(context, n)
            page_members = parse_cards(html)
            all_members.extend(page_members)
            print(
                f"  page {n:>2}/{TOTAL_PAGES}: {len(page_members):>3} cards "
                f"(total {len(all_members)})"
            )
            time.sleep(0.5)  # be polite

        return all_members
    finally:
        context.close()
        browser.close()


def write_csv(members: Iterable[Member], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for m in members:
            writer.writerow(asdict(m))


def main() -> int:
    with sync_playwright() as p:
        members = scrape(p)
    write_csv(members, OUTPUT_PATH)
    print(f"\nWrote {len(members)} rows to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
