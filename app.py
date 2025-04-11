import psycopg2
from flask import Flask, jsonify, render_template
import requests
from flask_apscheduler import APScheduler
import threading
import time

app = Flask(__name__)

# Database connection
def db_connection():
    return psycopg2.connect(
    dbname="hq_db",
    user="hq_user",
    password="hq_pass",
    host="hq-db",
    port=5432
)

# HQ URL for truck events
HQ_URL = "http://hq:5001/get-truck-events"
# Shared Kibana dashboard URL
KIBANA_URL = "http://localhost:5601/app/dashboards#/view/a3348423-0e50-4a41-a5d3-1fc38d79af06?_g=(refreshInterval:(pause:!t,value:60000),time:(from:now-15m,to:now))&_a=()"
ELASTICSEARCH_URL = "http://elasticsearch:9200"
# Enable auto-reload in development mode
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Auto Sync data
scheduler = APScheduler()
latest_events = []

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/')
def home():
    return "Truck is running. Go to /dashboard to view the dashboard. ✅"

def update_truck_route():
    try:
        response = requests.get("http://localhost:5002/truck-events")  # Change to correct field server port
        if response.status_code == 200:
            data = response.json()
            global truck_route
            truck_route = [
                {
                    "lat": float(location.split(",")[0]),
                    "lon": float(location.split(",")[1]),
                    "location": entry["location"],
                    "status": entry["status"]
                }
                for entry in data
                for location in [entry["location"]]
            ]
            print(f"✅ Updated Truck Route: {truck_route}")
        else:
            print("❌ Failed to fetch truck data")

    except Exception as e:
        print(f"❌ Error fetching truck data: {str(e)}")
# chatGPT simulated route for Truck
# truck_route = [
#     {"lat": 43.5813, "lon": -96.7419, "location": "Sioux Falls Regional Airport"},
#     {"lat": 43.5460, "lon": -96.7313, "location": "Downtown Sioux Falls"},
#     {"lat": 43.5105, "lon": -96.7760, "location": "The Empire Mall"},
#     {"lat": 43.5315, "lon": -96.7456, "location": "Sanford USD Medical Center"},
#     {"lat": 43.4846, "lon": -96.7323, "location": "Sioux Falls Truck Stop"}
# ]

# current_index = 0  # Track current stop

# # Function to update truck location in Elasticsearch every 10 seconds
# def update_truck_location():
#     global current_index
#     while True:
#         current_stop = truck_route[current_index]
#         last_updated = time.strftime("%Y-%m-%d %H:%M:%S")

#         try:
#             conn = db_connection()
#             cur = conn.cursor()

#             # Save data to HQ DB
#             cur.execute("""
#                 INSERT INTO trucks (truck_id, status, location, event, last_updated)
#                 VALUES (%s, %s, %s, %s, %s)
#             """, (f"{current_stop['truck_id']}", "in transit", f"{current_stop['lat']}, {current_stop['lon']}",
#                 f"{current_stop['location']} ", last_updated))
#             db_connection.commit()

#             print(f"✅ Truck location saved to HQ DB: {current_stop['location']}")
#             # Update Elasticsearch with new location
#             data = {
#                 "truck_id": f"{current_stop['truck_id']}",
#                 "status": "in transit",
#                 "location": f"{current_stop['lat']}, {current_stop['lon']}",
#                 "event": f"{current_stop['location']}",
#                 "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
#             }
#             response = requests.post(f"{ELASTICSEARCH_URL}/trucks/_doc", json=data)
#             if response.status_code == 201:
#                 print(f"📍 Truck is now at: {current_stop['location']} and updated ES")
#             else:
#                 print(f"❌ Failed to sync with Elasticsearch: {response.text}")

#         except Exception as e:
#             print(f"❌ Error updating truck location: {str(e)}")

#         # Move to next stop (loop back to start when reaching end)
#         current_index = (current_index + 1) % len(truck_route)

#         time.sleep(3)  # Wait 10 seconds before updating again

def fetch_truck_events():
    print("🔄 Fetching latest truck data from Elasticsearch...")
    es_query = {
        "query": {
           "wildcard": { "truck_id.keyword": "Truck-*"}
       }
    }
    response = requests.get(f"{ELASTICSEARCH_URL}/trucks/_search", json=es_query)

    if response.status_code == 200:
        data = response.json()
        print("✅ Truck events fetched successfully!")
        return data  # ✅ Returns data to the scheduler (not the frontend)
    else:
        print("❌ Failed to fetch truck events:", response.status_code)

@app.route("/truck-events", methods=["GET"])
def get_truck_events():
   global latest_events
   es_query = {
       "size": 5,  # Get the latest 5 updates
       "sort": [{"last_updated": {"order": "desc"}}],  # Sort by most recent
       "_source": ["truck_id", "status", "location", "event", "last_updated"],  # Only get needed fields
       "query": {
           "wildcard": { "truck_id.keyword": "Truck-*"}
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
            print("Truck events have been updated 👍")
            return jsonify(latest_events)
        else: 
            latest_events = []
            return jsonify({"error": "No truck data found or failed to fetch truck data"}), 500
   else:
        return jsonify({"error": "No truck data found or failed to fetch truck data"}), 500

# Latest Sync

@scheduler.task("interval", id="sync_data", seconds=3)
def sync_data():
    print(f"🚴‍♀️Syncing your data from ES...")
    fetch_truck_events()

# truck dashboard
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', kibana_url=KIBANA_URL)

# Scheduler
#scheduler.add_job(id="sync_truck_data", func=get_truck_events, trigger="interval", seconds=30)
scheduler.init_app(app)
scheduler.start()
# Start the location update thread
threading.Thread(target=update_truck_route, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
