
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
import sqlite3
import requests
import os
import math

from classify_apartment import classify_apartment

BASE_URL = "https://www.willhaben.at"
URL = (
    "https://www.willhaben.at/iad/immobilien/mietwohnungen/"
    "mietwohnung-angebote?sfId=1d30152f-be68-4e65-9d34-17a68060cbcc"
    "&areaId=900&rows=30&keyword=Altbau&isNavigation=true"
    "&page=1&PRICE_TO=1500"
)

DB_PATH = "listings.db"
DC_HOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not DC_HOOK_URL:
    raise RuntimeError("DISCORD_WEBHOOK_URL environment variable is not set.")



def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    expected_columns = [
        "id",
        "listing_id",
        "title",
        "url",
        "price",
        "event_type",
        "seen_at",
    ]

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

    existing_columns = [
        row[1]
        for row in cur.execute(
            "PRAGMA table_info(listings_history)"
        ).fetchall()
    ]

    if existing_columns != expected_columns:
        print("Migrating listings_history to the seven-column schema...")

        # Preserve existing values for columns that are available.
        expressions = [
            f'"{col}"' if col in existing_columns else "NULL"
            for col in expected_columns
        ]

        cur.execute("DROP TABLE IF EXISTS listings_history_new")

        cur.execute("""
            CREATE TABLE listings_history_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT,
                title TEXT,
                url TEXT,
                price REAL,
                event_type TEXT,
                seen_at TEXT
            )
        """)

        cur.execute(f"""
            INSERT INTO listings_history_new (
                {", ".join(expected_columns)}
            )
            SELECT {", ".join(expressions)}
            FROM listings_history
        """)

        cur.execute("DROP TABLE listings_history")
        cur.execute("""
            ALTER TABLE listings_history_new
            RENAME TO listings_history
        """)

    conn.commit()
    conn.close()


def print_db_report():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM listings_history")
    print("Rows:", cur.fetchone()[0])

    cur.execute("""
        SELECT listing_id, title, price, event_type, seen_at
        FROM listings_history
        ORDER BY seen_at DESC
        LIMIT 10
    """)

    print("\nNewest 10 entries:")
    for row in cur.fetchall():
        print(row)

    conn.close()


