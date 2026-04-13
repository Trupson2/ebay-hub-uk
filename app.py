"""
eBay Hub UK v1.0.0
Flask web application for eBay UK pallet reselling.
Dark cyberpunk theme, mobile-first design.
"""

import os
import csv
import io
import secrets
from datetime import datetime, timedelta

from flask import (
    Flask, request, redirect, url_for, flash,
    render_template_string, jsonify, g, session
)

from modules.database import (
    get_db, close_db, init_db,
    get_config, set_config,
    query_db, execute_db
)
from modules.ebay_api import get_ebay_client
from modules.scraper import scrape_amazon_product, parse_specification, get_amazon_image_url

# ---------------------------------------------------------------------------
# Flask app setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=7)

# Initialise database on first request
with app.app_context():
    init_db()


@app.teardown_appcontext
def teardown_db(exception):
    close_db()


@app.before_request
def before_request():
    """Attach CSP nonce and check authentication."""
    request._csp_nonce = secrets.token_hex(16)

    # Simple PIN/password auth
    if request.path.startswith('/static') or request.path == '/login':
        return
    if not session.get('authenticated'):
        pin = get_config('app_pin', '')
        if pin:  # PIN is set — require login
            return redirect('/login')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        entered = request.form.get('pin', '')
        stored = get_config('app_pin', '')
        if entered == stored:
            session['authenticated'] = True
            session.permanent = True
            flash('Welcome back!', 'success')
            return redirect('/')
        else:
            flash('Wrong PIN.', 'error')
    return render_template_string(LOGIN_TEMPLATE)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


