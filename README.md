# Concordia Connect directory scraper

Scrapes the member directory at
`https://connect.swoogo.com/concordiaconnect/Directory?i=...`
and writes every card to `data/concordia_directory.csv`.

## Why this needs to run on your machine

The cloud sandbox this code was authored in blocks outbound HTTP to
`connect.swoogo.com` (returns `403 host_not_allowed`) and also blocks
Playwright's Chromium download CDN. Run the script on your local machine
where neither block applies.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python scraper.py
```

Expected output:

```
Opening https://connect.swoogo.com/concordiaconnect/3765355?i=...
Navigating to directory: https://connect.swoogo.com/concordiaconnect/Directory?i=...
  page  1/46:  40 cards (total 40)
  page  2/46:  40 cards (total 80)
  ...
  page 46/46:  ?? cards (total ~1840)

Wrote 1840 rows to data/concordia_directory.csv
```

## CSV columns

`full_name, title, organization, bio, industry, city, state, country, website, region_of_interest, twitter, linkedin, photo`

`photo` is the absolute URL of the member's profile picture (Swoogo serves
them as protocol-relative `//assets.swoogo.com/...`; the scraper prepends
`https:`).

## Notes

- Credentials are hard-coded in `scraper.py` for convenience. If the
  `i=...` token already authenticates, the login form is skipped
  automatically.
- The script fetches each page via Playwright's authenticated request
  context (no JS execution), so it parses the server-rendered DOM before
  the inline page JS rewrites the cards.
- 0.5s delay between pages to be polite. ~1 minute total run.
- If `.reg-list-card` isn't found on the directory page (e.g. login
  failed or layout changed), the failing HTML is dumped to
  `data/_failed_directory.html` for debugging.
