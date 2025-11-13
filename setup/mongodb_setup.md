# MongoDB Setup Guide

This guide helps you (Sam!) get MongoDB running locally, connect from Python, and store Polymarket markets + price history.

---

## 1) Install MongoDB Community Edition

### macOS (Homebrew)
```bash
brew tap mongodb/brew
brew install mongodb-community@7.0
brew services start mongodb-community@7.0
```

### Ubuntu / Debian
```bash
sudo apt update
sudo apt install -y mongodb
sudo systemctl start mongodb
sudo systemctl enable mongodb
systemctl status mongodb
```

### Windows
1. Download “MongoDB Community Server” from mongodb.com → Install with defaults.  
2. Ensure **MongoDB Server** is running as a Windows service (`services.msc`).  
3. MongoDB Compass (GUI) is optional but recommended.

> Default local URI: `mongodb://localhost:27017/`

---

## 2) Verify it’s running

```bash
mongosh "mongodb://localhost:27017"
```

Then inside:
```javascript
show dbs
use polymarket_db
db.createCollection("markets")
db.createCollection("price_history")
show collections
```

---

## 3) Project database layout

- **Database:** `polymarket_db`
- **Collections:** `markets`, `price_history`

```javascript
use polymarket_db
db.createCollection("markets")
db.createCollection("price_history")
```

---

## 4) Indexes

```javascript
use polymarket_db
db.markets.createIndex({ conditionId: 1 })
db.markets.createIndex({ gameStartTime: 1 })
db.price_history.createIndex({ conditionId: 1, t: 1 })
```

---

## 5) Python connection

```bash
pip install pymongo
```

```python
from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/")
db = client["polymarket_db"]
markets = db["markets"]
price_history = db["price_history"]
markets.insert_one({"_test": True})
print("Count:", markets.count_documents({}))
```

---

## 6) Useful Queries

```python
docs = markets.find({
    "gameStartTime": {"$exists": True, "$nin": [None, ""]}
})

markets.update_one(
    {"conditionId": market["conditionId"]},
    {"$set": market},
    upsert=True
)
```

---

## 7) Environment Variables

```
MONGODB_URI=mongodb://localhost:27017/
MONGO_DB=polymarket_db
MARKETS_COLL=markets
PRICE_COLL=price_history
```

---

## 8) Docker Option

```bash
docker run -d --name mongo -p 27017:27017 -v mongo_data:/data/db mongo:7
```

---

## 9) Quick End-to-End Test

```python
from pymongo import MongoClient
from datetime import datetime, timezone

client = MongoClient("mongodb://localhost:27017/")
db = client["polymarket_db"]
mk = db["markets"]
ph = db["price_history"]

mk.update_one(
    {"conditionId": "demo-123"},
    {"$set": {"title": "Demo Market", "gameStartTime": datetime.now(timezone.utc).isoformat()}},
    upsert=True
)

ph.insert_many([
    {"conditionId": "demo-123", "t": 1731111111, "price": 0.44},
    {"conditionId": "demo-123", "t": 1731111171, "price": 0.47},
])

print("Markets:", mk.count_documents({}))
print("PH rows:", ph.count_documents({"conditionId": "demo-123"}))
```

---

**That’s it!** Once MongoDB is up, your example script can fetch markets, filter by `gameStartTime`, convert to epoch, and save price history.
