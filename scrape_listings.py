from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import sqlite3
from datetime import datetime
import requests
import os

BASE_URL = "https://www.willhaben.at"
URL = "https://www.willhaben.at/iad/immobilien/mietwohnungen/mietwohnung-angebote?sfId=1d30152f-be68-4e65-9d34-17a68060cbcc&areaId=900&rows=30&keyword=Altbau&isNavigation=true&page=1&PRICE_TO=1500"
DC_HOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not DC_HOOK_URL:
    raise RuntimeError("DISCORD_WEBHOOK_URL environment variable is not set.")


def init_db():
    conn = sqlite3.connect("listings.db")
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS listings_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id TEXT,
        title TEXT,
        url TEXT,
        price REAL,
        event_type TEXT,
        seen_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def print_db_report():
    conn = sqlite3.connect("listings.db")
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM listings_history")
    print("Rows:", cur.fetchone()[0])

    cur.execute("""
    SELECT
        listing_id,
        title,
        price,
        event_type,
        seen_at
    FROM listings_history
    ORDER BY seen_at DESC
    LIMIT 10
    """)

    print("\nNewest 10 entries:")
    for row in cur.fetchall():
        print(row)

    conn.commit()
    conn.close()

def process_listings(listings):
    conn = sqlite3.connect("listings.db")
    cur = conn.cursor()

    now = datetime.now().isoformat()

    new_items = []
    updated_items = []

    for l in listings:
        listing_id = l["id"]

        # Get latest known state from history
        cur.execute("""
        SELECT price
        FROM listings_history
        WHERE listing_id = ?
        ORDER BY seen_at DESC
        LIMIT 1
        """, (listing_id,))

        row = cur.fetchone()
        if row:
            old_price = row[0]
        else:
            new_item = True

        # Classify event
        if new_item:
            event_type = "NEW"
            new_items.append(l)
        elif old_price != l["price"]:
            event_type = "PRICE_CHANGE"
            updated_items.append(l)
        else:
            event_type = "SEEN"

        # Only store meaningful events (no spam)
        if event_type != "SEEN":
            cur.execute("""
            INSERT INTO listings_history (
                listing_id, title, url, price, event_type, seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                listing_id,
                l["title"],
                l["url"],
                l["price"],
                event_type,
                now
            ))

    conn.commit()
    conn.close()

    return new_items, updated_items


def scrape_listings():
    listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(viewport={"width": 1400, "height": 1000})

        print("Opening page...")
        page.goto(URL, wait_until="domcontentloaded")

        # Let React hydrate
        page.wait_for_timeout(1000)

        print("Scrolling...")

        last_height = 0

        for i in range(20):
            page.evaluate("window.scrollBy(0, 500)")
            page.wait_for_timeout(500)

            new_height = page.evaluate("document.body.scrollHeight")

            print(f"Scroll {i+1}: height = {new_height}")

            if new_height == last_height:
                break

            last_height = new_height

        # final lazy-load buffer
        page.wait_for_timeout(1000)

        html = page.content()
        browser.close()

    # -------------------------
    # PARSING
    # -------------------------
    soup = BeautifulSoup(html, "lxml")

    seen = set()

    for div in soup.find_all("div", id=True):
        listing_id = div["id"]

        if not listing_id.isdigit():
            continue

        if listing_id in seen:
            continue

        link = div.select_one("a[href*='/iad/immobilien/d/']")
        if not link:
            continue

        href = link.get("href")
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)

        title = link.get_text(" ", strip=True).replace("\n", " ")

        # -------------------------
        # PRICE EXTRACTION
        # -------------------------
        price_span = div.select_one(
            "span[data-testid^='search-result-entry-price-']:not([data-testid*='sqmeter'])"
        )

        if price_span:
            raw_price = price_span.get_text(strip=True)
            raw_price = raw_price.replace("€", "").strip()

            try:
                price = float(raw_price.replace(".", "").replace(",", "."))
            except:
                price = float("nan")
        else:
            price = float("nan")

        seen.add(listing_id)

        listings.append({
            "id": listing_id,
            "title": title,
            "url": full_url,
            "price": price
        })

    return listings


def notify_discord(message):
    requests.post(DC_HOOK_URL, json={
        "content": message
    })


if __name__ == "__main__":
    init_db()

    print_db_report()

    listings = scrape_listings()

    new_items, updated_items = process_listings(listings)

    print(f"New: {len(new_items)} | Updated: {len(updated_items)}")
    for item in reversed(new_items):
        print(f"New item {item['id']}")
        notify_discord(
            f"🏠 NEW LISTING\n"
            f"{item['title']}\n"
            f"€{item['price']}\n"
            f"{item['url']}"
        )

    for item in reversed(updated_items):
        print(f"Updated item {item['id']}")
        notify_discord(
            f"📉 PRICE UPDATE\n"
            f"{item['title']}\n"
            f"€{item['price']}\n"
            f"{item['url']}"
        )
