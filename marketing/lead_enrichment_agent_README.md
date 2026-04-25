# Restaurant Lead Enrichment Agent

This workflow enriches a restaurant lead CSV with public business data.

## What It Does

1. Reads `texas_top_100_restaurants_contacts_seed.csv`.
2. Searches each restaurant through Google Places API Text Search.
3. Extracts phone, website, address, Google Maps URL, rating, review count, and business status.
4. Visits the official website and likely contact/about/event pages.
5. Extracts public business emails when listed.
6. Writes `texas_top_100_restaurants_enriched.csv`.

## Why Google Places API

Do not scrape Google Maps pages directly. Google provides Places API for this use case, and the agent uses the current Text Search endpoint:

`https://places.googleapis.com/v1/places:searchText`

Google requires field masks for Places requests and bills based on the fields requested.

Official docs:

- https://developers.google.com/maps/documentation/places/web-service/text-search
- https://developers.google.com/maps/documentation/places/web-service/place-details

## Setup

Create or update `.env` in the project root:

```text
GOOGLE_MAPS_API_KEY=your_google_maps_platform_key
```

Enable Places API in Google Cloud for that key.

## Run

From the project root:

```powershell
python marketing\lead_enrichment_agent.py --limit 10
```

For all 100:

```powershell
python marketing\lead_enrichment_agent.py --limit 100
```

Output:

```text
marketing/texas_top_100_restaurants_enriched.csv
```

## Notes

- Google Places normally does not return email addresses.
- Emails are extracted from official restaurant websites when publicly listed.
- Some sites use contact forms instead of public emails.
- Rows with `match_confidence=review` should be manually checked before outreach.
- Respect email marketing laws and use verified business contact details only.
