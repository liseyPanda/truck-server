from flask import Flask, jsonify, render_template
from flask_apscheduler import APScheduler
import requests
import psycopg2
from datetime import datetime
import threading

app = Flask(__name__)

# PostgreSQL connection to HQ DB
def db_connection():
    return psycopg2.connect(
        dbname="hq_db",
        user="hq_user",
        password="hq_pass",
        host="hq-db",
        port=5432
    )

# DNS URLs to HQ and Cloud (now HTTPS over 8080)
HQ_URL = "https://hq-server-git-kompose-ndrc.apps.osc-hq.hq.ndrc.mil:8080/update"
CLOUD_URL = "https://cloud-server-git-kompose-ndrc.apps.osc-trailer.trailer.ndrc.mil:8080/update"
ELASTICSEARCH_URL = "http://elasticsearch-route-kompose-ndrc.apps.osc-trailer.trailer.ndrc.mil";

scheduler = APScheduler()
latest_events = []

@app.route("/")
def home():
    return "✅ Truck Server is up! Dashboard available at /dashboard"

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store"
    return response

# Pull truck events from Elasticsearch
@app.route("/truck-events", methods=["GET"])
def get_truck_events():
    global latest_events
    es_query = {
        "size": 5,
        "sort": [{"last_updated": {"order": "desc"}}],
        "_source": ["truck_id", "status", "location", "event", "last_updated"],
        "query": {
            "wildcard": {"truck_id.keyword": "Truck-*"}
        }
    }

    response = requests.get(f"{ELASTICSEARCH_URL}/trucks/_search", json=es_query)
    if response.status_code == 200:
        data = response.json()
        if "hits" in data and "hits" in data["hits"]:
            latest_events = [
                {
                    "truck_id": hit["_source"]["truck_id"],
                    "status": hit["_source"]["status"],
                    "location": hit["_source"]["location"],
                    "event": hit["_source"]["event"],
                    "last_updated": hit["_source"]["last_updated"]
                }
                for hit in data["hits"]["hits"]
            ]
            return jsonify(latest_events)
    return jsonify({"error": "Failed to fetch data"}), 500

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

# Keep Elasticsearch synced
@scheduler.task("interval", id="sync_truck", seconds=3)
def sync_data():
    get_truck_events()

# Simulate truck movement and send to HQ/Cloud
def simulate_route():
    import time
    route = [
        {"lat": 43.5813, "lon": -96.7419, "event": "Sioux Falls Regional Airport"},
        {"lat": 43.5460, "lon": -96.7313, "event": "Downtown Sioux Falls"},
        {"lat": 43.5105, "lon": -96.7760, "event": "The Empire Mall"},
        {"lat": 43.5315, "lon": -96.7456, "event": "Sanford USD Medical Center"},
        {"lat": 43.4846, "lon": -96.7323, "event": "Truck Stop"}
    ]
    index = 0
    truck_id = "Truck-1"
    while True:
        current = route[index]
        payload = {
            "truck_id": truck_id,
            "status": "in transit",
            "location": f"{current['lat']}, {current['lon']}",
            "event": f"Moving to {current['event']}",
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

        try:
            res = requests.post(HQ_URL, json=payload, timeout=2, verify=False)
            if res.status_code != 201:
                raise Exception("HQ down")
        except:
            requests.post(CLOUD_URL, json=payload, verify=False)

        index = (index + 1) % len(route)
        time.sleep(10)

# Init & start everything
scheduler.init_app(app)
scheduler.start()
threading.Thread(target=simulate_route, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
