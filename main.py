import os
from typing import Optional

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Eastern Lights Backend")

DATABASE_URL = os.getenv("DATABASE_URL")
API_KEY = os.getenv("API_KEY", "eastern-lights-secret-key")


def get_conn():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL)


def check_key(x_api_key: Optional[str]):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


class RegisterData(BaseModel):
    employee_id: str
    staff_name: str
    device_id: str


class TrackingData(BaseModel):
    employee_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None
    beacon_id: Optional[str] = None
    beacon_rssi: Optional[int] = None
    screen_active: Optional[bool] = None
    moving: Optional[bool] = None
    battery_level: Optional[int] = None
    tamper_status: Optional[str] = "normal"


@app.get("/health")
def health():
    return {"status": "ok", "app": "Eastern Lights"}


@app.post("/register")
def register(data: RegisterData, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO staff (employee_id, staff_name, device_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (employee_id)
        DO UPDATE SET staff_name = EXCLUDED.staff_name,
                      device_id = EXCLUDED.device_id
        """,
        (data.employee_id, data.staff_name, data.device_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "registered"}


@app.post("/track")
def track(data: TrackingData, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO tracking_logs (
            employee_id, latitude, longitude, accuracy,
            beacon_id, beacon_rssi, screen_active,
            moving, battery_level, tamper_status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            data.employee_id,
            data.latitude,
            data.longitude,
            data.accuracy,
            data.beacon_id,
            data.beacon_rssi,
            data.screen_active,
            data.moving,
            data.battery_level,
            data.tamper_status,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "saved"}


def safe_text(value, default="-"):
    return default if value is None or value == "" else str(value)


def format_time(value):
    if value is None:
        return "-"
    try:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


@app.get("/api/tracks")
def api_tracks(limit: int = Query(100, ge=1, le=1000)):
    """Return recent GPS tracks grouped by employee ID. Times are returned in UAE time."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                tl.employee_id,
                COALESCE(s.staff_name, '') AS staff_name,
                tl.latitude,
                tl.longitude,
                tl.accuracy,
                tl.beacon_id,
                tl.beacon_rssi,
                tl.screen_active,
                tl.moving,
                tl.battery_level,
                tl.tamper_status,
                tl.created_at + INTERVAL '4 hours' AS created_at_uae
            FROM tracking_logs tl
            LEFT JOIN staff s ON s.employee_id = tl.employee_id
            WHERE tl.latitude IS NOT NULL
              AND tl.longitude IS NOT NULL
            ORDER BY tl.employee_id, tl.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    tracks = {}
    for row in rows:
        (
            employee_id,
            staff_name,
            latitude,
            longitude,
            accuracy,
            beacon_id,
            beacon_rssi,
            screen_active,
            moving,
            battery_level,
            tamper_status,
            created_at,
        ) = row
        point = {
            "employee_id": employee_id,
            "staff_name": staff_name,
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy,
            "beacon_id": beacon_id,
            "beacon_rssi": beacon_rssi,
            "screen_active": screen_active,
            "moving": moving,
            "battery_level": battery_level,
            "tamper_status": tamper_status or "normal",
            "created_at": format_time(created_at),
        }
        tracks.setdefault(employee_id, []).append(point)

    # Database query returns newest first. Reverse each track so path lines draw oldest to newest.
    for employee_id in tracks:
        tracks[employee_id].reverse()

    return {"tracks": tracks}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT ON (tl.employee_id)
                tl.employee_id,
                COALESCE(s.staff_name, '') AS staff_name,
                tl.latitude,
                tl.longitude,
                tl.beacon_id,
                tl.beacon_rssi,
                tl.screen_active,
                tl.moving,
                tl.battery_level,
                tl.tamper_status,
                tl.created_at + INTERVAL '4 hours' AS created_at_uae
            FROM tracking_logs tl
            LEFT JOIN staff s ON s.employee_id = tl.employee_id
            ORDER BY tl.employee_id, tl.created_at DESC
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as exc:
        rows = []
        error = str(exc)
    else:
        error = None

    table_rows = ""
    for r in rows:
        emp, staff_name, lat, lon, beacon, rssi, screen, moving, battery, tamper, created = r
        maps_link = "-"
        if lat is not None and lon is not None:
            maps_link = f'<a target="_blank" href="https://www.google.com/maps?q={lat},{lon}">{lat}, {lon}</a>'
        table_rows += f"""
        <tr>
            <td>{safe_text(emp)}</td>
            <td>{safe_text(staff_name)}</td>
            <td>{maps_link}</td>
            <td>{safe_text(beacon)}</td>
            <td>{rssi if rssi is not None else '-'}</td>
            <td><span class="{'good' if screen else 'bad'}">{'Active' if screen else 'Inactive'}</span></td>
            <td>{'Moving' if moving else 'Still'}</td>
            <td>{battery if battery is not None else '-'}%</td>
            <td>{tamper or 'normal'}</td>
            <td>{format_time(created)}</td>
        </tr>
        """

    error_html = f'<div class="error">Database error: {error}</div>' if error else ""

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Eastern Lights Dashboard</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f4f6f8; margin:0; padding:20px; }}
            .top {{ background:#111f4d; color:white; padding:18px; border-radius:14px; margin-bottom:18px; }}
            h1 {{ margin:0; font-size:26px; }}
            .nav {{ margin-top:12px; }}
            .nav a {{ background:white; color:#111f4d; padding:8px 12px; border-radius:8px; text-decoration:none; font-weight:bold; margin-right:8px; }}
            .card {{ background:white; padding:16px; border-radius:14px; box-shadow:0 2px 12px rgba(0,0,0,.08); overflow-x:auto; }}
            table {{ width:100%; border-collapse:collapse; min-width:1100px; }}
            th, td {{ padding:12px; border-bottom:1px solid #e5e7eb; text-align:left; font-size:14px; }}
            th {{ background:#eef2ff; color:#111f4d; }}
            .good {{ color:#15803d; font-weight:bold; }}
            .bad {{ color:#dc2626; font-weight:bold; }}
            .error {{ background:#fee2e2; color:#991b1b; padding:12px; border-radius:10px; margin-bottom:15px; }}
            a {{ color:#2563eb; }}
        </style>
    </head>
    <body>
        <div class="top">
            <h1>Eastern Lights Staff Dashboard</h1>
            <div>Live tracking dashboard - UAE time</div>
            <div class="nav"><a href="/">Dashboard</a><a href="/map">Map View</a></div>
        </div>
        {error_html}
        <div class="card">
            <table>
                <tr>
                    <th>Employee ID</th>
                    <th>Staff Name</th>
                    <th>GPS</th>
                    <th>Beacon</th>
                    <th>RSSI</th>
                    <th>Screen</th>
                    <th>Movement</th>
                    <th>Battery</th>
                    <th>Tamper</th>
                    <th>Last Update UAE</th>
                </tr>
                {table_rows}
            </table>
        </div>
    </body>
    </html>
    """


@app.get("/map", response_class=HTMLResponse)
def map_view():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Eastern Lights Map View</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            body { margin:0; font-family:Arial, sans-serif; background:#f4f6f8; }
            .top { background:#111f4d; color:white; padding:14px 18px; }
            h1 { margin:0; font-size:24px; }
            .nav { margin-top:10px; }
            .nav a { background:white; color:#111f4d; padding:7px 11px; border-radius:8px; text-decoration:none; font-weight:bold; margin-right:8px; }
            #map { height: calc(100vh - 105px); width:100%; }
            .popup-title { font-weight:bold; font-size:16px; margin-bottom:6px; }
            .popup-row { margin:3px 0; }
            .tag { display:inline-block; padding:3px 7px; border-radius:999px; background:#eef2ff; margin:2px 2px 2px 0; font-size:12px; }
            .status-good { color:#15803d; font-weight:bold; }
            .status-bad { color:#dc2626; font-weight:bold; }
            .legend { position:absolute; bottom:18px; left:18px; background:white; padding:10px 12px; border-radius:10px; z-index:999; box-shadow:0 2px 8px rgba(0,0,0,.2); font-size:13px; }
        </style>
    </head>
    <body>
        <div class="top">
            <h1>Eastern Lights Staff Map</h1>
            <div>Location tracks, latest staff position, and live details</div>
            <div class="nav"><a href="/">Dashboard</a><a href="/map">Map View</a></div>
        </div>
        <div id="map"></div>
        <div class="legend">Auto-refresh: 60 seconds<br>Latest marker + track line per employee</div>
        <script>
            const map = L.map('map').setView([25.2048, 55.2708], 11);
            L.tileLayer(
              'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
               { attribution: 'Tiles © Esri',
                 maxZoom: 19      }
            ).addTo(map);

            let layerGroup = L.layerGroup().addTo(map);

            function markerHtml(employeeId, moving, battery) {
                const bg = moving ? '#16a34a' : '#2563eb';
                const batteryText = battery === null || battery === undefined ? '-' : battery + '%';
                return `<div style="background:${bg}; color:white; border-radius:18px; padding:5px 8px; border:2px solid white; box-shadow:0 2px 6px rgba(0,0,0,.35); font-size:12px; font-weight:bold; white-space:nowrap;">ID ${employeeId} | ${batteryText}</div>`;
            }

            function popupHtml(p) {
                const screenClass = p.screen_active ? 'status-good' : 'status-bad';
                return `
                    <div class="popup-title">Employee ID: ${p.employee_id}</div>
                    <div class="popup-row"><b>Name:</b> ${p.staff_name || '-'}</div>
                    <div class="popup-row"><b>GPS:</b> ${p.latitude}, ${p.longitude}</div>
                    <div class="popup-row"><b>Accuracy:</b> ${p.accuracy ?? '-'} m</div>
                    <div class="popup-row"><b>Last Update UAE:</b> ${p.created_at}</div>
                    <div class="popup-row">
                        <span class="tag">Battery: ${p.battery_level ?? '-'}%</span>
                        <span class="tag">Movement: ${p.moving ? 'Moving' : 'Still'}</span>
                        <span class="tag ${screenClass}">Screen: ${p.screen_active ? 'Active' : 'Inactive'}</span>
                    </div>
                    <div class="popup-row">
                        <span class="tag">Beacon: ${p.beacon_id || '-'}</span>
                        <span class="tag">RSSI: ${p.beacon_rssi ?? '-'}</span>
                        <span class="tag">Tamper: ${p.tamper_status || 'normal'}</span>
                    </div>
                    <div class="popup-row"><a target="_blank" href="https://www.google.com/maps?q=${p.latitude},${p.longitude}">Open in Google Maps</a></div>
                `;
            }

            async function loadTracks() {
                try {
                    const response = await fetch('/api/tracks?limit=500');
                    const data = await response.json();
                    if (data.error) throw new Error(data.error);

                    layerGroup.clearLayers();
                    const bounds = [];
                    const tracks = data.tracks || {};

                    Object.keys(tracks).forEach((employeeId) => {
                        const points = tracks[employeeId];
                        if (!points || points.length === 0) return;

                        const latlngs = points.map(p => [p.latitude, p.longitude]);
                        latlngs.forEach(x => bounds.push(x));

                        if (latlngs.length > 1) {
                            L.polyline(latlngs, { weight: 4, opacity: 0.65 }).addTo(layerGroup);
                        }

                        // Add small historical dots
                        points.slice(0, -1).forEach((p) => {
                            L.circleMarker([p.latitude, p.longitude], { radius: 4, weight: 1, opacity: 0.7, fillOpacity: 0.5 })
                                .bindPopup(popupHtml(p))
                                .addTo(layerGroup);
                        });

                        const latest = points[points.length - 1];
                        const icon = L.divIcon({
                            className: '',
                            html: markerHtml(latest.employee_id, latest.moving, latest.battery_level),
                            iconSize: [120, 30],
                            iconAnchor: [20, 15]
                        });
                        L.marker([latest.latitude, latest.longitude], { icon })
                            .bindPopup(popupHtml(latest))
                            .addTo(layerGroup);
                    });

                    if (bounds.length > 0) {
                        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
                    }
                } catch (err) {
                    console.error(err);
                    alert('Unable to load map data: ' + err.message);
                }
            }

            loadTracks();
            setInterval(loadTracks, 60000);
        </script>
    </body>
    </html>
    """
