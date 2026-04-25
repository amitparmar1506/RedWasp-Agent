# Restaurant Lead Agent

Restaurant Lead Agent is a sellable lead-enrichment web app for restaurant outreach.

It takes a seed CSV of restaurant names and cities, enriches each lead with Google Places business data, scans official websites for public emails, and exports a clean CSV for review.

## Features

- Upload or use a seed CSV
- Google Places enrichment for phone, website, address, rating, review count, and Maps URL
- Official website/contact-page email extraction
- Row-by-row progress log
- Downloadable enriched CSV
- Confidence flags for manual review

## Setup

Create `.env` in the project root:

```text
GOOGLE_MAPS_API_KEY=your_google_maps_platform_key
LEAD_AGENT_TOKEN=choose_a_private_admin_password
```

Install:

```powershell
pip install -r lead_agent_product\requirements.txt
```

Run:

```powershell
python lead_agent_product\app.py
```

Open:

```text
http://127.0.0.1:5150
```

## CSV Input Columns

Required:

```text
restaurant_name
city
state
```

Recommended:

```text
rank
phone_number
website
email_address
source
source_url
verification_status
```

## Compliance Note

This app uses Google Places API instead of scraping Google Maps pages. Email extraction is limited to publicly available official websites/contact pages. Always review enriched leads and follow applicable email marketing laws.