LOGIN_TEMPLATE = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login - eBay Hub UK</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a14;color:#e2e8f0;font-family:'Space Grotesk',sans-serif;display:flex;align-items:center;justify-content:center;height:100vh}
.login-box{background:rgba(15,15,30,0.8);border:1px solid rgba(143,245,255,0.12);padding:40px;max-width:360px;width:90%;text-align:center}
h1{font-size:1.4rem;color:#8ff5ff;margin-bottom:8px}
p{color:#64748b;font-size:0.85rem;margin-bottom:24px}
input{width:100%;padding:14px;background:#0a0a14;border:1px solid rgba(143,245,255,0.15);color:#e2e8f0;font-size:1.2rem;text-align:center;letter-spacing:8px;font-family:'Space Grotesk',sans-serif;margin-bottom:16px}
input:focus{outline:none;border-color:#8ff5ff}
button{width:100%;padding:14px;background:#8ff5ff;color:#0a0a14;border:none;font-weight:700;font-size:1rem;cursor:pointer;font-family:'Space Grotesk',sans-serif}
button:hover{background:#beee00}
.flash{padding:10px;margin-bottom:16px;font-size:0.85rem;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#ef4444}
</style></head><body>
<div class="login-box">
<h1>eBay Hub UK</h1>
<p>Enter your PIN to continue</p>
{% with messages = get_flashed_messages() %}{% if messages %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endif %}{% endwith %}
<form method="POST">
<input type="password" name="pin" placeholder="PIN" autofocus required>
<button type="submit">Unlock</button>
</form>
</div>
</body></html>"""


@app.after_request
def add_security_headers(response):
    """Minimal security headers — no strict CSP for simplicity."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def nonce():
    return getattr(request, '_csp_nonce', '')


def amazon_image(asin):
    """Build Amazon product image URL from ASIN."""
    if asin:
        return f"https://images-na.ssl-images-amazon.com/images/I/{asin}._AC_SL1500_.jpg"
    return ""


def fmt_gbp(val):
    """Format a number as GBP."""
    try:
        return f"\u00a3{float(val):,.2f}"
    except (TypeError, ValueError):
        return "\u00a30.00"


def fmt_date(val):
    """Format an ISO date string nicely."""
    if not val:
        return "-"
    try:
        dt = datetime.fromisoformat(str(val).replace('Z', '+00:00'))
        return dt.strftime("%d %b %Y")
    except Exception:
        return str(val)[:10] if val else "-"


def fmt_datetime(val):
    """Format an ISO datetime string nicely."""
    if not val:
        return "-"
    try:
        dt = datetime.fromisoformat(str(val).replace('Z', '+00:00'))
        return dt.strftime("%d %b %Y %H:%M")
    except Exception:
        return str(val)[:16] if val else "-"


def condition_label(cond):
    """Human-friendly condition label."""
    labels = {
        'new': 'New',
        'like_new': 'Like New',
        'used': 'Used',
        'damaged': 'Damaged'
    }
    return labels.get(cond, cond or 'Unknown')


def status_color(status):
    """CSS class for status badges."""
    colors = {
        'active': 'badge-cyan',
        'warehouse': 'badge-purple',
        'listed': 'badge-cyan',
        'sold': 'badge-lime',
        'shipped': 'badge-lime',
        'delivered': 'badge-lime',
        'draft': 'badge-muted',
        'ended': 'badge-muted',
        'archived': 'badge-muted',
        'new': 'badge-pink',
    }
    return colors.get(status, 'badge-muted')


# Register template context
@app.context_processor
def inject_helpers():
    return dict(
        nonce=nonce,
        amazon_image=amazon_image,
        fmt_gbp=fmt_gbp,
        fmt_date=fmt_date,
        fmt_datetime=fmt_datetime,
        condition_label=condition_label,
        status_color=status_color,
        now=datetime.utcnow
    )


# ---------------------------------------------------------------------------
# Dashboard stats helpers
# ---------------------------------------------------------------------------

def get_dashboard_stats():
    """Compute dashboard statistics."""
    today = datetime.utcnow().strftime('%Y-%m-%d')
    week_ago = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    month_ago = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')

    # Sales totals
    sales_today = query_db(
        "SELECT COALESCE(SUM(price_gbp), 0) as total, COUNT(*) as cnt "
        "FROM sales WHERE DATE(sold_at) = ?", (today,), one=True
    )
    sales_week = query_db(
        "SELECT COALESCE(SUM(price_gbp), 0) as total, COUNT(*) as cnt "
        "FROM sales WHERE DATE(sold_at) >= ?", (week_ago,), one=True
    )
    sales_month = query_db(
        "SELECT COALESCE(SUM(price_gbp), 0) as total, COUNT(*) as cnt "
        "FROM sales WHERE DATE(sold_at) >= ?", (month_ago,), one=True
    )
    sales_all = query_db(
        "SELECT COALESCE(SUM(price_gbp), 0) as total, COUNT(*) as cnt FROM sales",
        one=True
    )

    # Counts
    active_listings = query_db(
        "SELECT COUNT(*) as cnt FROM ebay_listings WHERE status = 'active'", one=True
    )['cnt']
    to_ship = query_db(
        "SELECT COUNT(*) as cnt FROM sales WHERE status = 'new'", one=True
    )['cnt']
    total_products = query_db(
        "SELECT COUNT(*) as cnt FROM products", one=True
    )['cnt']
    total_pallets = query_db(
        "SELECT COUNT(*) as cnt FROM pallets", one=True
    )['cnt']
    warehouse_products = query_db(
        "SELECT COUNT(*) as cnt FROM products WHERE status = 'warehouse'", one=True
    )['cnt']

    # Frozen capital: cost of pallets with unsold products
    frozen = query_db(
        "SELECT COALESCE(SUM(p.purchase_price_gbp), 0) as total "
        "FROM pallets p WHERE p.status = 'active'",
        one=True
    )['total']

    # Total cost for profit calculation
    total_cost = query_db(
        "SELECT COALESCE(SUM(purchase_price_gbp), 0) as total FROM pallets",
        one=True
    )['total']

    total_revenue = sales_all['total']
    total_profit = total_revenue - total_cost

    # Monthly revenue data (last 6 months) for chart
    chart_data = []
    for i in range(5, -1, -1):
        d = datetime.utcnow() - timedelta(days=30 * i)
        month_start = d.replace(day=1).strftime('%Y-%m-%d')
        if i > 0:
            next_d = datetime.utcnow() - timedelta(days=30 * (i - 1))
            month_end = next_d.replace(day=1).strftime('%Y-%m-%d')
        else:
            month_end = '2099-12-31'
        row = query_db(
            "SELECT COALESCE(SUM(price_gbp), 0) as rev FROM sales "
            "WHERE DATE(sold_at) >= ? AND DATE(sold_at) < ?",
            (month_start, month_end), one=True
        )
        chart_data.append({
            'label': d.strftime('%b %Y'),
            'revenue': round(row['rev'], 2)
        })

    return {
        'sales_today': sales_today,
        'sales_week': sales_week,
        'sales_month': sales_month,
        'sales_all': sales_all,
        'active_listings': active_listings,
        'to_ship': to_ship,
        'total_products': total_products,
        'total_pallets': total_pallets,
        'warehouse_products': warehouse_products,
        'frozen_capital': frozen,
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'total_profit': total_profit,
        'chart_data': chart_data,
    }


# ===================================================================
# POST-only routes (no template rendering)
# ===================================================================

@app.route('/pallets/add', methods=['POST'])
def pallet_add():
    name = request.form.get('name', '').strip()
    supplier = request.form.get('supplier', '').strip()
    price = request.form.get('purchase_price_gbp', '0')
    date = request.form.get('purchase_date', '')
    notes = request.form.get('notes', '').strip()
    if not name:
        flash('Pallet name is required.', 'error')
        return redirect(url_for('pallets_list'))

    try:
        price = float(price)
    except ValueError:
        price = 0.0

    pallet_id = execute_db(
        "INSERT INTO pallets (name, supplier, purchase_price_gbp, purchase_date, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, supplier, price, date, notes)
    )

    # Import products from uploaded CSV/XLSX file
    imported = 0
    scraped_cnt = 0
    spec_file = request.files.get('spec_file')
    if spec_file and spec_file.filename:
        from modules.scraper import scrape_amazon_product, get_amazon_image_url
        fname = spec_file.filename.lower()
        try:
            rows = []
            if fname.endswith(('.xlsx', '.xls')):
                import openpyxl
                wb = openpyxl.load_workbook(spec_file, data_only=True)
                ws = wb.active
                headers = [str(c.value or '').strip().lower() for c in ws[1]]
                for row_cells in ws.iter_rows(min_row=2, values_only=True):
                    row = {}
                    for i, val in enumerate(row_cells):
                        if i < len(headers):
                            row[headers[i]] = str(val or '').strip()
                    rows.append(row)
            elif fname.endswith('.csv'):
                raw = spec_file.stream.read()
                for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
                    try:
                        text = raw.decode(enc)
                        break
                    except:
                        continue
                else:
                    text = raw.decode('utf-8', errors='replace')
                first_line = text.split('\n')[0]
                delimiter = ';' if first_line.count(';') > first_line.count(',') else ','
                reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
                rows = list(reader)

            def get_col(row, *names):
                # Exact match first, then substring
                for n in names:
                    for key in row:
                        if key and key.lower().strip() == n:
                            val = row[key].strip() if row[key] else ''
                            if val and val.lower() not in ('none', 'nan', 'null'):
                                return val
                for n in names:
                    for key in row:
                        if key and n in key.lower() and 'category' not in key.lower():
                            val = row[key].strip() if row[key] else ''
                            if val and val.lower() not in ('none', 'nan', 'null'):
                                return val
                return ''

            for row in rows:
                prod_name = get_col(row, 'name', 'title', 'product', 'nazwa', 'description')
                if not prod_name:
                    continue
                asin = get_col(row, 'asin').upper()
                ean = get_col(row, 'ean', 'barcode', 'upc', 'gtin')
                try:
                    qty = int(float(get_col(row, 'quantity', 'qty', 'ilosc', 'amount') or '1'))
                except:
                    qty = 1
                cond = get_col(row, 'condition', 'state', 'stan').lower()
                if cond not in ('new', 'like_new', 'used', 'damaged'):
                    cond = 'new'
                try:
                    ebay_price = float(get_col(row, 'price', 'ebay_price', 'rrp', 'cena') or '0')
                except:
                    ebay_price = 0.0

                image_url = get_amazon_image_url(asin) if asin else ''

                # Auto-scrape Amazon UK
                if asin:
                    try:
                        data = scrape_amazon_product(asin)
                        if data:
                            if data.get('title') and len(data['title']) > len(prod_name):
                                prod_name = data['title']
                            if data.get('image_url'):
                                image_url = data['image_url']
                            if data.get('price') and ebay_price == 0:
                                ebay_price = data['price']
                            scraped_cnt += 1
                    except:
                        pass

                execute_db(
                    "INSERT INTO products (pallet_id, name, asin, ean, quantity, "
                    "condition, ebay_price_gbp, image_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (pallet_id, prod_name, asin, ean, qty, cond, ebay_price, image_url)
                )
                imported += 1
        except Exception as e:
            flash(f'File import error: {e}', 'error')

    msg = f'Pallet "{name}" added successfully.'
    if imported > 0:
        msg += f' Imported {imported} products'
        if scraped_cnt > 0:
            msg += f' (scraped {scraped_cnt} from Amazon UK)'
        msg += '.'
    flash(msg, 'success')
    return redirect(url_for('pallet_detail', pallet_id=pallet_id) if imported > 0 else url_for('pallets_list'))


@app.route('/pallet/<int:pallet_id>/delete', methods=['POST'])
def pallet_delete(pallet_id):
    pallet = query_db("SELECT * FROM pallets WHERE id = ?", (pallet_id,), one=True)
    if not pallet:
        flash('Pallet not found.', 'error')
        return redirect(url_for('pallets_list'))
    execute_db("DELETE FROM products WHERE pallet_id = ?", (pallet_id,))
    execute_db("DELETE FROM pallets WHERE id = ?", (pallet_id,))
    flash(f'Pallet "{pallet["name"]}" deleted.', 'success')
    return redirect(url_for('pallets_list'))


@app.route('/pallet/<int:pallet_id>/archive', methods=['POST'])
def pallet_archive(pallet_id):
    execute_db("UPDATE pallets SET status = 'archived' WHERE id = ?", (pallet_id,))
    flash('Pallet archived.', 'success')
    return redirect(url_for('pallet_detail', pallet_id=pallet_id))


@app.route('/pallet/<int:pallet_id>/scrape', methods=['POST'])
def pallet_scrape(pallet_id):
    """Scrape Amazon UK for all products with ASINs but no image_url."""
    pallet = query_db("SELECT * FROM pallets WHERE id = ?", (pallet_id,), one=True)
    if not pallet:
        flash('Pallet not found.', 'error')
        return redirect(url_for('pallets_list'))

    from modules.scraper import get_amazon_image_urls
    import requests as _req

    products = query_db(
        "SELECT * FROM products WHERE pallet_id = ? AND asin != ''",
        (pallet_id,)
    )

    if not products:
        flash('No products with ASINs to scrape.', 'info')
        return redirect(url_for('pallet_detail', pallet_id=pallet_id))

    updated = 0
    for prod in products:
        # Try scraping Amazon page first
        amz_data = scrape_amazon_product(prod['asin'])
        if amz_data and amz_data.get('image_url'):
            new_name = amz_data.get('title') or prod['name']
            new_image = amz_data['image_url']
            new_price = amz_data.get('price') or prod['ebay_price_gbp']
            execute_db(
                "UPDATE products SET name = ?, image_url = ?, ebay_price_gbp = ? WHERE id = ?",
                (new_name, new_image, new_price, prod['id'])
            )
            updated += 1
        else:
            # Fallback: try multiple image URL formats
            for url in get_amazon_image_urls(prod['asin']):
                try:
                    r = _req.head(url, timeout=5, allow_redirects=True)
                    if r.status_code == 200 and 'image' in r.headers.get('content-type', ''):
                        execute_db("UPDATE products SET image_url = ? WHERE id = ?", (url, prod['id']))
                        updated += 1
                        break
                except:
                    continue

    flash(f'Updated {updated}/{len(products)} products from Amazon UK.', 'success')
    return redirect(url_for('pallet_detail', pallet_id=pallet_id))


@app.route('/pallet/<int:pallet_id>/add_product', methods=['POST'])
def add_product(pallet_id):
    name = request.form.get('name', '').strip()
    asin = request.form.get('asin', '').strip()
    ean = request.form.get('ean', '').strip()
    quantity = request.form.get('quantity', '1')
    condition = request.form.get('condition', 'new')
    ebay_price = request.form.get('ebay_price_gbp', '0')
    category = request.form.get('category', '').strip()

    if not name:
        flash('Product name is required.', 'error')
        return redirect(url_for('pallet_detail', pallet_id=pallet_id))

    try:
        quantity = int(quantity)
    except ValueError:
        quantity = 1
    try:
        ebay_price = float(ebay_price)
    except ValueError:
        ebay_price = 0.0

    pallet = query_db("SELECT * FROM pallets WHERE id = ?", (pallet_id,), one=True)
    product_count = query_db(
        "SELECT COUNT(*) as cnt FROM products WHERE pallet_id = ?",
        (pallet_id,), one=True
    )['cnt']
    cost_per_unit = (pallet['purchase_price_gbp'] or 0) / max(product_count + 1, 1)

    image_url = amazon_image(asin)

    execute_db(
        "INSERT INTO products (pallet_id, name, asin, ean, quantity, condition, "
        "ebay_price_gbp, cost_per_unit, category, image_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pallet_id, name, asin, ean, quantity, condition,
         ebay_price, cost_per_unit, category, image_url)
    )
    flash(f'Product "{name}" added.', 'success')
    return redirect(url_for('pallet_detail', pallet_id=pallet_id))


@app.route('/product/<int:product_id>/update', methods=['POST'])
def product_update(product_id):
    name = request.form.get('name', '').strip()
    asin = request.form.get('asin', '').strip()
    ean = request.form.get('ean', '').strip()
    quantity = request.form.get('quantity', '1')
    condition = request.form.get('condition', 'new')
    ebay_price = request.form.get('ebay_price_gbp', '0')
    category = request.form.get('category', '').strip()
    status = request.form.get('status', 'warehouse')

    try:
        quantity = int(quantity)
    except ValueError:
        quantity = 1
    try:
        ebay_price = float(ebay_price)
    except ValueError:
        ebay_price = 0.0

    image_url = amazon_image(asin)

    execute_db(
        "UPDATE products SET name=?, asin=?, ean=?, quantity=?, condition=?, "
        "ebay_price_gbp=?, category=?, image_url=?, status=? WHERE id=?",
        (name, asin, ean, quantity, condition, ebay_price,
         category, image_url, status, product_id)
    )
    flash('Product updated.', 'success')
    return redirect(url_for('product_detail', product_id=product_id))


@app.route('/product/<int:product_id>/delete', methods=['POST'])
def product_delete(product_id):
    product = query_db("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('pallets_list'))
    pallet_id = product['pallet_id']
    execute_db("DELETE FROM ebay_listings WHERE product_id = ?", (product_id,))
    execute_db("DELETE FROM sales WHERE product_id = ?", (product_id,))
    execute_db("DELETE FROM products WHERE id = ?", (product_id,))
    flash('Product deleted.', 'success')
    return redirect(url_for('pallet_detail', pallet_id=pallet_id))


@app.route('/product/<int:product_id>/list_ebay', methods=['POST'])
def list_on_ebay(product_id):
    product = query_db("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('pallets_list'))

    title = request.form.get('title', product['name'])
    description = request.form.get('description', '')
    price = request.form.get('price', str(product['ebay_price_gbp']))

    try:
        price = float(price)
    except ValueError:
        price = product['ebay_price_gbp']

    listing_id = execute_db(
        "INSERT INTO ebay_listings (product_id, title, description, price_gbp, status) "
        "VALUES (?, ?, ?, ?, 'draft')",
        (product_id, title, description, price)
    )

    ebay = get_ebay_client(get_config)
    if ebay.is_configured():
        result = ebay.create_listing({
            'title': title,
            'description': description,
            'price': price,
            'condition': product['condition'],
            'quantity': product['quantity'],
            'ean': product['ean'],
            'image_urls': [product['image_url']] if product['image_url'] else []
        })
        if result and result.get('success'):
            execute_db(
                "UPDATE ebay_listings SET ebay_item_id=?, status='active' WHERE id=?",
                (result['ebay_item_id'], listing_id)
            )
            execute_db(
                "UPDATE products SET status='listed' WHERE id=?", (product_id,)
            )
            flash('Listed on eBay successfully!', 'success')
        else:
            error = result.get('error', 'Unknown error') if result else 'API error'
            flash(f'Draft saved. eBay API: {error}', 'warning')
    else:
        flash('Draft listing saved. Configure eBay API in Settings to publish.', 'info')

    return redirect(url_for('product_detail', product_id=product_id))


@app.route('/order/<int:order_id>/ship', methods=['POST'])
def order_mark_shipped(order_id):
    execute_db(
        "UPDATE sales SET status='shipped', shipped_at=CURRENT_TIMESTAMP WHERE id=?",
        (order_id,)
    )
    order = query_db("SELECT * FROM sales WHERE id = ?", (order_id,), one=True)
    if order and order['product_id']:
        execute_db(
            "UPDATE products SET status='shipped' WHERE id=?",
            (order['product_id'],)
        )
    flash('Order marked as shipped.', 'success')
    return redirect(url_for('orders_list'))


@app.route('/api/add_sale', methods=['POST'])
def api_add_sale():
    product_id = request.form.get('product_id')
    price = request.form.get('price_gbp', '0')
    buyer = request.form.get('buyer', '')
    address = request.form.get('shipping_address', '')

    try:
        price = float(price)
    except ValueError:
        price = 0.0

    execute_db(
        "INSERT INTO sales (product_id, price_gbp, buyer, shipping_address) "
        "VALUES (?, ?, ?, ?)",
        (product_id, price, buyer, address)
    )

    if product_id:
        execute_db("UPDATE products SET status='sold' WHERE id=?", (product_id,))

    flash('Sale recorded.', 'success')
    return redirect(url_for('orders_list'))


# ===================================================================
# CSS THEME
# ===================================================================

CSS_THEME = """
/* eBay Hub UK - Cyberpunk Theme */
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');

:root {
    --cyan: #8ff5ff;
    --lime: #beee00;
    --pink: #ff6b9b;
    --purple: #a855f7;
    --bg-dark: #0a0a0f;
    --bg-card: #12121a;
    --bg-card-hover: #1a1a26;
    --bg-input: #1a1a26;
    --border: #2a2a3a;
    --text: #e0e0e8;
    --text-muted: #6a6a80;
    --danger: #ff4444;
    --warning: #ffaa00;
    --radius: 12px;
    --radius-sm: 8px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: 'Space Grotesk', sans-serif;
    background: var(--bg-dark);
    color: var(--text);
    min-height: 100vh;
    line-height: 1.5;
}

/* Scrollbar */
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-track { background: var(--bg-dark); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--purple); }

/* Layout */
.app-container {
    max-width: 1280px;
    margin: 0 auto;
    padding: 0 16px 80px 16px;
}

/* Navigation */
.navbar {
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    padding: 12px 0;
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(10px);
}
.navbar-inner {
    max-width: 1280px;
    margin: 0 auto;
    padding: 0 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
}
.navbar-brand {
    display: flex;
    align-items: center;
    gap: 8px;
    text-decoration: none;
    font-weight: 700;
    font-size: 1.2rem;
    color: var(--cyan);
}
.navbar-brand .material-symbols-outlined { font-size: 28px; }
.nav-links {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
}
.nav-links a {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 8px 12px;
    color: var(--text-muted);
    text-decoration: none;
    border-radius: var(--radius-sm);
    font-size: 0.85rem;
    font-weight: 500;
    transition: all 0.2s;
}
.nav-links a:hover, .nav-links a.active {
    color: var(--cyan);
    background: rgba(143, 245, 255, 0.08);
}
.nav-links a .material-symbols-outlined { font-size: 20px; }

/* Page header */
.page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    margin: 24px 0 20px 0;
}
.page-header h1 {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--text);
}
.page-header h1 span { color: var(--cyan); }

/* Cards */
.card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    transition: border-color 0.2s;
}
.card:hover { border-color: rgba(143, 245, 255, 0.2); }
.card-title {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 8px;
}
.card-value {
    font-size: 1.8rem;
    font-weight: 700;
    color: var(--cyan);
}
.card-value.lime { color: var(--lime); }
.card-value.pink { color: var(--pink); }
.card-value.purple { color: var(--purple); }
.card-subtitle {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-top: 4px;
}

/* Stats grid */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}

/* Tables */
.table-wrap {
    overflow-x: auto;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    background: var(--bg-card);
}
table {
    width: 100%;
    border-collapse: collapse;
}
th {
    text-align: left;
    padding: 12px 16px;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
}
td {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--bg-card-hover); }
.table-link {
    color: var(--cyan);
    text-decoration: none;
    font-weight: 500;
}
.table-link:hover { text-decoration: underline; }

/* Badges */
.badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.badge-cyan { background: rgba(143, 245, 255, 0.12); color: var(--cyan); }
.badge-lime { background: rgba(190, 238, 0, 0.12); color: var(--lime); }
.badge-pink { background: rgba(255, 107, 155, 0.12); color: var(--pink); }
.badge-purple { background: rgba(168, 85, 247, 0.12); color: var(--purple); }
.badge-muted { background: rgba(106, 106, 128, 0.12); color: var(--text-muted); }
.badge-danger { background: rgba(255, 68, 68, 0.12); color: var(--danger); }

/* Buttons */
.btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 10px 20px;
    border: none;
    border-radius: var(--radius-sm);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    text-decoration: none;
    white-space: nowrap;
}
.btn .material-symbols-outlined { font-size: 20px; }
.btn-cyan {
    background: var(--cyan);
    color: #0a0a0f;
}
.btn-cyan:hover { background: #adf8ff; box-shadow: 0 0 20px rgba(143, 245, 255, 0.3); }
.btn-lime {
    background: var(--lime);
    color: #0a0a0f;
}
.btn-lime:hover { background: #d4ff2a; box-shadow: 0 0 20px rgba(190, 238, 0, 0.3); }
.btn-pink {
    background: var(--pink);
    color: #0a0a0f;
}
.btn-pink:hover { background: #ff8db5; box-shadow: 0 0 20px rgba(255, 107, 155, 0.3); }
.btn-purple {
    background: var(--purple);
    color: #fff;
}
.btn-purple:hover { background: #b86ef9; box-shadow: 0 0 20px rgba(168, 85, 247, 0.3); }
.btn-outline {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text);
}
.btn-outline:hover { border-color: var(--cyan); color: var(--cyan); }
.btn-danger {
    background: rgba(255, 68, 68, 0.15);
    color: var(--danger);
    border: 1px solid rgba(255, 68, 68, 0.3);
}
.btn-danger:hover { background: rgba(255, 68, 68, 0.25); }
.btn-sm { padding: 6px 14px; font-size: 0.8rem; }
.btn-block { width: 100%; justify-content: center; }

/* Filter tabs */
.filter-tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 20px;
    flex-wrap: wrap;
}
.filter-tab {
    padding: 8px 16px;
    border-radius: var(--radius-sm);
    background: var(--bg-card);
    border: 1px solid var(--border);
    color: var(--text-muted);
    text-decoration: none;
    font-size: 0.85rem;
    font-weight: 500;
    transition: all 0.2s;
}
.filter-tab:hover { border-color: var(--cyan); color: var(--cyan); }
.filter-tab.active {
    background: rgba(143, 245, 255, 0.1);
    border-color: var(--cyan);
    color: var(--cyan);
}
.filter-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 20px;
    height: 20px;
    padding: 0 6px;
    border-radius: 10px;
    background: rgba(143, 245, 255, 0.15);
    font-size: 0.7rem;
    margin-left: 6px;
}

/* Forms */
.form-group {
    margin-bottom: 16px;
}
.form-label {
    display: block;
    margin-bottom: 6px;
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--text-muted);
}
.form-control {
    width: 100%;
    padding: 10px 14px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.9rem;
    transition: border-color 0.2s;
}
.form-control:focus {
    outline: none;
    border-color: var(--cyan);
    box-shadow: 0 0 0 3px rgba(143, 245, 255, 0.1);
}
select.form-control {
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg width='12' height='8' viewBox='0 0 12 8' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%236a6a80' stroke-width='2' fill='none'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 14px center;
    padding-right: 36px;
}
textarea.form-control { resize: vertical; min-height: 80px; }
.form-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
}
.form-hint {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: 4px;
}

/* Modal */
.modal-overlay {
    display: none;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(4px);
    z-index: 200;
    align-items: center;
    justify-content: center;
    padding: 16px;
}
.modal-overlay.active { display: flex; }
.modal {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    width: 100%;
    max-width: 520px;
    max-height: 90vh;
    overflow-y: auto;
}
.modal-title {
    font-size: 1.2rem;
    font-weight: 700;
    margin-bottom: 20px;
    color: var(--cyan);
}

/* Flash messages */
.flash-container { margin: 16px 0; }
.flash {
    padding: 12px 16px;
    border-radius: var(--radius-sm);
    margin-bottom: 8px;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 8px;
}
.flash-success { background: rgba(190, 238, 0, 0.1); border: 1px solid rgba(190, 238, 0, 0.3); color: var(--lime); }
.flash-error { background: rgba(255, 68, 68, 0.1); border: 1px solid rgba(255, 68, 68, 0.3); color: var(--danger); }
.flash-warning { background: rgba(255, 170, 0, 0.1); border: 1px solid rgba(255, 170, 0, 0.3); color: var(--warning); }
.flash-info { background: rgba(143, 245, 255, 0.1); border: 1px solid rgba(143, 245, 255, 0.3); color: var(--cyan); }

/* Product grid */
.product-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}
.product-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    transition: all 0.2s;
    text-decoration: none;
    color: var(--text);
    display: block;
}
.product-card:hover {
    border-color: var(--cyan);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}
.product-card-img {
    width: 100%;
    height: 160px;
    object-fit: contain;
    background: #1a1a26;
    padding: 12px;
}
.product-card-body { padding: 14px; }
.product-card-name {
    font-weight: 600;
    font-size: 0.9rem;
    margin-bottom: 6px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.product-card-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 8px;
}
.product-card-price {
    font-weight: 700;
    color: var(--lime);
    font-size: 1.1rem;
}

/* Chart bar */
.chart-container { margin-bottom: 24px; }
.chart-bars {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    height: 160px;
    padding: 0 4px;
}
.chart-bar-wrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    height: 100%;
    justify-content: flex-end;
}
.chart-bar {
    width: 100%;
    max-width: 60px;
    background: linear-gradient(to top, var(--cyan), var(--purple));
    border-radius: 4px 4px 0 0;
    min-height: 2px;
    transition: height 0.3s;
}
.chart-bar-label {
    font-size: 0.65rem;
    color: var(--text-muted);
    margin-top: 6px;
    text-align: center;
}
.chart-bar-value {
    font-size: 0.7rem;
    color: var(--cyan);
    margin-bottom: 4px;
    font-weight: 600;
}

/* Detail page layout */
.detail-header {
    display: flex;
    gap: 24px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}
.detail-image {
    width: 200px;
    height: 200px;
    object-fit: contain;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px;
    flex-shrink: 0;
}
.detail-info { flex: 1; min-width: 250px; }
.detail-info h2 {
    font-size: 1.3rem;
    margin-bottom: 12px;
}
.detail-meta {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 6px 16px;
    font-size: 0.9rem;
}
.detail-meta dt { color: var(--text-muted); }
.detail-meta dd { color: var(--text); }

/* Section headings */
.section-title {
    font-size: 1.1rem;
    font-weight: 600;
    margin: 24px 0 16px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
    color: var(--cyan);
}

/* Empty state */
.empty-state {
    text-align: center;
    padding: 48px 20px;
    color: var(--text-muted);
}
.empty-state .material-symbols-outlined {
    font-size: 48px;
    margin-bottom: 12px;
    opacity: 0.3;
}
.empty-state p { font-size: 1rem; margin-bottom: 16px; }

/* Utility */
.text-cyan { color: var(--cyan); }
.text-lime { color: var(--lime); }
.text-pink { color: var(--pink); }
.text-purple { color: var(--purple); }
.text-muted { color: var(--text-muted); }
.text-danger { color: var(--danger); }
.text-right { text-align: right; }
.mt-16 { margin-top: 16px; }
.mb-16 { margin-bottom: 16px; }
.flex-between {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
}
.gap-8 { gap: 8px; }
.d-flex { display: flex; }
.align-center { align-items: center; }
.inline-form { display: inline; }

/* Responsive */
@media (max-width: 768px) {
    .navbar-inner { flex-direction: column; align-items: flex-start; }
    .nav-links { width: 100%; overflow-x: auto; }
    .page-header { flex-direction: column; align-items: flex-start; }
    .page-header h1 { font-size: 1.2rem; }
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    .card-value { font-size: 1.4rem; }
    .detail-header { flex-direction: column; }
    .detail-image { width: 100%; height: 200px; }
    .form-row { grid-template-columns: 1fr; }
    .product-grid { grid-template-columns: 1fr; }
    .modal { padding: 16px; }
}

@media (max-width: 480px) {
    .stats-grid { grid-template-columns: 1fr; }
    .nav-links a span.nav-text { display: none; }
}
"""

# ===================================================================
# TEMPLATES
# ===================================================================

# -------------------------------------------------------------------
# Base template (layout wrapper)
# -------------------------------------------------------------------
TEMPLATE_BASE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title | default('eBay Hub UK') }}</title>
    <meta name="theme-color" content="#8ff5ff">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <link rel="manifest" href="/static/manifest.json">
    <link rel="apple-touch-icon" href="/static/icon-192.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link nonce="{{ nonce() }}" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link nonce="{{ nonce() }}" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap" rel="stylesheet">
    <style nonce="{{ nonce() }}">""" + CSS_THEME + """</style>
</head>
<body>

<nav class="navbar">
    <div class="navbar-inner">
        <a href="/" class="navbar-brand">
            <span class="material-symbols-outlined">hub</span>
            eBay Hub UK
        </a>
        <div class="nav-links">
            <a href="/" class="{{ 'active' if active_page == 'dashboard' else '' }}">
                <span class="material-symbols-outlined">dashboard</span>
                <span class="nav-text">Dashboard</span>
            </a>
            <a href="/pallets" class="{{ 'active' if active_page == 'pallets' else '' }}">
                <span class="material-symbols-outlined">inventory_2</span>
                <span class="nav-text">Pallets</span>
            </a>
            <a href="/listings" class="{{ 'active' if active_page == 'listings' else '' }}">
                <span class="material-symbols-outlined">sell</span>
                <span class="nav-text">Listings</span>
            </a>
            <a href="/orders" class="{{ 'active' if active_page == 'orders' else '' }}">
                <span class="material-symbols-outlined">local_shipping</span>
                <span class="nav-text">Orders</span>
            </a>
            <a href="/settings" class="{{ 'active' if active_page == 'settings' else '' }}">
                <span class="material-symbols-outlined">settings</span>
                <span class="nav-text">Settings</span>
            </a>
            <a href="/logout" style="color:#ef4444">
                <span class="material-symbols-outlined">logout</span>
            </a>
        </div>
    </div>
</nav>

<div class="app-container">
    {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
    <div class="flash-container">
        {% for category, message in messages %}
        <div class="flash flash-{{ category }}">
            <span class="material-symbols-outlined">
                {% if category == 'success' %}check_circle{% elif category == 'error' %}error{% elif category == 'warning' %}warning{% else %}info{% endif %}
            </span>
            {{ message }}
        </div>
        {% endfor %}
    </div>
    {% endif %}
    {% endwith %}

    {{ content }}
</div>

<!-- Loading Spinner Overlay -->
<div id="loadingOverlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:99999;align-items:center;justify-content:center;flex-direction:column;gap:16px">
    <div style="width:48px;height:48px;border:3px solid rgba(143,245,255,0.15);border-top:3px solid #8ff5ff;border-radius:50%;animation:spin 0.8s linear infinite"></div>
    <div id="loadingText" style="color:#8ff5ff;font-family:'Space Grotesk',sans-serif;font-size:0.95rem;font-weight:600">Processing...</div>
    <div style="color:rgba(255,255,255,0.4);font-size:0.75rem">Scraping Amazon UK may take a moment</div>
</div>
<style>@keyframes spin{to{transform:rotate(360deg)}}</style>
<script>
if('serviceWorker' in navigator){navigator.serviceWorker.register('/static/sw.js')}
// Show spinner on form submit (for imports/scraping)
document.querySelectorAll('form').forEach(function(f){
    f.addEventListener('submit', function(){
        var overlay = document.getElementById('loadingOverlay');
        var btn = f.querySelector('button[type="submit"]');
        var hasFile = f.querySelector('input[type="file"]');
        var isScrape = f.action && (f.action.includes('/scrape') || f.action.includes('/import') || f.action.includes('/add'));
        if(isScrape || hasFile){
            overlay.style.display='flex';
            if(btn) btn.disabled=true;
            var dots = 0;
            setInterval(function(){
                dots = (dots+1)%4;
                document.getElementById('loadingText').textContent = 'Importing & scraping' + '.'.repeat(dots);
            }, 500);
        }
    });
});
</script>
</body>
</html>"""

# -------------------------------------------------------------------
# Helper: wrap content in base
# -------------------------------------------------------------------
def render_page(content_template, page_title='eBay Hub UK', active_page='', **kwargs):
    """Render a content template inside the base layout."""
    from markupsafe import Markup
    content_html = render_template_string(content_template, **kwargs)
    return render_template_string(
        TEMPLATE_BASE,
        content=Markup(content_html),
        page_title=page_title,
        active_page=active_page,
        **kwargs
    )


# -------------------------------------------------------------------
# Dashboard Template
# -------------------------------------------------------------------
TEMPLATE_DASHBOARD_CONTENT = """
<div class="page-header">
    <h1><span>Dashboard</span></h1>
</div>

<div class="stats-grid">
    <div class="card">
        <div class="card-title">Today's Sales</div>
        <div class="card-value">{{ fmt_gbp(stats.sales_today.total) }}</div>
        <div class="card-subtitle">{{ stats.sales_today.cnt }} order{{ 's' if stats.sales_today.cnt != 1 }}</div>
    </div>
    <div class="card">
        <div class="card-title">This Week</div>
        <div class="card-value lime">{{ fmt_gbp(stats.sales_week.total) }}</div>
        <div class="card-subtitle">{{ stats.sales_week.cnt }} order{{ 's' if stats.sales_week.cnt != 1 }}</div>
    </div>
    <div class="card">
        <div class="card-title">This Month</div>
        <div class="card-value purple">{{ fmt_gbp(stats.sales_month.total) }}</div>
        <div class="card-subtitle">{{ stats.sales_month.cnt }} order{{ 's' if stats.sales_month.cnt != 1 }}</div>
    </div>
    <div class="card">
        <div class="card-title">Total Profit</div>
        <div class="card-value {{ 'lime' if stats.total_profit >= 0 else 'text-danger' }}">
            {{ fmt_gbp(stats.total_profit) }}
        </div>
        <div class="card-subtitle">Revenue: {{ fmt_gbp(stats.total_revenue) }}</div>
    </div>
</div>

<div class="stats-grid">
    <div class="card">
        <div class="card-title">Active Listings</div>
        <div class="card-value cyan">{{ stats.active_listings }}</div>
    </div>
    <div class="card">
        <div class="card-title">To Ship</div>
        <div class="card-value pink">{{ stats.to_ship }}</div>
        {% if stats.to_ship > 0 %}
        <a href="/orders?status=new" class="btn btn-pink btn-sm mt-16">
            <span class="material-symbols-outlined">local_shipping</span> View Orders
        </a>
        {% endif %}
    </div>
    <div class="card">
        <div class="card-title">Products</div>
        <div class="card-value purple">{{ stats.total_products }}</div>
        <div class="card-subtitle">{{ stats.warehouse_products }} in warehouse</div>
    </div>
    <div class="card">
        <div class="card-title">Frozen Capital</div>
        <div class="card-value">{{ fmt_gbp(stats.frozen_capital) }}</div>
        <div class="card-subtitle">{{ stats.total_pallets }} pallet{{ 's' if stats.total_pallets != 1 }}</div>
    </div>
</div>

<!-- Revenue Chart -->
<div class="card chart-container">
    <div class="card-title">Monthly Revenue</div>
    {% set max_rev = stats.chart_data | map(attribute='revenue') | max %}
    <div class="chart-bars">
        {% for bar in stats.chart_data %}
        <div class="chart-bar-wrap">
            <div class="chart-bar-value">{{ fmt_gbp(bar.revenue) }}</div>
            <div class="chart-bar" style="height: {{ (bar.revenue / max_rev * 120) if max_rev > 0 else 2 }}px"></div>
            <div class="chart-bar-label">{{ bar.label }}</div>
        </div>
        {% endfor %}
    </div>
</div>

<!-- Quick Actions -->
<div class="card">
    <div class="card-title">Quick Actions</div>
    <div class="d-flex gap-8" style="flex-wrap: wrap; margin-top: 12px;">
        <a href="/pallets" class="btn btn-cyan">
            <span class="material-symbols-outlined">add</span> New Pallet
        </a>
        <a href="/listings" class="btn btn-purple">
            <span class="material-symbols-outlined">sell</span> View Listings
        </a>
        <a href="/orders?status=new" class="btn btn-pink">
            <span class="material-symbols-outlined">local_shipping</span> Pending Orders
        </a>
        <a href="/settings" class="btn btn-outline">
            <span class="material-symbols-outlined">settings</span> Settings
        </a>
    </div>
</div>
"""

# -------------------------------------------------------------------
# Route: Dashboard
# -------------------------------------------------------------------
@app.route('/')
def dashboard():
    stats = get_dashboard_stats()
    return render_page(
        TEMPLATE_DASHBOARD_CONTENT,
        page_title='Dashboard - eBay Hub UK',
        active_page='dashboard',
        stats=stats
    )


# -------------------------------------------------------------------
# Pallets Template
# -------------------------------------------------------------------
TEMPLATE_PALLETS_CONTENT = """
<div class="page-header">
    <h1><span>Pallets</span></h1>
    <button class="btn btn-cyan" onclick="document.getElementById('addPalletModal').classList.add('active')">
        <span class="material-symbols-outlined">add</span> Add Pallet
    </button>
</div>

{% if pallets %}
<div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>Name</th>
                <th>Supplier</th>
                <th>Cost</th>
                <th>Products</th>
                <th>Sold</th>
                <th>Revenue</th>
                <th>ROI</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            {% for p in pallets %}
            <tr>
                <td>
                    <a href="/pallet/{{ p.id }}" class="table-link">{{ p.name }}</a>
                </td>
                <td class="text-muted">{{ p.supplier or '-' }}</td>
                <td>{{ fmt_gbp(p.purchase_price_gbp) }}</td>
                <td>{{ p.product_count }}</td>
                <td>{{ p.sold_count }}</td>
                <td class="text-lime">{{ fmt_gbp(p.revenue) }}</td>
                <td>
                    {% if p.purchase_price_gbp > 0 %}
                        {% set roi = ((p.revenue - p.purchase_price_gbp) / p.purchase_price_gbp * 100) %}
                        <span class="{{ 'text-lime' if roi >= 0 else 'text-danger' }}">
                            {{ "%.0f"|format(roi) }}%
                        </span>
                    {% else %}-{% endif %}
                </td>
                <td><span class="badge {{ status_color(p.status) }}">{{ p.status }}</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% else %}
<div class="empty-state">
    <span class="material-symbols-outlined">inventory_2</span>
    <p>No pallets yet. Add your first pallet to get started!</p>
    <button class="btn btn-cyan" onclick="document.getElementById('addPalletModal').classList.add('active')">
        <span class="material-symbols-outlined">add</span> Add Pallet
    </button>
</div>
{% endif %}

<!-- Add Pallet Modal -->
<div id="addPalletModal" class="modal-overlay" onclick="if(event.target===this)this.classList.remove('active')">
    <div class="modal">
        <div class="modal-title">Add New Pallet</div>
        <form method="POST" action="/pallets/add" enctype="multipart/form-data">
            <div class="form-group">
                <label class="form-label">Pallet Name *</label>
                <input type="text" name="name" class="form-control" placeholder="e.g. Amazon Returns Batch #12" required>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Supplier</label>
                    <input type="text" name="supplier" class="form-control" placeholder="e.g. Wholesale Co">
                </div>
                <div class="form-group">
                    <label class="form-label">Purchase Price (GBP)</label>
                    <input type="number" step="0.01" name="purchase_price_gbp" class="form-control" placeholder="0.00">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Purchase Date</label>
                <input type="date" name="purchase_date" class="form-control">
            </div>
            <div class="form-group">
                <label class="form-label">Notes</label>
                <textarea name="notes" class="form-control" rows="2" placeholder="Optional notes..."></textarea>
            </div>
            <div style="border-top:1px solid rgba(255,255,255,0.08);padding-top:14px;margin-top:14px">
                <label class="form-label"><span class="material-symbols-outlined" style="font-size:0.9rem;vertical-align:middle">upload_file</span> Import Specification (CSV / XLSX)</label>
                <input type="file" name="spec_file" accept=".csv,.xlsx,.xls" class="form-control" style="padding:8px">
                <div style="font-size:0.7rem;color:var(--text-muted);margin-top:4px">Upload supplier file with products. ASINs will be auto-scraped from Amazon UK.</div>
            </div>
            <div class="d-flex gap-8" style="justify-content: flex-end; margin-top: 20px;">
                <button type="button" class="btn btn-outline" onclick="document.getElementById('addPalletModal').classList.remove('active')">Cancel</button>
                <button type="submit" class="btn btn-cyan">
                    <span class="material-symbols-outlined">add</span> Add Pallet
                </button>
            </div>
        </form>
    </div>
</div>
"""

@app.route('/pallets')
def pallets_list():
    pallets = query_db("""
        SELECT p.*,
            COUNT(pr.id) as product_count,
            SUM(CASE WHEN pr.status = 'sold' THEN 1 ELSE 0 END) as sold_count,
            COALESCE(SUM(CASE WHEN pr.status = 'sold' THEN pr.ebay_price_gbp ELSE 0 END), 0) as revenue
        FROM pallets p
        LEFT JOIN products pr ON pr.pallet_id = p.id
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """)
    return render_page(
        TEMPLATE_PALLETS_CONTENT,
        page_title='Pallets - eBay Hub UK',
        active_page='pallets',
        pallets=pallets
    )


# -------------------------------------------------------------------
# Pallet Detail Template
# -------------------------------------------------------------------
TEMPLATE_PALLET_DETAIL_CONTENT = """
<div class="page-header">
    <h1>
        <a href="/pallets" class="text-muted" style="text-decoration: none;">Pallets</a>
        <span class="text-muted">/</span>
        <span>{{ pallet.name }}</span>
    </h1>
    <div class="d-flex gap-8">
        <a href="/pallet/{{ pallet.id }}/import" class="btn btn-purple btn-sm">
            <span class="material-symbols-outlined">upload_file</span> Import CSV
        </a>
        <form method="POST" action="/pallet/{{ pallet.id }}/scrape" class="inline-form">
            <button type="submit" class="btn btn-cyan btn-sm">
                <span class="material-symbols-outlined">photo_camera</span> Scrape Images
            </button>
        </form>
        <form method="POST" action="/pallet/{{ pallet.id }}/archive" class="inline-form">
            <button type="submit" class="btn btn-outline btn-sm">
                <span class="material-symbols-outlined">archive</span> Archive
            </button>
        </form>
        <form method="POST" action="/pallet/{{ pallet.id }}/delete" class="inline-form" onsubmit="return confirm('Delete this pallet and all its products? This cannot be undone.')">
            <button type="submit" class="btn btn-sm" style="background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#ef4444">
                <span class="material-symbols-outlined">delete</span> Delete
            </button>
        </form>
    </div>
</div>

<!-- Pallet Stats -->
<div class="stats-grid">
    <div class="card">
        <div class="card-title">Pallet Cost</div>
        <div class="card-value">{{ fmt_gbp(pallet.purchase_price_gbp) }}</div>
        <div class="card-subtitle">{{ pallet.supplier or 'No supplier' }} &middot; {{ fmt_date(pallet.purchase_date) }}</div>
    </div>
    <div class="card">
        <div class="card-title">Products</div>
        <div class="card-value purple">{{ stats.total }}</div>
        <div class="card-subtitle">{{ stats.warehouse }} warehouse / {{ stats.listed }} listed / {{ stats.sold }} sold</div>
    </div>
    <div class="card">
        <div class="card-title">Revenue</div>
        <div class="card-value lime">{{ fmt_gbp(stats.revenue) }}</div>
    </div>
    <div class="card">
        <div class="card-title">Profit</div>
        <div class="card-value {{ 'lime' if profit >= 0 else 'text-danger' }}">{{ fmt_gbp(profit) }}</div>
        {% if pallet.purchase_price_gbp > 0 %}
        <div class="card-subtitle">ROI: {{ "%.0f"|format((profit / pallet.purchase_price_gbp) * 100) }}%</div>
        {% endif %}
    </div>
</div>

{% if pallet.notes %}
<div class="card mb-16">
    <div class="card-title">Notes</div>
    <p>{{ pallet.notes }}</p>
</div>
{% endif %}

<!-- Add Product -->
<div class="flex-between mb-16">
    <h3 class="section-title" style="margin: 0; border: none; padding: 0;">Products</h3>
    <button class="btn btn-cyan btn-sm" onclick="document.getElementById('addProductModal').classList.add('active')">
        <span class="material-symbols-outlined">add</span> Add Product
    </button>
</div>

{% if products %}
<div class="product-grid">
    {% for p in products %}
    <a href="/product/{{ p.id }}" class="product-card">
        {% if p.image_url %}
        <img src="{{ p.image_url }}" alt="{{ p.name }}" class="product-card-img"
             onerror="this.style.display='none'">
        {% else %}
        <div class="product-card-img" style="display:flex;align-items:center;justify-content:center;">
            <span class="material-symbols-outlined" style="font-size:48px;opacity:0.2;">image</span>
        </div>
        {% endif %}
        <div class="product-card-body">
            <div class="product-card-name">{{ p.name }}</div>
            <div style="font-size:0.75rem;color:var(--text-muted);">
                {% if p.asin %}ASIN: {{ p.asin }}{% endif %}
                {% if p.ean %} &middot; EAN: {{ p.ean }}{% endif %}
            </div>
            <div class="product-card-meta">
                <div class="product-card-price">{{ fmt_gbp(p.ebay_price_gbp) }}</div>
                <span class="badge {{ status_color(p.status) }}">{{ p.status }}</span>
            </div>
            <div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;">
                Qty: {{ p.quantity }} &middot; {{ condition_label(p.condition) }}
            </div>
        </div>
    </a>
    {% endfor %}
</div>
{% else %}
<div class="empty-state">
    <span class="material-symbols-outlined">category</span>
    <p>No products in this pallet yet.</p>
    <div class="d-flex gap-8" style="justify-content: center;">
        <button class="btn btn-cyan" onclick="document.getElementById('addProductModal').classList.add('active')">
            <span class="material-symbols-outlined">add</span> Add Product
        </button>
        <a href="/pallet/{{ pallet.id }}/import" class="btn btn-purple">
            <span class="material-symbols-outlined">upload_file</span> Import CSV
        </a>
    </div>
</div>
{% endif %}

<!-- Add Product Modal -->
<div id="addProductModal" class="modal-overlay" onclick="if(event.target===this)this.classList.remove('active')">
    <div class="modal">
        <div class="modal-title">Add Product</div>
        <form method="POST" action="/pallet/{{ pallet.id }}/add_product">
            <div class="form-group">
                <label class="form-label">Product Name *</label>
                <input type="text" name="name" class="form-control" placeholder="e.g. Sony WH-1000XM5" required>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">ASIN</label>
                    <input type="text" name="asin" class="form-control" placeholder="B0BS1N8GK7">
                    <div class="form-hint">Amazon product ID (for image)</div>
                </div>
                <div class="form-group">
                    <label class="form-label">EAN / Barcode</label>
                    <input type="text" name="ean" class="form-control" placeholder="5027242923485">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Quantity</label>
                    <input type="number" name="quantity" class="form-control" value="1" min="1">
                </div>
                <div class="form-group">
                    <label class="form-label">Condition</label>
                    <select name="condition" class="form-control">
                        <option value="new">New</option>
                        <option value="like_new">Like New</option>
                        <option value="used">Used</option>
                        <option value="damaged">Damaged</option>
                    </select>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">eBay Price (GBP)</label>
                    <input type="number" step="0.01" name="ebay_price_gbp" class="form-control" placeholder="0.00">
                </div>
                <div class="form-group">
                    <label class="form-label">Category</label>
                    <input type="text" name="category" class="form-control" placeholder="e.g. Electronics">
                </div>
            </div>
            <div class="d-flex gap-8" style="justify-content: flex-end; margin-top: 20px;">
                <button type="button" class="btn btn-outline" onclick="document.getElementById('addProductModal').classList.remove('active')">Cancel</button>
                <button type="submit" class="btn btn-cyan">
                    <span class="material-symbols-outlined">add</span> Add Product
                </button>
            </div>
        </form>
    </div>
</div>
"""

@app.route('/pallet/<int:pallet_id>')
def pallet_detail(pallet_id):
    pallet = query_db("SELECT * FROM pallets WHERE id = ?", (pallet_id,), one=True)
    if not pallet:
        flash('Pallet not found.', 'error')
        return redirect(url_for('pallets_list'))

    products = query_db(
        "SELECT * FROM products WHERE pallet_id = ? ORDER BY created_at DESC",
        (pallet_id,)
    )

    stats = query_db("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'listed' THEN 1 ELSE 0 END) as listed,
            SUM(CASE WHEN status = 'sold' THEN 1 ELSE 0 END) as sold,
            SUM(CASE WHEN status = 'warehouse' THEN 1 ELSE 0 END) as warehouse,
            COALESCE(SUM(CASE WHEN status = 'sold' THEN ebay_price_gbp ELSE 0 END), 0) as revenue,
            COALESCE(SUM(ebay_price_gbp * quantity), 0) as potential_revenue
        FROM products WHERE pallet_id = ?
    """, (pallet_id,), one=True)

    profit = (stats['revenue'] or 0) - (pallet['purchase_price_gbp'] or 0)

    return render_page(
        TEMPLATE_PALLET_DETAIL_CONTENT,
        page_title=f'{pallet["name"]} - eBay Hub UK',
        active_page='pallets',
        pallet=pallet, products=products, stats=stats, profit=profit
    )


# -------------------------------------------------------------------
# CSV Import Template
# -------------------------------------------------------------------
TEMPLATE_CSV_IMPORT_CONTENT = """
<div class="page-header">
    <h1>
        <a href="/pallets" class="text-muted" style="text-decoration: none;">Pallets</a>
        <span class="text-muted">/</span>
        <a href="/pallet/{{ pallet.id }}" class="text-muted" style="text-decoration: none;">{{ pallet.name }}</a>
        <span class="text-muted">/</span>
        <span>Import</span>
    </h1>
</div>

<div class="card">
    <div class="card-title">Upload Specification (CSV or Excel)</div>
    <p style="margin: 12px 0; color: var(--text-muted); font-size: 0.9rem;">
        Upload the CSV or XLSX file from your joblot supplier. The app will auto-detect columns and scrape product data from Amazon UK.
    </p>

    <div class="table-wrap mb-16">
        <table>
            <thead>
                <tr>
                    <th>Column</th>
                    <th>Required</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
                <tr><td>name / title / product</td><td><span class="text-lime">Yes</span></td><td>Product name</td></tr>
                <tr><td>asin</td><td><span class="text-muted">No</span></td><td>Amazon ASIN (for auto-scrape)</td></tr>
                <tr><td>ean / barcode</td><td><span class="text-muted">No</span></td><td>EAN / Barcode</td></tr>
                <tr><td>quantity / qty</td><td><span class="text-muted">No</span></td><td>Quantity (default: 1)</td></tr>
                <tr><td>condition / state</td><td><span class="text-muted">No</span></td><td>new / like_new / used / damaged</td></tr>
                <tr><td>price / ebay_price / rrp</td><td><span class="text-muted">No</span></td><td>Price in GBP</td></tr>
            </tbody>
        </table>
    </div>

    <form method="POST" enctype="multipart/form-data" action="/pallet/{{ pallet.id }}/import">
        <div class="form-group">
            <label class="form-label">Select file (CSV or XLSX)</label>
            <input type="file" name="csv_file" accept=".csv,.xlsx,.xls" class="form-control" required>
        </div>
        <div class="form-group" style="margin-top: 12px;">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 0.85rem; color: var(--text-muted);">
                <input type="checkbox" name="auto_scrape" value="1" checked style="accent-color: #8ff5ff;">
                Auto-scrape Amazon UK for products with ASIN (images, titles, prices)
            </label>
        </div>
        <div class="d-flex gap-8" style="margin-top: 20px;">
            <a href="/pallet/{{ pallet.id }}" class="btn btn-outline">Cancel</a>
            <button type="submit" class="btn btn-purple">
                <span class="material-symbols-outlined">upload_file</span> Import Products
            </button>
        </div>
    </form>
</div>
"""

@app.route('/pallet/<int:pallet_id>/import', methods=['GET', 'POST'])
def csv_import(pallet_id):
    pallet = query_db("SELECT * FROM pallets WHERE id = ?", (pallet_id,), one=True)
    if not pallet:
        flash('Pallet not found.', 'error')
        return redirect(url_for('pallets_list'))

    if request.method == 'POST':
        file = request.files.get('csv_file')
        if not file or not file.filename:
            flash('Please upload a file.', 'error')
            return redirect(url_for('csv_import', pallet_id=pallet_id))

        fname = file.filename.lower()
        auto_scrape = request.form.get('auto_scrape') == '1'

        try:
            rows = []

            # Parse XLSX
            if fname.endswith(('.xlsx', '.xls')):
                try:
                    import openpyxl
                except ImportError:
                    flash('openpyxl not installed. Run: pip install openpyxl', 'error')
                    return redirect(url_for('csv_import', pallet_id=pallet_id))
                wb = openpyxl.load_workbook(file, data_only=True)
                ws = wb.active
                # Find header row (first row with text)
                headers = []
                for cell in ws[1]:
                    headers.append(str(cell.value or '').strip().lower())
                for row_cells in ws.iter_rows(min_row=2, values_only=True):
                    row = {}
                    for i, val in enumerate(row_cells):
                        if i < len(headers):
                            row[headers[i]] = str(val or '').strip()
                    rows.append(row)

            # Parse CSV
            elif fname.endswith('.csv'):
                raw = file.stream.read()
                # Try UTF-8 first, fallback to latin-1
                for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
                    try:
                        text = raw.decode(enc)
                        break
                    except:
                        continue
                else:
                    text = raw.decode('utf-8', errors='replace')
                # Detect delimiter
                first_line = text.split('\n')[0]
                delimiter = ';' if first_line.count(';') > first_line.count(',') else ','
                reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
                rows = list(reader)
            else:
                flash('Unsupported file format. Use CSV or XLSX.', 'error')
                return redirect(url_for('csv_import', pallet_id=pallet_id))

            # Column name mapping (flexible)
            def get_col(row, *names):
                # Exact match first, then substring
                for n in names:
                    for key in row:
                        if key and key.lower().strip() == n:
                            val = row[key].strip() if row[key] else ''
                            if val and val.lower() not in ('none', 'nan', 'null'):
                                return val
                for n in names:
                    for key in row:
                        if key and n in key.lower() and 'category' not in key.lower():
                            val = row[key].strip() if row[key] else ''
                            if val and val.lower() not in ('none', 'nan', 'null'):
                                return val
                return ''

            count = 0
            scraped = 0
            from modules.scraper import scrape_amazon_product, get_amazon_image_url

            for row in rows:
                name = get_col(row, 'name', 'title', 'product', 'nazwa', 'description')
                if not name:
                    continue

                asin = get_col(row, 'asin').upper()
                ean = get_col(row, 'ean', 'barcode', 'upc', 'gtin')
                try:
                    qty = int(float(get_col(row, 'quantity', 'qty', 'ilosc', 'amount') or '1'))
                except:
                    qty = 1
                cond = get_col(row, 'condition', 'state', 'stan').lower()
                if cond not in ('new', 'like_new', 'used', 'damaged'):
                    cond = 'new'
                try:
                    price = float(get_col(row, 'price', 'ebay_price', 'rrp', 'cena') or '0')
                except:
                    price = 0.0

                image_url = get_amazon_image_url(asin) if asin else ''

                # Auto-scrape Amazon UK for products with ASIN
                if auto_scrape and asin:
                    try:
                        data = scrape_amazon_product(asin)
                        if data:
                            if data.get('title') and len(data['title']) > len(name):
                                name = data['title']
                            if data.get('image_url'):
                                image_url = data['image_url']
                            if data.get('price') and price == 0:
                                price = data['price']
                            scraped += 1
                    except Exception as e:
                        print(f"[WARN] Scrape failed for {asin}: {e}")

                execute_db(
                    "INSERT INTO products (pallet_id, name, asin, ean, quantity, "
                    "condition, ebay_price_gbp, image_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (pallet_id, name, asin, ean, qty, cond, price, image_url)
                )
                count += 1

            msg = f'Imported {count} products'
            if scraped > 0:
                msg += f' (scraped {scraped} from Amazon UK)'
            flash(msg + '.', 'success')
            return redirect(url_for('pallet_detail', pallet_id=pallet_id))

        except Exception as e:
            flash(f'Error importing file: {e}', 'error')
            return redirect(url_for('csv_import', pallet_id=pallet_id))

    return render_page(
        TEMPLATE_CSV_IMPORT_CONTENT,
        page_title=f'Import CSV - {pallet["name"]} - eBay Hub UK',
        active_page='pallets',
        pallet=pallet
    )


# -------------------------------------------------------------------
# Product Detail Template
# -------------------------------------------------------------------
TEMPLATE_PRODUCT_DETAIL_CONTENT = """
<div class="page-header">
    <h1>
        <a href="/pallets" class="text-muted" style="text-decoration: none;">Pallets</a>
        <span class="text-muted">/</span>
        {% if pallet %}
        <a href="/pallet/{{ pallet.id }}" class="text-muted" style="text-decoration: none;">{{ pallet.name }}</a>
        <span class="text-muted">/</span>
        {% endif %}
        <span>{{ product.name[:40] }}{% if product.name|length > 40 %}...{% endif %}</span>
    </h1>
</div>

<div class="detail-header">
    {% if product.image_url %}
    <img src="{{ product.image_url }}" alt="{{ product.name }}" class="detail-image"
         onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 200%22><rect fill=%22%2312121a%22 width=%22200%22 height=%22200%22/><text x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 fill=%22%236a6a80%22 font-size=%2214%22>No Image</text></svg>'">
    {% endif %}
    <div class="detail-info">
        <h2>{{ product.name }}</h2>
        <dl class="detail-meta">
            <dt>ASIN</dt><dd>{{ product.asin or '-' }}</dd>
            <dt>EAN</dt><dd>{{ product.ean or '-' }}</dd>
            <dt>Condition</dt><dd>{{ condition_label(product.condition) }}</dd>
            <dt>Quantity</dt><dd>{{ product.quantity }}</dd>
            <dt>eBay Price</dt><dd class="text-lime">{{ fmt_gbp(product.ebay_price_gbp) }}</dd>
            <dt>Status</dt><dd><span class="badge {{ status_color(product.status) }}">{{ product.status }}</span></dd>
            <dt>Category</dt><dd>{{ product.category or '-' }}</dd>
            <dt>Added</dt><dd>{{ fmt_datetime(product.created_at) }}</dd>
        </dl>
    </div>
</div>

<!-- Edit Product -->
<div class="section-title">Edit Product</div>
<div class="card">
    <form method="POST" action="/product/{{ product.id }}/update">
        <div class="form-row">
            <div class="form-group">
                <label class="form-label">Name</label>
                <input type="text" name="name" class="form-control" value="{{ product.name }}" required>
            </div>
            <div class="form-group">
                <label class="form-label">Status</label>
                <select name="status" class="form-control">
                    <option value="warehouse" {{ 'selected' if product.status == 'warehouse' }}>Warehouse</option>
                    <option value="listed" {{ 'selected' if product.status == 'listed' }}>Listed</option>
                    <option value="sold" {{ 'selected' if product.status == 'sold' }}>Sold</option>
                    <option value="shipped" {{ 'selected' if product.status == 'shipped' }}>Shipped</option>
                </select>
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label class="form-label">ASIN</label>
                <input type="text" name="asin" class="form-control" value="{{ product.asin }}">
            </div>
            <div class="form-group">
                <label class="form-label">EAN</label>
                <input type="text" name="ean" class="form-control" value="{{ product.ean }}">
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label class="form-label">Quantity</label>
                <input type="number" name="quantity" class="form-control" value="{{ product.quantity }}" min="1">
            </div>
            <div class="form-group">
                <label class="form-label">Condition</label>
                <select name="condition" class="form-control">
                    <option value="new" {{ 'selected' if product.condition == 'new' }}>New</option>
                    <option value="like_new" {{ 'selected' if product.condition == 'like_new' }}>Like New</option>
                    <option value="used" {{ 'selected' if product.condition == 'used' }}>Used</option>
                    <option value="damaged" {{ 'selected' if product.condition == 'damaged' }}>Damaged</option>
                </select>
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label class="form-label">eBay Price (GBP)</label>
                <input type="number" step="0.01" name="ebay_price_gbp" class="form-control" value="{{ product.ebay_price_gbp }}">
            </div>
            <div class="form-group">
                <label class="form-label">Category</label>
                <input type="text" name="category" class="form-control" value="{{ product.category }}">
            </div>
        </div>
        <div class="d-flex gap-8" style="margin-top: 16px;">
            <button type="submit" class="btn btn-cyan">
                <span class="material-symbols-outlined">save</span> Save Changes
            </button>
        </div>
    </form>
</div>

<!-- List on eBay -->
<div class="section-title">eBay Listing</div>
<div class="card">
    <form method="POST" action="/product/{{ product.id }}/list_ebay">
        <div class="form-group">
            <label class="form-label">Listing Title</label>
            <input type="text" name="title" class="form-control" value="{{ product.name }}" maxlength="80">
            <div class="form-hint">Max 80 characters. Make it descriptive for eBay search.</div>
        </div>
        <div class="form-group">
            <label class="form-label">Description</label>
            <textarea name="description" class="form-control" rows="4" placeholder="Product description for eBay listing..."></textarea>
        </div>
        <div class="form-group">
            <label class="form-label">Price (GBP)</label>
            <input type="number" step="0.01" name="price" class="form-control" value="{{ product.ebay_price_gbp }}">
        </div>
        <div class="d-flex gap-8" style="margin-top: 16px;">
            <button type="submit" class="btn btn-lime">
                <span class="material-symbols-outlined">sell</span> List on eBay
            </button>
            <button type="button" class="btn btn-outline btn-sm" disabled title="Coming soon">
                <span class="material-symbols-outlined">auto_awesome</span> Generate Title
            </button>
            <button type="button" class="btn btn-outline btn-sm" disabled title="Coming soon">
                <span class="material-symbols-outlined">auto_awesome</span> Generate Description
            </button>
        </div>
    </form>
</div>

<!-- Listings History -->
{% if listings %}
<div class="section-title">Listing History</div>
<div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>Title</th>
                <th>Price</th>
                <th>Status</th>
                <th>eBay ID</th>
                <th>Views</th>
                <th>Watchers</th>
                <th>Created</th>
            </tr>
        </thead>
        <tbody>
            {% for l in listings %}
            <tr>
                <td>{{ l.title[:50] }}</td>
                <td>{{ fmt_gbp(l.price_gbp) }}</td>
                <td><span class="badge {{ status_color(l.status) }}">{{ l.status }}</span></td>
                <td class="text-muted">{{ l.ebay_item_id or '-' }}</td>
                <td>{{ l.views }}</td>
                <td>{{ l.watchers }}</td>
                <td class="text-muted">{{ fmt_datetime(l.created_at) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

<!-- Sales History -->
{% if sales %}
<div class="section-title">Sales History</div>
<div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>Buyer</th>
                <th>Price</th>
                <th>Status</th>
                <th>Sold</th>
                <th>Shipped</th>
            </tr>
        </thead>
        <tbody>
            {% for s in sales %}
            <tr>
                <td>{{ s.buyer or 'Unknown' }}</td>
                <td class="text-lime">{{ fmt_gbp(s.price_gbp) }}</td>
                <td><span class="badge {{ status_color(s.status) }}">{{ s.status }}</span></td>
                <td class="text-muted">{{ fmt_datetime(s.sold_at) }}</td>
                <td class="text-muted">{{ fmt_datetime(s.shipped_at) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

<!-- Delete Product -->
<div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);">
    <form method="POST" action="/product/{{ product.id }}/delete"
          onsubmit="return confirm('Delete this product? This cannot be undone.')">
        <button type="submit" class="btn btn-danger btn-sm">
            <span class="material-symbols-outlined">delete</span> Delete Product
        </button>
    </form>
</div>
"""

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = query_db("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('pallets_list'))

    pallet = None
    if product['pallet_id']:
        pallet = query_db(
            "SELECT * FROM pallets WHERE id = ?",
            (product['pallet_id'],), one=True
        )

    listings = query_db(
        "SELECT * FROM ebay_listings WHERE product_id = ? ORDER BY created_at DESC",
        (product_id,)
    )

    sales = query_db(
        "SELECT * FROM sales WHERE product_id = ? ORDER BY sold_at DESC",
        (product_id,)
    )

    return render_page(
        TEMPLATE_PRODUCT_DETAIL_CONTENT,
        page_title=f'{product["name"]} - eBay Hub UK',
        active_page='pallets',
        product=product, pallet=pallet, listings=listings, sales=sales
    )


# -------------------------------------------------------------------
# Listings Template
# -------------------------------------------------------------------
TEMPLATE_LISTINGS_CONTENT = """
<div class="page-header">
    <h1><span>Listings</span></h1>
</div>

<div class="filter-tabs">
    <a href="/listings" class="filter-tab {{ 'active' if current_filter == 'all' }}">
        All <span class="filter-count">{{ counts.total }}</span>
    </a>
    <a href="/listings?status=active" class="filter-tab {{ 'active' if current_filter == 'active' }}">
        Active <span class="filter-count">{{ counts.active }}</span>
    </a>
    <a href="/listings?status=draft" class="filter-tab {{ 'active' if current_filter == 'draft' }}">
        Draft <span class="filter-count">{{ counts.draft }}</span>
    </a>
    <a href="/listings?status=sold" class="filter-tab {{ 'active' if current_filter == 'sold' }}">
        Sold <span class="filter-count">{{ counts.sold }}</span>
    </a>
    <a href="/listings?status=ended" class="filter-tab {{ 'active' if current_filter == 'ended' }}">
        Ended <span class="filter-count">{{ counts.ended }}</span>
    </a>
</div>

{% if listings %}
<div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th></th>
                <th>Title</th>
                <th>Price</th>
                <th>Status</th>
                <th>eBay ID</th>
                <th>Views</th>
                <th>Watchers</th>
                <th>Created</th>
            </tr>
        </thead>
        <tbody>
            {% for l in listings %}
            <tr>
                <td style="width:40px;">
                    {% if l.image_url %}
                    <img src="{{ l.image_url }}" style="width:36px;height:36px;object-fit:contain;border-radius:4px;"
                         onerror="this.style.display='none'">
                    {% endif %}
                </td>
                <td>
                    {% if l.product_id %}
                    <a href="/product/{{ l.product_id }}" class="table-link">{{ l.title[:60] }}</a>
                    {% else %}
                    {{ l.title[:60] }}
                    {% endif %}
                </td>
                <td>{{ fmt_gbp(l.price_gbp) }}</td>
                <td><span class="badge {{ status_color(l.status) }}">{{ l.status }}</span></td>
                <td class="text-muted">{{ l.ebay_item_id or '-' }}</td>
                <td>{{ l.views }}</td>
                <td>{{ l.watchers }}</td>
                <td class="text-muted">{{ fmt_datetime(l.created_at) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% else %}
<div class="empty-state">
    <span class="material-symbols-outlined">sell</span>
    <p>No listings yet. List products from your pallets to see them here.</p>
    <a href="/pallets" class="btn btn-cyan">
        <span class="material-symbols-outlined">inventory_2</span> Go to Pallets
    </a>
</div>
{% endif %}
"""

@app.route('/listings')
def listings_list():
    status_filter = request.args.get('status', 'all')

    if status_filter != 'all':
        listings = query_db("""
            SELECT l.*, p.name as product_name, p.image_url
            FROM ebay_listings l
            LEFT JOIN products p ON p.id = l.product_id
            WHERE l.status = ?
            ORDER BY l.created_at DESC
        """, (status_filter,))
    else:
        listings = query_db("""
            SELECT l.*, p.name as product_name, p.image_url
            FROM ebay_listings l
            LEFT JOIN products p ON p.id = l.product_id
            ORDER BY l.created_at DESC
        """)

    counts = query_db("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active,
            SUM(CASE WHEN status='draft' THEN 1 ELSE 0 END) as draft,
            SUM(CASE WHEN status='ended' THEN 1 ELSE 0 END) as ended,
            SUM(CASE WHEN status='sold' THEN 1 ELSE 0 END) as sold
        FROM ebay_listings
    """, one=True)

    return render_page(
        TEMPLATE_LISTINGS_CONTENT,
        page_title='Listings - eBay Hub UK',
        active_page='listings',
        listings=listings, counts=counts, current_filter=status_filter
    )


# -------------------------------------------------------------------
# Orders Template
# -------------------------------------------------------------------
TEMPLATE_ORDERS_CONTENT = """
<div class="page-header">
    <h1><span>Orders</span></h1>
</div>

<div class="filter-tabs">
    <a href="/orders" class="filter-tab {{ 'active' if current_filter == 'all' }}">
        All <span class="filter-count">{{ counts.total }}</span>
    </a>
    <a href="/orders?status=new" class="filter-tab {{ 'active' if current_filter == 'new' }}">
        To Ship <span class="filter-count" style="background:rgba(255,107,155,0.2);color:var(--pink);">{{ counts.new_orders }}</span>
    </a>
    <a href="/orders?status=shipped" class="filter-tab {{ 'active' if current_filter == 'shipped' }}">
        Shipped <span class="filter-count">{{ counts.shipped }}</span>
    </a>
    <a href="/orders?status=delivered" class="filter-tab {{ 'active' if current_filter == 'delivered' }}">
        Delivered <span class="filter-count">{{ counts.delivered }}</span>
    </a>
</div>

{% if orders %}
<div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th></th>
                <th>Product</th>
                <th>Buyer</th>
                <th>Price</th>
                <th>Status</th>
                <th>Sold</th>
                <th>Address</th>
                <th>Action</th>
            </tr>
        </thead>
        <tbody>
            {% for o in orders %}
            <tr style="{{ 'background:rgba(255,107,155,0.04);' if o.status == 'new' }}">
                <td style="width:40px;">
                    {% if o.image_url %}
                    <img src="{{ o.image_url }}" style="width:36px;height:36px;object-fit:contain;border-radius:4px;"
                         onerror="this.style.display='none'">
                    {% endif %}
                </td>
                <td>
                    {% if o.product_id %}
                    <a href="/product/{{ o.product_id }}" class="table-link">
                        {{ o.product_name or o.listing_title or 'Product #' ~ o.product_id }}
                    </a>
                    {% else %}
                    {{ o.listing_title or '-' }}
                    {% endif %}
                </td>
                <td>{{ o.buyer or '-' }}</td>
                <td class="text-lime">{{ fmt_gbp(o.price_gbp) }}</td>
                <td><span class="badge {{ status_color(o.status) }}">{{ o.status }}</span></td>
                <td class="text-muted">{{ fmt_datetime(o.sold_at) }}</td>
                <td class="text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">
                    {{ o.shipping_address[:60] if o.shipping_address else '-' }}
                </td>
                <td>
                    {% if o.status == 'new' %}
                    <form method="POST" action="/order/{{ o.id }}/ship" class="inline-form">
                        <button type="submit" class="btn btn-pink btn-sm">
                            <span class="material-symbols-outlined">local_shipping</span> Ship
                        </button>
                    </form>
                    {% elif o.status == 'shipped' %}
                    <span class="text-muted">In transit</span>
                    {% else %}
                    <span class="text-lime">Done</span>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% else %}
<div class="empty-state">
    <span class="material-symbols-outlined">local_shipping</span>
    <p>No orders yet. Sales will appear here when products are sold.</p>
</div>
{% endif %}
"""

@app.route('/orders')
def orders_list():
    status_filter = request.args.get('status', 'all')

    if status_filter != 'all':
        orders = query_db("""
            SELECT s.*, p.name as product_name, p.image_url,
                   l.title as listing_title
            FROM sales s
            LEFT JOIN products p ON p.id = s.product_id
            LEFT JOIN ebay_listings l ON l.id = s.listing_id
            WHERE s.status = ?
            ORDER BY s.sold_at DESC
        """, (status_filter,))
    else:
        orders = query_db("""
            SELECT s.*, p.name as product_name, p.image_url,
                   l.title as listing_title
            FROM sales s
            LEFT JOIN products p ON p.id = s.product_id
            LEFT JOIN ebay_listings l ON l.id = s.listing_id
            ORDER BY s.sold_at DESC
        """)

    counts = query_db("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='new' THEN 1 ELSE 0 END) as new_orders,
            SUM(CASE WHEN status='shipped' THEN 1 ELSE 0 END) as shipped,
            SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END) as delivered
        FROM sales
    """, one=True)

    return render_page(
        TEMPLATE_ORDERS_CONTENT,
        page_title='Orders - eBay Hub UK',
        active_page='orders',
        orders=orders, counts=counts, current_filter=status_filter
    )


# -------------------------------------------------------------------
# Settings Template
# -------------------------------------------------------------------
TEMPLATE_SETTINGS_CONTENT = """
<div class="page-header">
    <h1><span>Settings</span></h1>
</div>

<form method="POST" action="/settings">

    <!-- eBay API -->
    <div class="card mb-16">
        <div class="card-title" style="display:flex;align-items:center;gap:8px;">
            <span class="material-symbols-outlined text-cyan" style="font-size:20px;">api</span>
            eBay API Credentials
        </div>
        <p class="text-muted" style="font-size:0.85rem;margin:8px 0 16px 0;">
            Get your API keys from
            <span class="text-cyan">developer.ebay.com</span>.
            These are required to publish listings and sync orders.
        </p>
        <div class="form-row">
            <div class="form-group">
                <label class="form-label">App ID (Client ID)</label>
                <input type="text" name="ebay_app_id" class="form-control"
                       value="{{ config.ebay_app_id }}" placeholder="Your eBay App ID">
            </div>
            <div class="form-group">
                <label class="form-label">Cert ID (Client Secret)</label>
                <input type="password" name="ebay_cert_id" class="form-control"
                       value="{{ config.ebay_cert_id }}" placeholder="Your eBay Cert ID">
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label class="form-label">Dev ID</label>
                <input type="text" name="ebay_dev_id" class="form-control"
                       value="{{ config.ebay_dev_id }}" placeholder="Your eBay Dev ID">
            </div>
            <div class="form-group">
                <label class="form-label">User Token</label>
                <input type="password" name="ebay_user_token" class="form-control"
                       value="{{ config.ebay_user_token }}" placeholder="OAuth user token">
            </div>
        </div>
    </div>

    <!-- Telegram -->
    <div class="card mb-16">
        <div class="card-title" style="display:flex;align-items:center;gap:8px;">
            <span class="material-symbols-outlined text-purple" style="font-size:20px;">send</span>
            Telegram Notifications
        </div>
        <p class="text-muted" style="font-size:0.85rem;margin:8px 0 16px 0;">
            Get notified about new sales and orders via Telegram bot.
        </p>
        <div class="form-row">
            <div class="form-group">
                <label class="form-label">Bot Token</label>
                <input type="text" name="telegram_bot_token" class="form-control"
                       value="{{ config.telegram_bot_token }}" placeholder="123456:ABC-DEF...">
                <div class="form-hint">Get from @BotFather on Telegram</div>
            </div>
            <div class="form-group">
                <label class="form-label">Chat ID</label>
                <input type="text" name="telegram_chat_id" class="form-control"
                       value="{{ config.telegram_chat_id }}" placeholder="-1001234567890">
            </div>
        </div>
    </div>

    <!-- Security -->
    <div class="card mb-16">
        <div class="card-title" style="display:flex;align-items:center;gap:8px;">
            <span class="material-symbols-outlined" style="font-size:20px;color:#ef4444">lock</span>
            Security
        </div>
        <div class="form-row">
            <div class="form-group">
                <label class="form-label">App PIN (required to access)</label>
                <input type="password" name="app_pin" class="form-control"
                       value="{{ config.app_pin }}" placeholder="Set a PIN (e.g. 1234)">
                <div class="form-hint">Leave empty to disable PIN protection</div>
            </div>
        </div>
    </div>

    <!-- Defaults -->
    <div class="card mb-16">
        <div class="card-title" style="display:flex;align-items:center;gap:8px;">
            <span class="material-symbols-outlined text-lime" style="font-size:20px;">tune</span>
            Default Settings
        </div>
        <div class="form-row">
            <div class="form-group">
                <label class="form-label">Default Shipping Method</label>
                <select name="default_shipping" class="form-control">
                    <option value="royal_mail_2nd" {{ 'selected' if config.default_shipping == 'royal_mail_2nd' }}>Royal Mail 2nd Class</option>
                    <option value="royal_mail_1st" {{ 'selected' if config.default_shipping == 'royal_mail_1st' }}>Royal Mail 1st Class</option>
                    <option value="royal_mail_tracked" {{ 'selected' if config.default_shipping == 'royal_mail_tracked' }}>Royal Mail Tracked</option>
                    <option value="hermes" {{ 'selected' if config.default_shipping == 'hermes' }}>Evri (Hermes)</option>
                    <option value="dpd" {{ 'selected' if config.default_shipping == 'dpd' }}>DPD</option>
                    <option value="yodel" {{ 'selected' if config.default_shipping == 'yodel' }}>Yodel</option>
                    <option value="collect" {{ 'selected' if config.default_shipping == 'collect' }}>Collection Only</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">Default Return Policy (days)</label>
                <input type="number" name="default_return_days" class="form-control"
                       value="{{ config.default_return_days or '30' }}" min="0">
                <div class="form-hint">eBay UK requires minimum 14 days for consumer sales</div>
            </div>
        </div>
    </div>

    <button type="submit" class="btn btn-cyan">
        <span class="material-symbols-outlined">save</span> Save Settings
    </button>
</form>

<!-- Backups -->
<div class="card mb-16" style="margin-top:24px">
    <div class="card-title" style="display:flex;align-items:center;justify-content:space-between;">
        <div style="display:flex;align-items:center;gap:8px;">
            <span class="material-symbols-outlined text-lime" style="font-size:20px;">backup</span>
            Database Backups
        </div>
        <form method="POST" action="/settings/backup/create" class="inline-form">
            <button type="submit" class="btn btn-lime btn-sm">
                <span class="material-symbols-outlined">add_circle</span> Create Backup Now
            </button>
        </form>
    </div>
    <p class="text-muted" style="font-size:0.8rem;margin:8px 0 16px 0;">
        Auto-backup runs every hour. Max 48 backups kept (2 days).
    </p>

    {% if backups %}
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Size</th>
                    <th>File</th>
                    <th style="text-align:right">Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for b in backups[:15] %}
                <tr>
                    <td>{{ b.date }}</td>
                    <td>{{ b.size_mb }} MB</td>
                    <td style="font-size:0.75rem;color:var(--text-muted);font-family:monospace">{{ b.name }}</td>
                    <td style="text-align:right">
                        <div class="d-flex gap-8" style="justify-content:flex-end">
                            <a href="/settings/backup/download/{{ b.name }}" class="btn btn-outline btn-sm" style="padding:4px 10px;font-size:0.7rem">
                                <span class="material-symbols-outlined" style="font-size:0.85rem">download</span> Download
                            </a>
                            <form method="POST" action="/settings/backup/restore/{{ b.name }}" class="inline-form" onsubmit="return confirm('Restore database from {{ b.name }}?\\n\\nCurrent data will be backed up first.')">
                                <button type="submit" class="btn btn-sm" style="padding:4px 10px;font-size:0.7rem;background:rgba(245,158,11,0.15);border:1px solid rgba(245,158,11,0.3);color:#f59e0b">
                                    <span class="material-symbols-outlined" style="font-size:0.85rem">restore</span> Restore
                                </button>
                            </form>
                        </div>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% if backups|length > 15 %}
    <div style="text-align:center;padding:8px;color:var(--text-muted);font-size:0.75rem">Showing 15 of {{ backups|length }} backups</div>
    {% endif %}
    {% else %}
    <div style="text-align:center;padding:20px;color:var(--text-muted)">No backups yet. Click "Create Backup Now" to make one.</div>
    {% endif %}
</div>

<!-- Upload Backup -->
<div class="card mb-16">
    <div class="card-title" style="display:flex;align-items:center;gap:8px;">
        <span class="material-symbols-outlined text-purple" style="font-size:20px;">upload_file</span>
        Upload Backup
    </div>
    <form method="POST" action="/settings/backup/upload" enctype="multipart/form-data">
        <div class="form-group">
            <label class="form-label">Upload a .db backup file to restore</label>
            <input type="file" name="backup_file" accept=".db" class="form-control" required style="padding:8px">
        </div>
        <button type="submit" class="btn btn-purple btn-sm" onclick="return confirm('Upload and restore this backup?\\n\\nCurrent data will be backed up first.')">
            <span class="material-symbols-outlined">upload</span> Upload & Restore
        </button>
    </form>
</div>
"""

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        keys = [
            'app_pin',
            'ebay_app_id', 'ebay_cert_id', 'ebay_dev_id', 'ebay_user_token',
            'telegram_bot_token', 'telegram_chat_id',
            'default_shipping', 'default_return_days'
        ]
        for key in keys:
            val = request.form.get(key, '')
            set_config(key, val)
        flash('Settings saved.', 'success')
        return redirect(url_for('settings'))

    config = {}
    keys = [
        'ebay_app_id', 'ebay_cert_id', 'ebay_dev_id', 'ebay_user_token',
        'telegram_bot_token', 'telegram_chat_id',
        'default_shipping', 'default_return_days'
    ]
    for key in keys:
        config[key] = get_config(key, '')

    from modules.backup import get_backups
    backups = get_backups()

    return render_page(
        TEMPLATE_SETTINGS_CONTENT,
        page_title='Settings - eBay Hub UK',
        active_page='settings',
        config=config,
        backups=backups
    )


@app.route('/settings/backup/create', methods=['POST'])
def backup_create():
    from modules.backup import create_backup
    result = create_backup()
    if result:
        flash(f'Backup created: {result.name}', 'success')
    else:
        flash('Backup failed!', 'error')
    return redirect(url_for('settings'))


@app.route('/settings/backup/restore/<backup_name>', methods=['POST'])
def backup_restore(backup_name):
    from modules.backup import restore_backup
    from modules.database import close_db
    ok, msg = restore_backup(backup_name)
    if ok:
        # Force close current DB connection so next request uses restored DB
        close_db()
        flash(f'Database restored from {backup_name}.', 'success')
    else:
        flash(f'Restore failed: {msg}', 'error')
    return redirect(url_for('settings'))


@app.route('/settings/backup/download/<backup_name>')
def backup_download(backup_name):
    from pathlib import Path
    backup_dir = Path(__file__).parent / 'backups'
    backup_path = backup_dir / backup_name
    if not backup_path.exists() or '..' in backup_name:
        flash('Backup not found.', 'error')
        return redirect(url_for('settings'))
    from flask import send_file
    return send_file(str(backup_path), as_attachment=True, download_name=backup_name)


@app.route('/settings/backup/upload', methods=['POST'])
def backup_upload():
    from modules.backup import create_backup
    from pathlib import Path
    import shutil

    file = request.files.get('backup_file')
    if not file or not file.filename.endswith('.db'):
        flash('Please upload a .db file.', 'error')
        return redirect(url_for('settings'))

    # Safety backup first
    create_backup()

    # Close current connection, replace DB, next request reconnects
    from modules.database import close_db
    close_db()
    db_path = Path(__file__).parent / 'ebay_hub.db'
    file.save(str(db_path))
    flash(f'Database restored from uploaded file: {file.filename}', 'success')
    return redirect(url_for('settings'))


# ===================================================================
# Run
# ===================================================================

if __name__ == '__main__':
    # Start backup scheduler
    try:
        from modules.backup import start_backup_scheduler, create_backup
        start_backup_scheduler()
        create_backup()  # Initial backup on start
    except Exception as e:
        print(f"[WARN] Backup init error: {e}")

    print("=" * 50)
    print("  eBay Hub UK v1.0.0")
    print("  http://127.0.0.1:5002")
    print("=" * 50)
    app.run(debug=False, host='0.0.0.0', port=5002)
