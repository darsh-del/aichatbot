#!/usr/bin/env python3
"""
Bucketlistt.com Web Scraper
Fetches all pages from bucketlistt.com sitemap, extracts clean text content,
and saves to a structured JSON file for vector database ingestion.

Usage:
    cd backend
    python scripts/scrape_bucketlistt.py
"""

import json
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import httpx

# ─── All URLs from sitemap.xml ────────────────────────────────────────────────
URLS = [
    # Homepage
    ("home", "https://www.bucketlistt.com/"),
    # Activity category pages
    ("activity_category", "https://www.bucketlistt.com/bungee"),
    ("activity_category", "https://www.bucketlistt.com/rafting"),
    ("activity_category", "https://www.bucketlistt.com/paragliding"),
    ("activity_category", "https://www.bucketlistt.com/zipline"),
    ("activity_category", "https://www.bucketlistt.com/hot-air-balloon"),
    # Destination pages
    ("destination", "https://www.bucketlistt.com/rishikesh"),
    ("destination", "https://www.bucketlistt.com/manali"),
    ("destination", "https://www.bucketlistt.com/bir-billings"),
    ("destination", "https://www.bucketlistt.com/ujjain"),
    ("destination", "https://www.bucketlistt.com/mussoorie"),
    ("destination", "https://www.bucketlistt.com/jim-corbett"),
    ("destination", "https://www.bucketlistt.com/tehri"),
    # Rishikesh product pages
    ("product", "https://www.bucketlistt.com/rishikesh/himalayan-bungee"),
    ("product", "https://www.bucketlistt.com/rishikesh/river-rafting"),
    ("product", "https://www.bucketlistt.com/rishikesh/maa-ganga-bungee"),
    ("product", "https://www.bucketlistt.com/rishikesh/paragliding-with-whynotfly"),
    ("product", "https://www.bucketlistt.com/rishikesh/zip-line-over-ganga"),
    ("product", "https://www.bucketlistt.com/rishikesh/camping"),
    ("product", "https://www.bucketlistt.com/rishikesh/hot-air-balloon"),
    ("product", "https://www.bucketlistt.com/rishikesh/jumpin-heights"),
    ("product", "https://www.bucketlistt.com/rishikesh/thrill-factory-bungee-more"),
    ("product", "https://www.bucketlistt.com/rishikesh/paramotoring"),
    ("product", "https://www.bucketlistt.com/rishikesh/hap-hikers-adventure-park"),
    ("product", "https://www.bucketlistt.com/rishikesh/bungee-jumping"),
    ("product", "https://www.bucketlistt.com/rishikesh/aerial-yoga"),
    ("product", "https://www.bucketlistt.com/rishikesh/dronecraft-river-rafting"),
    ("product", "https://www.bucketlistt.com/rishikesh/bike-rental-rishikesh"),
    ("product", "https://www.bucketlistt.com/rishikesh/splash-bungy"),
    ("product", "https://www.bucketlistt.com/rishikesh/tapowan-to-haridwar-drop"),
    ("product", "https://www.bucketlistt.com/rishikesh/mussoorie-package-taxi"),
    ("product", "https://www.bucketlistt.com/rishikesh/front-row-seats-at-ganga-aarti-triveni-ghat"),
    ("product", "https://www.bucketlistt.com/rishikesh/maa-ganga-bungee/maa-ganga-bungee-video"),
    ("product", "https://www.bucketlistt.com/rishikesh/himalayan-bungee/extreme-highest-bungee-117m-with-video"),
    # Mussoorie products
    ("product", "https://www.bucketlistt.com/mussoorie/paragliding-with-skywing-adventure"),
    ("product", "https://www.bucketlistt.com/mussoorie/kanatal-outdoors"),
    ("product", "https://www.bucketlistt.com/mussoorie/high-fly-adventure"),
    ("product", "https://www.bucketlistt.com/mussoorie/skywing-bungee-jump"),
    # Jim Corbett
    ("product", "https://www.bucketlistt.com/jim-corbett/jim-corbett-bungee-himalayan-bungee"),
    # Manali
    ("product", "https://www.bucketlistt.com/manali/manali-bungee"),
    # Tehri
    ("product", "https://www.bucketlistt.com/tehri/tehri-water-sports"),
    # Info pages
    ("info", "https://www.bucketlistt.com/about-bucketlistt"),
    ("info", "https://www.bucketlistt.com/contact"),
    ("info", "https://www.bucketlistt.com/safety-guidelines"),
    ("info", "https://www.bucketlistt.com/reviews"),
    ("info", "https://www.bucketlistt.com/terms"),
    ("info", "https://www.bucketlistt.com/privacy"),
    # Blog articles
    ("blog", "https://www.bucketlistt.com/blogs/paragliding-in-india-cost-and-tips"),
    ("blog", "https://www.bucketlistt.com/blogs/best-adventure-booking-platform-in-rishikesh-bucketlistt"),
    ("blog", "https://www.bucketlistt.com/blogs/places-to-visit-in-rishikesh-in-one-day"),
    ("blog", "https://www.bucketlistt.com/blogs/best-zipline-adventures-india"),
    ("blog", "https://www.bucketlistt.com/blogs/top-adventure-holiday-spots-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/best-rishikesh-rafting-distance-for-beginners"),
    ("blog", "https://www.bucketlistt.com/blogs/bungee-jumping-height-in-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/book-safe-river-rafting-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/10-reasons-to-try-bungee-jumping-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/top-trending-adventure-activities-in-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/adventure-sports-booking-tips-india"),
    ("blog", "https://www.bucketlistt.com/blogs/river-rafting-season-in-india"),
    ("blog", "https://www.bucketlistt.com/blogs/best-paragliding-places-in-india"),
    ("blog", "https://www.bucketlistt.com/blogs/price-of-highest-bungee-jumping-in-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/adventure-sports-in-india-before-30"),
    ("blog", "https://www.bucketlistt.com/blogs/top-reasons-to-try-a-hot-air-balloon-ride-in-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/what-are-the-prices-of-bungee-jumping-in-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/top-reasons-to-book-river-rafting-with-bucketlistt"),
    ("blog", "https://www.bucketlistt.com/blogs/best-adventure-activities-rishikesh-solo-travelers"),
    ("blog", "https://www.bucketlistt.com/blogs/splash-bungee-jumping-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/best-bungee-jumping-in-rishikesh-2026"),
    ("blog", "https://www.bucketlistt.com/blogs/are-you-eligible-for-the-flying-fox-in-rishikesh-weight-limit-details"),
    ("blog", "https://www.bucketlistt.com/blogs/top-bungee-jumping-spots-rishikesh"),
    ("blog", "https://www.bucketlistt.com/blogs/best-adventure-sports-destinations-india"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def clean_html(html: str) -> str:
    """Strip HTML tags and compress whitespace."""
    # Remove script, style, and other non-content tags entirely
    html = re.sub(r'<(script|style|noscript|svg|path|circle|line|polyline|rect)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove remaining tags
    html = re.sub(r'<[^>]+>', ' ', html)
    # Decode HTML entities
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#x27;', "'").replace('&nbsp;', ' ').replace('&#39;', "'")
    # Compress whitespace
    html = re.sub(r'\s+', ' ', html).strip()
    return html


def extract_schema_json(html: str) -> list[dict]:
    """Extract all JSON-LD schema.org blocks from HTML."""
    schemas = []
    pattern = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(html):
        try:
            data = json.loads(match.group(1).strip())
            schemas.append(data)
        except json.JSONDecodeError:
            pass
    return schemas


def extract_meta(html: str) -> dict:
    """Extract page title and meta description."""
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', html, re.IGNORECASE)
    og_title = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']*)["\']', html, re.IGNORECASE)
    og_desc = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']*)["\']', html, re.IGNORECASE)
    return {
        "title": clean_html(title_match.group(1)) if title_match else "",
        "description": desc_match.group(1) if desc_match else (og_desc.group(1) if og_desc else ""),
        "og_title": og_title.group(1) if og_title else "",
    }


def extract_meaningful_text(html: str) -> str:
    """Extract meaningful visible text from the page body, excluding nav/footer boilerplate."""
    # Extract body content
    body_match = re.search(r'<(?:main|body)[^>]*>(.*?)(?:</main>|</body>)', html, re.DOTALL | re.IGNORECASE)
    if body_match:
        body = body_match.group(1)
    else:
        body = html

    # Remove nav, header, footer, boilerplate sections
    for tag in ['<nav', '<footer', '<header', 'class="NavContainer"', 'class="FooterTopGrid"', 'class="FooterBottomBar"', 'class="CTASection"', 'class="ContactSocialStrip"', 'class="SB-wrap"']:
        idx = body.find(tag)
        if idx > -1:
            # Find end of this tag block (rough approximation)
            pass

    return clean_html(body)


def build_structured_content(url: str, page_type: str, meta: dict, schemas: list, raw_text: str) -> dict:
    """Build a clean structured content dict from page data."""
    # Extract offers from schemas
    activities = []
    faqs = []
    highlights = []
    org_info = {}

    for schema in schemas:
        schema_type = schema.get("@type", "")

        # Extract offers/activities from hasOfferCatalog
        catalog = schema.get("hasOfferCatalog", {})
        if catalog:
            for item in catalog.get("itemListElement", []):
                offered = item.get("itemOffered", {})
                name = offered.get("name", "")
                desc = offered.get("description", "")
                price = item.get("price", "")
                currency = item.get("priceCurrency", "INR")
                if name:
                    activities.append({
                        "name": name,
                        "description": desc,
                        "price_inr": price,
                        "currency": currency,
                    })

        # Extract FAQs
        if schema_type == "FAQPage":
            for qa in schema.get("mainEntity", []):
                q = qa.get("name", "")
                a = qa.get("acceptedAnswer", {}).get("text", "")
                if q:
                    faqs.append({"question": q, "answer": a})

        # Extract org info
        if schema_type in ("Organization", "TouristInformationCenter", "LocalBusiness"):
            org_info = {
                "name": schema.get("name", ""),
                "description": schema.get("description", ""),
                "telephone": schema.get("telephone", ""),
                "email": schema.get("email", ""),
                "address": schema.get("address", {}),
                "rating": schema.get("aggregateRating", {}),
            }

        # Service page
        if schema_type == "Service":
            desc = schema.get("description", "")
            if desc and desc not in highlights:
                highlights.append(desc)

        # TouristAttraction / TouristTrip
        if schema_type in ("TouristAttraction", "TouristTrip", "Event"):
            desc = schema.get("description", "")
            if desc and desc not in highlights:
                highlights.append(desc)

        # Blog/Article
        if schema_type in ("Article", "BlogPosting", "NewsArticle"):
            body = schema.get("articleBody", "") or schema.get("description", "")
            if body and body not in highlights:
                highlights.append(body[:2000])

        # Reviews
        for review in schema.get("review", []):
            body = review.get("reviewBody", "")
            rating = review.get("reviewRating", {}).get("ratingValue", "")
            author = review.get("author", "Anonymous") if isinstance(review.get("author"), str) else review.get("author", {}).get("name", "Anonymous")
            if body:
                highlights.append(f"Customer Review ({rating}/5 by {author}): {body}")

    # Build main content text block
    content_parts = []

    if meta.get("title"):
        content_parts.append(f"# {meta['title']}")
    if meta.get("description"):
        content_parts.append(f"## Description\n{meta['description']}")

    if highlights:
        content_parts.append("## Key Information\n" + "\n".join(f"- {h}" for h in highlights[:5]))

    if activities:
        acts_text = "\n".join(
            f"- {a['name']}: ₹{a['price_inr']} INR - {a['description']}"
            for a in activities
        )
        content_parts.append(f"## Activities & Packages\n{acts_text}")

    if faqs:
        faq_text = "\n".join(
            f"Q: {f['question']}\nA: {f['answer']}"
            for f in faqs
        )
        content_parts.append(f"## FAQs\n{faq_text}")

    if org_info:
        content_parts.append(
            f"## Contact & About\n"
            f"Name: {org_info.get('name', '')}\n"
            f"Phone: {org_info.get('telephone', '')}\n"
            f"Email: {org_info.get('email', '')}\n"
            f"Description: {org_info.get('description', '')}"
        )

    # Add a clean excerpt of the page text (first 3000 chars of meaningful text)
    page_excerpt = raw_text[:3000] if raw_text else ""
    if page_excerpt:
        content_parts.append(f"## Page Content Excerpt\n{page_excerpt}")

    return {
        "url": url,
        "page_type": page_type,
        "title": meta.get("title", ""),
        "description": meta.get("description", ""),
        "content": "\n\n".join(content_parts),
        "activities": activities,
        "faqs": faqs,
        "scraped_at": datetime.utcnow().isoformat(),
    }


def fetch_page(client: httpx.Client, url: str, retries: int = 3) -> str | None:
    """Fetch a URL with retries and return HTML content."""
    for attempt in range(retries):
        try:
            response = client.get(url, timeout=30)
            if response.status_code == 200:
                return response.text
            elif response.status_code == 404:
                print(f"  [404 skipped] {url}")
                return None
            else:
                print(f"  [HTTP {response.status_code}] {url}")
                if attempt < retries - 1:
                    time.sleep(2)
        except Exception as e:
            print(f"  [Error attempt {attempt+1}] {url}: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    return None


def main():
    output_path = "data/bucketlistt_scraped.json"
    all_pages = []
    failed_urls = []

    print(f"Starting scrape of {len(URLS)} URLs...")
    print("=" * 60)

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        for i, (page_type, url) in enumerate(URLS, 1):
            print(f"[{i:02d}/{len(URLS)}] {page_type}: {url}")
            html = fetch_page(client, url)

            if html is None:
                failed_urls.append(url)
                continue

            try:
                meta = extract_meta(html)
                schemas = extract_schema_json(html)
                raw_text = extract_meaningful_text(html)
                page_data = build_structured_content(url, page_type, meta, schemas, raw_text)
                all_pages.append(page_data)
                print(f"  ✓ '{page_data['title'][:60]}' | {len(schemas)} schemas | {len(page_data['activities'])} activities | {len(page_data['faqs'])} FAQs")
            except Exception as e:
                print(f"  ✗ Parse error: {e}")
                failed_urls.append(url)

            # Respectful crawl delay
            if i < len(URLS):
                time.sleep(0.8)

    output = {
        "scraped_at": datetime.utcnow().isoformat(),
        "source": "https://www.bucketlistt.com",
        "total_pages": len(all_pages),
        "failed_urls": failed_urls,
        "pages": all_pages,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"✅ Done! Scraped {len(all_pages)} pages, {len(failed_urls)} failed.")
    print(f"   Saved to: {output_path}")
    if failed_urls:
        print(f"   Failed URLs: {failed_urls}")


if __name__ == "__main__":
    main()
