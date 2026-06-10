# Product Catalog API

REST API with dashboard for managing a product catalog. Built with FastAPI + SQLite.

## Endpoints

All API endpoints require an `X-Api-Key` header.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/products` | List all products (supports `?search=`, `?status=`, `?supplier=` query params) |
| `POST` | `/products` | Add or upsert a product |
| `GET` | `/products/{sku}` | Get one product by SKU |
| `PATCH` | `/products/{sku}` | Update specific fields |
| `DELETE` | `/products/{sku}` | Delete a product |
| `GET` | `/health` | Health check |
| `GET` | `/` | Web dashboard |

## Product fields

```json
{
  "sku": "PB-500",
  "name": "PhytoBiome 500g",
  "supplier": "Health Food Symmetry",
  "price": 29.95,
  "status": "active",
  "description": "Insoluble prebiotic fibre",
  "photo_url": "https://...",
  "in_shopify": false
}
```

## Run locally

```bash
pip install -r requirements.txt
export API_KEY="your-secret-key"    # optional — auto-generates if not set
uvicorn main:app --reload
```

Dashboard at `http://localhost:8000`, API at `http://localhost:8000/products`.

## Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app), create a new project → "Deploy from GitHub repo"
3. Add environment variable: `API_KEY` = (generate a strong key)
4. Railway auto-detects Python, installs deps, and deploys
5. Go to Settings → Networking → Generate Domain
6. Your API is live at `https://your-app.up.railway.app`

### Persistent storage (important for SQLite)

By default Railway's filesystem is ephemeral. To keep your data between deploys:

1. In your Railway service, go to **Settings → Volumes**
2. Add a volume, mount it at `/data`
3. Set env var: `DATABASE_PATH=/data/products.db`

## Example API calls

```bash
# Add a product
curl -X POST https://your-app.up.railway.app/products \
  -H "X-Api-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"sku":"PB-500","name":"PhytoBiome 500g","supplier":"HFS","price":29.95,"status":"active"}'

# List products
curl https://your-app.up.railway.app/products -H "X-Api-Key: your-key"

# Update status
curl -X PATCH https://your-app.up.railway.app/products/PB-500 \
  -H "X-Api-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"status":"archived"}'
```
