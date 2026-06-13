import sqlite3
from datetime import datetime

DB_NAME = 'sourcing.db'


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            site TEXT,
            product_id TEXT,
            name TEXT,
            supply_price INTEGER,
            delivery_fee INTEGER,
            status TEXT,
            updated_at DATETIME,
            is_tracked INTEGER DEFAULT 0,
            seller_grade TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            PRIMARY KEY (site, product_id)
        )
    ''')

    # 기존 DB 마이그레이션
    for col, coltype in [("seller_grade", "TEXT DEFAULT ''"),
                         ("image_url",    "TEXT DEFAULT ''")]:
        try:
            cursor.execute(f"ALTER TABLE products ADD COLUMN {col} {coltype}")
            print(f"[DB] {col} 컬럼 추가 완료")
        except sqlite3.OperationalError:
            pass  # 이미 있으면 무시

    conn.commit()
    conn.close()
    print("[System] DB 초기화 완료.")


def upsert_tracked_product(p, is_tracked):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    grade     = str(p.get('seller_grade', '') or '')
    image_url = str(p.get('image_url', '') or '')

    cursor.execute('''
        INSERT INTO products
        (site, product_id, name, supply_price, delivery_fee, status,
         updated_at, is_tracked, seller_grade, image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(site, product_id) DO UPDATE SET
            name=excluded.name,
            supply_price=excluded.supply_price,
            delivery_fee=excluded.delivery_fee,
            status=excluded.status,
            updated_at=excluded.updated_at,
            is_tracked=excluded.is_tracked,
            seller_grade=CASE WHEN excluded.seller_grade != '' THEN excluded.seller_grade ELSE seller_grade END,
            image_url=CASE WHEN excluded.image_url != '' THEN excluded.image_url ELSE image_url END
    ''', (
        p['site'], str(p['product_id']), p['name'],
        p['supply_price'], p['delivery_fee'], p['status'],
        current_time, is_tracked, grade, image_url
    ))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
