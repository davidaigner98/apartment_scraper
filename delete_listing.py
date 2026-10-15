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
    delete_most_recent()
