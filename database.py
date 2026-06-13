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
            PRIMARY KEY (site, product_id)
        )
    ''')
    conn.commit()
    conn.close()
    print("[System] 데이터베이스 테이블이 성공적으로 초기화되었습니다.")


def upsert_tracked_product(p, is_tracked):
    """라이브 검색 결과에서 관심 등록(체크)된 개별 상품을 DB에 즉시 저장/수정합니다."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute('''
        INSERT INTO products 
        (site, product_id, name, supply_price, delivery_fee, status, updated_at, is_tracked)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(site, product_id) DO UPDATE SET
            name=excluded.name,
            supply_price=excluded.supply_price,
            delivery_fee=excluded.delivery_fee,
            status=excluded.status,
            updated_at=excluded.updated_at,
            is_tracked=excluded.is_tracked
    ''', (
        p['site'], str(p['product_id']), p['name'],
        p['supply_price'], p['delivery_fee'], p['status'], current_time, is_tracked
    ))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()