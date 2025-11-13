from clients.gamma_client import PolymarketGammaClient
from clients.clob_client import PolymarketCLOB

try:
    import pymongo
except ImportError:
    pymongo = None  # handle gracefully

from datetime import datetime, timezone

gamma_client = PolymarketGammaClient()
clob_client = PolymarketCLOB()

mongo_db = None
mongo_collection = None

def iso_to_epoch(iso_str: str, tz_hint: str = "utc") -> int:
    """Parse ISO8601 (handles trailing 'Z') to epoch seconds (UTC)."""
    s = iso_str.strip()
    if s.endswith("Z"):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc if tz_hint.lower() == "utc" else None)
    return int(dt.astimezone(timezone.utc).timestamp())

def initialize_clients():
    global mongo_db, mongo_collection
    if pymongo is None:
        print("PyMongo not installed. Run: pip install pymongo")
        return
    try:
        client = pymongo.MongoClient("mongodb://localhost:27017/")
        mongo_db = client["polymarket_db"]
        mongo_collection = mongo_db["markets"]
    except Exception as e:
        print(f"Error initializing MongoDB client: {e}")
        mongo_db = None
        mongo_collection = None

def find_sports_markets():
    """Find markets that have a non-empty gameStartTime and pull minute data around t0."""
    if mongo_collection is None:
        print("Mongo not initialized.")
        return
    # require gameStartTime present and non-empty
    docs = mongo_collection.find({
        "gameStartTime": {"$exists": True, "$nin": [None, ""]}
    })
    for doc in docs:
        try:
            start_epoch = iso_to_epoch(doc["gameStartTime"], "utc")
            # 3 hours window
            end_epoch = start_epoch + 3 * 3600
            # CLOB client is keyword-only; pass named args and set fidelity=1m
            price_history = clob_client.get_prices_history(
                market=doc.get("conditionId") or doc.get("condition_id"),
                start_ts=start_epoch,
                end_ts=end_epoch,
                fidelity=1
            )
            # TODO: process/store price_history
        except Exception as e:
            print(f"Failed market {doc.get('_id')}: {e}")

def main():
    # Example: fetch one page of markets
    data = gamma_client.fetch_markets(limit=100, offset=0)
    if not data:
        print("No markets returned from gamma.")
    else:
        print(f"Fetched {len(data)} markets (showing first 1):")
        print(data[0])
        # Optionally insert:
        # if mongo_collection: mongo_collection.insert_many(data)

if __name__ == "__main__":
    initialize_clients()
    main()
    # find_sports_markets()
