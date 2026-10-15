import sqlite3

DB_PATH = "listings.db"


def fetch_recent(limit=25):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    SELECT listing_id, title, url, price, event_type, seen_at
    FROM listings_history
    ORDER BY seen_at DESC
    LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


def print_rows(rows):
    print(f"\nLast {len(rows)} events:\n")
    print("-" * 80)

    for r in rows:
        listing_id, title, url, price, event_type, seen_at = r

        print(f"[{event_type}] {seen_at}")
        print(f"ID:    {listing_id}")
        print(f"Title: {title}")
        print(f"Price: {price}")
        print(f"URL:   {url}")
        print("-" * 80)


def delete_most_recent():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM listings_history
        WHERE rowid = (
            SELECT rowid
            FROM listings_history
            ORDER BY seen_at DESC, rowid DESC
            LIMIT 1
        )
    """)

    deleted = cur.rowcount
    conn.commit()
    conn.close()

    if deleted:
        print("Most recent listing history entry deleted.")
    else:
        print("No listing history entries found.")


if __name__ == "__main__":
    rows = fetch_recent(25)
    print_rows(rows)