def find_new_listings(listings):
    """Return listings whose IDs have not been recorded."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    new_items = []

    for listing in listings:
        cur.execute(
            "SELECT 1 FROM listings_history WHERE listing_id = ? LIMIT 1",
            (listing["id"],),
        )

        if cur.fetchone() is None:
            new_items.append(listing)

    conn.close()
    return new_items


def scrape_listings():
    listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1400, "height": 1000}
        )

        print("Opening search page...")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)

        last_height = 0

        for i in range(20):
            page.evaluate("window.scrollBy(0, 500)")
            page.wait_for_timeout(500)

            new_height = page.evaluate("document.body.scrollHeight")
            print(f"Scroll {i + 1}: height = {new_height}")

            if new_height == last_height:
                break

            last_height = new_height

        page.wait_for_timeout(1000)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "lxml")
    seen = set()

    for div in soup.find_all("div", id=True):
        listing_id = div["id"]

        if not listing_id.isdigit() or listing_id in seen:
            continue

        link = div.select_one("a[href*='/iad/immobilien/d/']")
        if not link or not link.get("href"):
            continue

        full_url = urljoin(BASE_URL, link["href"])
        title = link.get_text(" ", strip=True).replace("\n", " ")

        price_span = div.select_one(
            "span[data-testid^='search-result-entry-price-']"
            ":not([data-testid*='sqmeter'])"
        )

        price = None

        if price_span:
            raw_price = (
                price_span.get_text(strip=True)
                .replace("€", "")
                .strip()
            )

            try:
                price = float(
                    raw_price.replace(".", "").replace(",", ".")
                )
                if not math.isfinite(price):
                    price = None
            except ValueError:
                pass

        seen.add(listing_id)

        listings.append({
            "id": listing_id,
            "title": title,
            "url": full_url,
            "price": price,
        })

    print(f"Scraped {len(listings)} listings.")
    return listings



def fetch_descriptions(listings):
    """Extract listing content from the main h1 up to Premium Services."""

    descriptions = {}

    if not listings:
        return descriptions

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1400, "height": 1000}
        )

        for listing in listings:
            listing_id = listing["id"]

            try:
                print(f"Fetching description for {listing_id}")

                page.goto(
                    listing["url"],
                    wait_until="domcontentloaded",
                    timeout=45000,
                )

                # Wait for the main listing title.
                title_selector = 'h1[data-testid="ad-detail-header"]'
                page.locator(title_selector).wait_for(timeout=15000)

                # Extract the relevant rendered DOM fragment.
                extracted_text = page.locator("body").evaluate("""(body) => {
                    const start = body.querySelector(
                        'h1[data-testid="ad-detail-header"]'
                    );
                
                    if (!start) {
                        throw new Error("Listing title not found");
                    }
                
                    const walker = document.createTreeWalker(
                        body,
                        NodeFilter.SHOW_TEXT
                    );
                
                    let node;
                    let started = false;
                    const parts = [];
                
                    while ((node = walker.nextNode())) {
                        const text = node.textContent.trim();
                        if (!text) continue;
                
                        const parent = node.parentElement;
                
                        // Ignore hidden elements.
                        if (!parent || !parent.checkVisibility()) continue;
                
                        if (start.contains(parent)) {
                            started = true;
                        }
                
                        if (
                            started &&
                            parent.closest("h1, h2, h3, h4, h5, h6")
                                ?.textContent.trim().toLowerCase() === "premium services"
                        ) {
                            break;
                        }
                
                        if (started) {
                            parts.push(text);
                        }
                    }
                
                    return parts.join(" ").replace(/\\s+/g, " ").trim();
                }""")


                extracted_text = extracted_text.strip()

                if not extracted_text:
                    raise ValueError(
                        "No text extracted from listing page"
                    )

                descriptions[listing_id] = extracted_text[:10000]

                print(
                    f"Extracted {len(extracted_text)} characters "
                    f"for listing {listing_id}"
                )

            except Exception as exc:
                print(
                    f"Description fetch failed for "
                    f"{listing_id}: {exc}"
                )

        browser.close()

    return descriptions


def save_classified_listing(listing, description, result):
    """Save listing history without descriptions or classifications."""
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        INSERT INTO listings_history (
            listing_id, title, url, price, event_type, seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        listing["id"],
        listing["title"],
        listing["url"],
        listing["price"],
        "NEW",
        datetime.now().isoformat(),
    ))

    conn.commit()
    conn.close()


def format_flag(value):
    if value is True:
        return "✅ Yes"
    if value is False:
        return "❌ No"
    return "❓ Unknown"



def format_flag(value):
    if value is True:
        return "✅ Yes"
    if value is False:
        return "❌ No"
    return "❓ Unknown"


def format_number(value):
    return str(value) if value is not None else "Unknown"


def notify_discord(listing, result):
    message = (
        f"🏠 NEW LISTING\n"
        f"{listing['title']}\n\n"
        f"Unbefristet: {format_flag(result['Unbefristet'])}\n"
        f"Separate Küche: {format_flag(result['Separate Küche'])}\n"
        f"Aufzug vorhanden: {format_flag(result['Aufzug vorhanden'])}\n"
        f"Bezirk: {format_number(result['Bezirk'])}\n"
        f"Stockwerk: {format_number(result['Stockwerk'])}\n"
        f"Anzahl der Zimmer: {format_number(result['Anzahl der Zimmer'])}\n"
        f"Price: {'€' + format(listing['price'], ',.2f') if listing['price'] is not None else 'Unknown'}\n\n"
        f"{listing['url']}"
    )

    response = requests.post(
        DC_HOOK_URL,
        json={"content": message},
        timeout=15,
    )
    response.raise_for_status()


if __name__ == "__main__":
    init_db()
    print_db_report()

    listings = scrape_listings()
    new_items = find_new_listings(listings)

    print(f"Found {len(new_items)} unrecorded listings.")

    if not new_items:
        print("Nothing new to classify. Exiting without loading the model.")
        raise SystemExit(0)

    descriptions = fetch_descriptions(new_items)

    for listing in new_items:
        listing_id = listing["id"]
        description = descriptions.get(listing_id)

        if not description:
            print(f"Skipping {listing_id}: no description available.")
            continue

        try:
            result = classify_apartment(description)
            print(f"Classification for {listing_id}: {result}")

            save_classified_listing(listing, description, result)

            try:
                notify_discord(listing, result)
            except Exception as exc:
                print(f"Discord notification failed for {listing_id}: {exc}")

        except Exception as exc:
            print(f"Classification failed for {listing_id}: {exc}")
            continue
