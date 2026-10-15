
import sqlite3

DB_PATH = "listings.db"


def delete_most_recent():
    conn = sqlite3.connect(DB_PATH)

    try:
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

        if cur.rowcount:
            print("Most recent listing history entry deleted.")
        else:
            print("No listing history entries found.")

        conn.commit()

    finally:
        conn.close()


if __name__ == "__main__":
    delete_most_recent()
