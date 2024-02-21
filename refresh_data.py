import sqlite3

def refresh_data():
    conn = sqlite3.connect('archiv.db')
    c = conn.cursor()
    c.execute("SELECT id, date, delivering, waste_name, quantity FROM archive")
    records = c.fetchall()
    conn.close()
    return records

if __name__ == "__main__":
    data = refresh_data()
    print(data)  # Toto len na overenie, môžete odstrániť, ak to nie je potrebné
