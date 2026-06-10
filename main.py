import os
import secrets
import sqlite3
import httpx
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# --- Config ---
DATABASE_PATH = os.getenv("DATABASE_PATH", "products.db")
API_KEY = os.getenv("API_KEY", "")

# Shopify config
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "")        # e.g. "my-store.myshopify.com"
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")         # Admin API access token

# Generate a key on first run if none is set
if not API_KEY:
    API_KEY = secrets.token_urlsafe(32)
    print(f"\n{'='*60}")
    print(f"  Generated API Key (set API_KEY env var to override):")
    print(f"  {API_KEY}")
    print(f"{'='*60}\n")

app = FastAPI(title="Product Catalog API", version="1.0.0")

# --- Database ---
def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            supplier TEXT DEFAULT '',
            price REAL DEFAULT 0.0,
            status TEXT DEFAULT 'draft',
            description TEXT DEFAULT '',
            photo_url TEXT DEFAULT '',
            in_shopify INTEGER DEFAULT 0,
            shopify_product_id TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    # Add shopify_product_id column if upgrading from v1
    try:
        conn.execute("ALTER TABLE products ADD COLUMN shopify_product_id TEXT DEFAULT ''")
    except:
        pass
    conn.commit()
    conn.close()

init_db()

# --- Auth ---
def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# --- Models ---
class ProductCreate(BaseModel):
    sku: str
    name: str
    supplier: str = ""
    price: float = 0.0
    status: str = "draft"
    description: str = ""
    photo_url: str = ""
    in_shopify: bool = False

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    supplier: Optional[str] = None
    price: Optional[float] = None
    status: Optional[str] = None
    description: Optional[str] = None
    photo_url: Optional[str] = None
    in_shopify: Optional[bool] = None

def row_to_dict(row):
    d = dict(row)
    d["in_shopify"] = bool(d["in_shopify"])
    return d

# --- API Endpoints ---
@app.get("/products")
def list_products(
    x_api_key: str = Header(None),
    status: Optional[str] = None,
    supplier: Optional[str] = None,
    search: Optional[str] = None,
):
    verify_api_key(x_api_key)
    conn = get_db()
    query = "SELECT * FROM products WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if supplier:
        query += " AND supplier LIKE ?"
        params.append(f"%{supplier}%")
    if search:
        query += " AND (name LIKE ? OR sku LIKE ? OR description LIKE ?)"
        params.extend([f"%{search}%"] * 3)
    query += " ORDER BY updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

@app.post("/products", status_code=201)
def create_or_update_product(product: ProductCreate, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO products (sku, name, supplier, price, status, description, photo_url, in_shopify, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
            name=excluded.name, supplier=excluded.supplier, price=excluded.price,
            status=excluded.status, description=excluded.description,
            photo_url=excluded.photo_url, in_shopify=excluded.in_shopify,
            updated_at=excluded.updated_at
    """, (product.sku, product.name, product.supplier, product.price,
          product.status, product.description, product.photo_url,
          int(product.in_shopify), now, now))
    conn.commit()
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (product.sku,)).fetchone()
    conn.close()
    return row_to_dict(row)

@app.get("/products/{sku}")
def get_product(sku: str, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)
    conn = get_db()
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")
    return row_to_dict(row)

@app.patch("/products/{sku}")
def update_product(sku: str, updates: ProductUpdate, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)
    conn = get_db()
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")

    fields = []
    params = []
    for field, value in updates.model_dump(exclude_unset=True).items():
        if field == "in_shopify":
            value = int(value)
        fields.append(f"{field} = ?")
        params.append(value)

    if fields:
        fields.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(sku)
        conn.execute(f"UPDATE products SET {', '.join(fields)} WHERE sku = ?", params)
        conn.commit()

    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    conn.close()
    return row_to_dict(row)

@app.delete("/products/{sku}")
def delete_product(sku: str, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)
    conn = get_db()
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")
    conn.execute("DELETE FROM products WHERE sku = ?", (sku,))
    conn.commit()
    conn.close()
    return {"deleted": sku}

# --- Shopify Integration ---
@app.post("/products/{sku}/push-to-shopify")
async def push_to_shopify(sku: str, x_api_key: str = Header(None)):
    """Push a product to your Shopify store. Creates it if new, updates if it already exists."""
    verify_api_key(x_api_key)

    if not SHOPIFY_STORE or not SHOPIFY_TOKEN:
        raise HTTPException(status_code=400, detail="Shopify not configured. Set SHOPIFY_STORE and SHOPIFY_TOKEN env vars.")

    conn = get_db()
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")

    product = dict(row)
    shopify_product_id = product.get("shopify_product_id", "")

    # Build the Shopify product payload
    shopify_data = {
        "product": {
            "title": product["name"],
            "body_html": product["description"],
            "vendor": product["supplier"],
            "product_type": "",
            "status": "active" if product["status"] == "active" else "draft",
            "variants": [{
                "sku": product["sku"],
                "price": str(product["price"]),
                "inventory_management": "shopify",
            }],
        }
    }

    # Add image if we have a photo URL
    if product["photo_url"]:
        shopify_data["product"]["images"] = [{"src": product["photo_url"]}]

    base_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        if shopify_product_id:
            # Update existing product
            resp = await client.put(
                f"{base_url}/products/{shopify_product_id}.json",
                json=shopify_data,
                headers=headers,
            )
        else:
            # Create new product
            resp = await client.post(
                f"{base_url}/products.json",
                json=shopify_data,
                headers=headers,
            )

        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail=f"Shopify API error ({resp.status_code}): {resp.text[:300]}"
            )

        result = resp.json()
        new_shopify_id = str(result["product"]["id"])

        # Update our record
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE products SET in_shopify = 1, shopify_product_id = ?, updated_at = ? WHERE sku = ?",
            (new_shopify_id, now, sku)
        )
        conn.commit()
        conn.close()

        return {
            "status": "pushed",
            "sku": sku,
            "shopify_product_id": new_shopify_id,
            "shopify_url": f"https://{SHOPIFY_STORE}/admin/products/{new_shopify_id}",
        }

@app.get("/shopify/status")
def shopify_status(x_api_key: str = Header(None)):
    """Check whether Shopify is configured."""
    verify_api_key(x_api_key)
    return {
        "configured": bool(SHOPIFY_STORE and SHOPIFY_TOKEN),
        "store": SHOPIFY_STORE if SHOPIFY_STORE else None,
    }

# --- Dashboard ---
@app.get("/", response_class=HTMLResponse)
def dashboard():
    html_path = Path(__file__).parent / "static" / "dashboard.html"
    return HTMLResponse(html_path.read_text())

@app.get("/health")
def health():
    return {"status": "ok", "products": get_db().execute("SELECT COUNT(*) FROM products").fetchone()[0]}
