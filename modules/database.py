"""
eBay Hub UK - Database Module
SQLite with WAL mode, thread-local connections.
"""

import sqlite3
import threading
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ebay_hub.db')

_local = threading.local()


def get_db():
    """Get thread-local database connection."""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, timeout=30)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def close_db():
    """Close thread-local connection."""
    if hasattr(_local, 'conn') and _local.conn is not None:
        _local.conn.close()
        _local.conn = None


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            supplier TEXT DEFAULT '',
            purchase_price_gbp REAL DEFAULT 0.0,
            purchase_date TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'sold', 'archived')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pallet_id INTEGER,
            name TEXT NOT NULL,
            asin TEXT DEFAULT '',
            ean TEXT DEFAULT '',
            quantity INTEGER DEFAULT 1,
            condition TEXT DEFAULT 'new' CHECK(condition IN ('new', 'like_new', 'used', 'damaged')),
            ebay_price_gbp REAL DEFAULT 0.0,
            cost_per_unit REAL DEFAULT 0.0,
            category TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            weight_kg REAL DEFAULT 0.0,
            length_cm REAL DEFAULT 0.0,
            width_cm REAL DEFAULT 0.0,
            height_cm REAL DEFAULT 0.0,
            shipping_method TEXT DEFAULT '',
            shipping_cost_gbp REAL DEFAULT 0.0,
            status TEXT DEFAULT 'warehouse' CHECK(status IN ('warehouse', 'listed', 'sold', 'shipped')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pallet_id) REFERENCES pallets(id)
        );

        CREATE TABLE IF NOT EXISTS ebay_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            ebay_item_id TEXT DEFAULT '',
            title TEXT DEFAULT '',
            description TEXT DEFAULT '',
            price_gbp REAL DEFAULT 0.0,
            status TEXT DEFAULT 'draft' CHECK(status IN ('draft', 'active', 'ended', 'sold')),
            views INTEGER DEFAULT 0,
            watchers INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ebay_order_id TEXT DEFAULT '',
            product_id INTEGER,
            listing_id INTEGER,
            price_gbp REAL DEFAULT 0.0,
            buyer TEXT DEFAULT '',
            shipping_address TEXT DEFAULT '',
            status TEXT DEFAULT 'new' CHECK(status IN ('new', 'shipped', 'delivered')),
            sold_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            shipped_at TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (listing_id) REFERENCES ebay_listings(id)
        );

        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        -- product_units: one row per physical unit in the pallet, so a
        -- product with quantity=37 can have a breakdown like
        --   29 x condition='new'
        --    8 x condition='used'
        -- Mirrors the `sztuki` table pattern from Akces Hub — the uncle is
        -- used to "rozbijanie na sztuki" there and asked for the same here.
        -- When rows exist for a product, they override the simple
        -- products.condition/quantity pair on the display. When absent,
        -- the legacy products.condition/quantity is used (so old data
        -- keeps working untouched).
        CREATE TABLE IF NOT EXISTS product_units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            unit_number INTEGER NOT NULL,
            condition TEXT DEFAULT 'new' CHECK(condition IN ('new', 'like_new', 'used', 'damaged')),
            status TEXT DEFAULT 'warehouse' CHECK(status IN ('warehouse', 'listed', 'sold', 'shipped')),
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        CREATE INDEX IF NOT EXISTS idx_product_units_product ON product_units(product_id);
    """)
    conn.commit()

    # Migrations for existing databases
    _migrations = [
        ('products', 'weight_kg', 'REAL DEFAULT 0.0'),
        ('products', 'length_cm', 'REAL DEFAULT 0.0'),
        ('products', 'width_cm', 'REAL DEFAULT 0.0'),
        ('products', 'height_cm', 'REAL DEFAULT 0.0'),
        ('products', 'shipping_method', "TEXT DEFAULT ''"),
        ('products', 'shipping_cost_gbp', 'REAL DEFAULT 0.0'),
        # shipping_pricing_mode: '' = use Settings default, 'flat' = flat rate,
        # 'calculated' = eBay calculates from weight/dims/postcode.
        ('products', 'shipping_pricing_mode', "TEXT DEFAULT ''"),
        ('products', 'images', "TEXT DEFAULT ''"),
        ('products', 'item_specifics', "TEXT DEFAULT ''"),
        # Supplier ground-truth description from CSV/ODS "Product Description" column.
        # Used as the primary source of truth for what is physically in the pallet —
        # Amazon variant metadata can describe a different colour/variant (see the
        # Busybee Christmas Tree case: Amazon says Colour:Champagne + Light Color:
        # Warm white, supplier says "Green Artificial Tree, Green Wire String Lights").
        ('products', 'supplier_description', "TEXT DEFAULT ''"),
        # JSON array of locally-uploaded image paths (relative to /static, e.g.
        # "uploads/products/42/abc.jpg"). Shown before Amazon images in the gallery
        # and prepended to eBay listings. Lets the uncle override wrong variant
        # photos with his own shots of the actual pallet contents.
        ('products', 'custom_images', "TEXT DEFAULT ''"),
        ('ebay_listings', 'category_id', "TEXT DEFAULT ''"),
        ('ebay_listings', 'item_specifics', "TEXT DEFAULT ''"),
        # sales.source: 'ebay' for orders synced from eBay API, 'private' for
        # items the uncle sold in person / to a friend / cash-in-hand — still
        # needs to count toward his revenue and profit on the dashboard.
        ('sales', 'source', "TEXT DEFAULT 'ebay'"),
        ('sales', 'notes', "TEXT DEFAULT ''"),
        # pallets.amazon_domain: which Amazon locale this pallet's ASINs belong
        # to. The SAME ASIN can point to different products across locales
        # (e.g. on .co.uk it's a white Christmas tree, on .de it's the green
        # one uncle actually got) — so the scraper MUST be told which locale
        # the supplier sourced from, otherwise we pull images/specs for a
        # completely different product. No default — the uncle picks per-pallet
        # when adding the pallet (empty = scraping blocked until set).
        ('pallets', 'amazon_domain', "TEXT DEFAULT ''"),
    ]
    for table, col, col_type in _migrations:
        try:
            conn.execute(f'SELECT {col} FROM {table} LIMIT 1')
        except:
            try:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {col_type}')
                conn.commit()
            except:
                pass


def get_config(key, default=''):
    """Get a config value by key."""
    conn = get_db()
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row['value'] if row else default


def set_config(key, value):
    """Set a config value (upsert)."""
    conn = get_db()
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, str(value), str(value))
    )
    conn.commit()


def query_db(query, args=(), one=False):
    """Execute a query and return results as list of dicts."""
    conn = get_db()
    cur = conn.execute(query, args)
    rows = cur.fetchall()
    if one:
        return dict(rows[0]) if rows else None
    return [dict(r) for r in rows]


def execute_db(query, args=()):
    """Execute an insert/update/delete and return lastrowid."""
    conn = get_db()
    cur = conn.execute(query, args)
    conn.commit()
    return cur.lastrowid
