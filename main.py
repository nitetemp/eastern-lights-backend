import csv
import io
import os
from typing import Optional

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Eastern Lights Backend")

DATABASE_URL = os.getenv("DATABASE_URL")
API_KEY = os.getenv("API_KEY", "eastern-lights-secret-key")
APP_VERSION = "FULL_MAP_FEATURES_2026_06_17_v4_STABLE_UI"


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
    return {"status": "ok", "app": "Eastern Lights", "version": APP_VERSION}


@app.get("/version")
def version():
    return {"version": APP_VERSION, "features": ["new_control_panel_layout", "layer_toggle", "tracks", "staff_markers", "stops_time_spent", "speed", "geofence", "playback", "search", "csv_export", "uae_time"]}


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


def fetch_tracks(hours: int = 12, employee_id: Optional[str] = None):
    conn = get_conn()
    cur = conn.cursor()
    params = [hours]
    where_employee = ""
    if employee_id:
        where_employee = "AND t.employee_id = %s"
        params.append(employee_id)

    cur.execute(
        f"""
        SELECT
            t.employee_id,
            COALESCE(s.staff_name, '') AS staff_name,
            t.latitude,
            t.longitude,
            t.accuracy,
            t.beacon_id,
            t.beacon_rssi,
            t.screen_active,
            t.moving,
            t.battery_level,
            t.tamper_status,
            t.created_at + INTERVAL '4 hours' AS created_at_uae
        FROM tracking_logs t
        LEFT JOIN staff s ON s.employee_id = t.employee_id
        WHERE t.latitude IS NOT NULL
          AND t.longitude IS NOT NULL
          AND t.created_at >= NOW() - (%s * INTERVAL '1 hour')
          {where_employee}
        ORDER BY t.employee_id, t.created_at ASC
        """,
        tuple(params),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    items = []
    for r in rows:
        created = r[11]
        items.append(
            {
                "employee_id": r[0],
                "staff_name": r[1],
                "latitude": float(r[2]) if r[2] is not None else None,
                "longitude": float(r[3]) if r[3] is not None else None,
                "accuracy": float(r[4]) if r[4] is not None else None,
                "beacon_id": r[5],
                "beacon_rssi": r[6],
                "screen_active": r[7],
                "moving": r[8],
                "battery_level": r[9],
                "tamper_status": r[10],
                "created_at": created.strftime("%Y-%m-%d %H:%M:%S") if created else "",
            }
        )
    return items


@app.get("/api/tracks")
def api_tracks(hours: int = Query(12, ge=1, le=168), employee_id: Optional[str] = None):
    return {"tracks": fetch_tracks(hours=hours, employee_id=employee_id)}


@app.get("/api/export.csv")
def export_csv(hours: int = Query(12, ge=1, le=168), employee_id: Optional[str] = None):
    rows = fetch_tracks(hours=hours, employee_id=employee_id)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "employee_id", "staff_name", "latitude", "longitude", "accuracy",
            "beacon_id", "beacon_rssi", "screen_active", "moving",
            "battery_level", "tamper_status", "created_at",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=eastern_lights_tracks.csv"},
    )


@app.get("/", response_class=HTMLResponse)
def dashboard():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT ON (t.employee_id)
                t.employee_id,
                COALESCE(s.staff_name, '') AS staff_name,
                t.latitude,
                t.longitude,
                t.beacon_id,
                t.beacon_rssi,
                t.screen_active,
                t.moving,
                t.battery_level,
                t.tamper_status,
                t.created_at + INTERVAL '4 hours' AS created_at_uae
            FROM tracking_logs t
            LEFT JOIN staff s ON s.employee_id = t.employee_id
            ORDER BY t.employee_id, t.created_at DESC
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
        created_txt = created.strftime("%Y-%m-%d %H:%M:%S") if created else "-"
        table_rows += f"""
        <tr>
            <td>{emp}</td>
            <td>{staff_name or '-'}</td>
            <td>{maps_link}</td>
            <td>{beacon or '-'}</td>
            <td>{rssi if rssi is not None else '-'}</td>
            <td><span class="{'good' if screen else 'bad'}">{'Active' if screen else 'Inactive'}</span></td>
            <td>{'Moving' if moving else 'Still'}</td>
            <td>{battery if battery is not None else '-'}%</td>
            <td>{tamper or 'normal'}</td>
            <td>{created_txt}</td>
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
            .nav a {{ display:inline-block; background:white; color:#111f4d; padding:8px 12px; border-radius:8px; margin-top:10px; margin-right:8px; text-decoration:none; font-weight:bold; }}
            .card {{ background:white; padding:16px; border-radius:14px; box-shadow:0 2px 12px rgba(0,0,0,.08); overflow-x:auto; }}
            table {{ width:100%; border-collapse:collapse; min-width:1050px; }}
            th, td {{ padding:12px; border-bottom:1px solid #e5e7eb; text-align:left; font-size:14px; white-space:nowrap; }}
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
            <div class="nav"><a href="/">Dashboard</a><a href="/map">Map View</a><a href="/api/export.csv">Export CSV</a></div>
        </div>
        {error_html}
        <div class="card">
            <table>
                <tr>
                    <th>Employee ID</th><th>Name</th><th>GPS</th><th>Beacon</th><th>RSSI</th>
                    <th>Screen</th><th>Movement</th><th>Battery</th><th>Tamper</th><th>Last Update UAE</th>
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
    <style>
        html, body { height:100%; margin:0; font-family:Arial, sans-serif; background:#0b1220; }
        .top { height:86px; background:#071229; color:white; padding:10px 16px; box-sizing:border-box; }
        .top h1 { margin:0; font-size:22px; line-height:1.2; }
        .top .subtitle { font-size:13px; opacity:.9; margin-top:2px; }
        .nav a, .nav button { display:inline-block; background:white; color:#071229; padding:7px 10px; border-radius:7px; margin:6px 6px 0 0; text-decoration:none; font-weight:bold; border:0; cursor:pointer; }
        #map { height: calc(100vh - 86px); width:100%; }

        .panel {
            position:absolute;
            top:102px;
            right:14px;
            z-index:1000;
            background:rgba(255,255,255,.96);
            padding:12px;
            border-radius:14px;
            box-shadow:0 4px 18px rgba(0,0,0,.30);
            width:320px;
            max-height:calc(100vh - 132px);
            overflow:auto;
            font-size:13px;
            backdrop-filter: blur(4px);
        }
        .panel h3 { margin:0 0 8px; color:#071229; font-size:17px; }
        .control-block { margin-bottom:10px; }
        .control-block label { display:block; font-weight:bold; color:#1f2937; margin-bottom:4px; }
        .panel input, .panel select, .panel button {
            width:100%; box-sizing:border-box; margin:0; padding:8px;
            border:1px solid #cbd5e1; border-radius:8px; background:white;
        }
        .button-row { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:8px; }
        .panel button { background:#111f4d; color:white; font-weight:bold; cursor:pointer; border:0; }
        .toggles { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:6px; }
        .toggle-item { font-size:12px; background:#f1f5f9; padding:7px; border-radius:8px; display:flex; gap:5px; align-items:center; }
        .toggle-item input { width:auto; }

        .legend { position:absolute; left:12px; bottom:22px; z-index:1000; background:rgba(255,255,255,.96); padding:10px; border-radius:10px; box-shadow:0 2px 12px rgba(0,0,0,.25); font-size:12px; }
        .staff-marker { color:white; border-radius:18px; padding:5px 9px; border:2px solid white; box-shadow:0 2px 8px rgba(0,0,0,.45); font-weight:bold; white-space:nowrap; }
        .popup-title { font-weight:bold; font-size:16px; margin-bottom:6px; }
        .popup-row { margin:3px 0; }
        .status-good { color:#15803d; font-weight:bold; }
        .status-bad { color:#dc2626; font-weight:bold; }
        .stop-list { max-height:180px; overflow:auto; margin-top:6px; }
        .stop-item { border-bottom:1px solid #e5e7eb; padding:6px 0; }
        .small { color:#555; font-size:12px; }
        .leaflet-control-layers { display:none !important; }

        @media (max-width: 760px) {
            .top { height:96px; }
            #map { height: calc(100vh - 96px); }
            .panel { left:10px; right:10px; top:106px; width:auto; max-height:42vh; }
            .legend { left:10px; bottom:10px; }
        }
    </style>
</head>
<body>
    <div class="top">
        <h1>Eastern Lights Staff Map</h1>
        <div class="subtitle">New layout: map layer, search, history, playback, stops, geofence, export</div>
        <div class="nav">
            <a href="/">Dashboard</a>
            <a href="/map">Map View</a>
            <a href="/api/export.csv" id="exportLink">Export CSV</a>
            <button onclick="loadData()">Refresh</button>
        </div>
    </div>

    <div id="map"></div>

    <div class="panel">
        <h3>Eastern Lights Controls</h3>

        <div class="control-block">
            <label>Search staff / ID</label>
            <input id="searchBox" placeholder="Example: 2 or Leon" oninput="renderAll()" />
        </div>

        <div class="control-block">
            <label>Map Layer</label>
            <select id="mapStyle" onchange="switchBaseLayer()">
                <option value="street" selected>Street Map - roads and labels</option>
                <option value="satellite">Satellite Imagery</option>
                <option value="hybrid">Satellite + Labels</option>
                <option value="osm">OpenStreetMap Backup</option>
            </select>
        </div>

        <div class="control-block">
            <label>History</label>
            <select id="hours" onchange="loadData()">
                <option value="1">Last 1 hour</option>
                <option value="6">Last 6 hours</option>
                <option value="12" selected>Last 12 hours</option>
                <option value="24">Today / 24 hours</option>
                <option value="72">Last 3 days</option>
                <option value="168">Last 7 days</option>
            </select>
        </div>

        <div class="control-block">
            <label>Auto refresh</label>
            <select id="refreshRate" onchange="resetTimer()">
                <option value="0">Off</option>
                <option value="30000">30 seconds</option>
                <option value="60000" selected>60 seconds</option>
                <option value="120000">2 minutes</option>
            </select>
        </div>

        <div class="toggles">
            <label class="toggle-item"><input type="checkbox" id="showTracks" checked onchange="renderAll()"> Tracks</label>
            <label class="toggle-item"><input type="checkbox" id="showGeofence" checked onchange="renderAll()"> Geofence</label>
            <label class="toggle-item"><input type="checkbox" id="showStops" checked onchange="renderAll()"> Stops</label>
            <label class="toggle-item"><input type="checkbox" id="fitMap" checked> Auto-fit</label>
        </div>

        <div class="button-row">
            <button onclick="playback()">Playback</button>
            <button onclick="loadData()">Reload</button>
        </div>

        <hr>
        <b>Detected stops / time spent</b>
        <div class="small">Stop = staff remains within about 75 m for 10+ minutes.</div>
        <div id="stops" class="stop-list"></div>
    </div>

    <div class="legend">Layer selection is now inside the right control panel.<br>Blue = still/latest, green = moving, line = route, circle = stop/geofence.</div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const map = L.map('map', { zoomControl: true }).setView([25.2048, 55.2708], 11);

        const street = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles © Esri', maxZoom: 19
        });
        const imagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles © Esri', maxZoom: 19
        });
        const labels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Labels © Esri', maxZoom: 19
        });
        const roads = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Roads © Esri', maxZoom: 19
        });
        const hybrid = L.layerGroup([imagery, roads, labels]);
        const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors', maxZoom: 19
        });

        const baseLayers = { street, satellite: imagery, hybrid, osm };
        let currentBase = street;
        currentBase.addTo(map);

        let data = [];
        let layerGroup = L.layerGroup().addTo(map);
        let timer = null;

        function switchBaseLayer() {
            const selected = document.getElementById('mapStyle').value;
            if (currentBase) map.removeLayer(currentBase);
            currentBase = baseLayers[selected] || street;
            currentBase.addTo(map);
        }

        function distanceMeters(a, b) {
            const R = 6371000;
            const lat1 = a.latitude * Math.PI / 180;
            const lat2 = b.latitude * Math.PI / 180;
            const dLat = (b.latitude - a.latitude) * Math.PI / 180;
            const dLon = (b.longitude - a.longitude) * Math.PI / 180;
            const x = Math.sin(dLat/2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon/2) ** 2;
            return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1-x));
        }

        function parseTime(s) { return new Date(s.replace(' ', 'T')); }
        function minutesBetween(a, b) { return Math.max(0, (parseTime(b.created_at) - parseTime(a.created_at)) / 60000); }
        function speedKmh(a, b) {
            const mins = minutesBetween(a, b);
            if (mins <= 0) return 0;
            return (distanceMeters(a,b) / 1000) / (mins / 60);
        }

        function markerHtml(employeeId, moving, battery) {
            const bg = moving ? '#16a34a' : '#2563eb';
            const batteryText = battery === null || battery === undefined ? '-' : battery + '%';
            return `<div class="staff-marker" style="background:${bg};">ID ${employeeId} | ${batteryText}</div>`;
        }

        function popupHtml(p, spd, stopText) {
            const screenClass = p.screen_active ? 'status-good' : 'status-bad';
            return `
                <div class="popup-title">Employee ID: ${p.employee_id}</div>
                <div class="popup-row"><b>Name:</b> ${p.staff_name || '-'}</div>
                <div class="popup-row"><b>GPS:</b> ${p.latitude}, ${p.longitude}</div>
                <div class="popup-row"><b>Accuracy:</b> ${p.accuracy ?? '-'} m</div>
                <div class="popup-row"><b>Speed:</b> ${spd.toFixed(1)} km/h</div>
                <div class="popup-row"><b>Screen:</b> <span class="${screenClass}">${p.screen_active ? 'Active' : 'Inactive'}</span></div>
                <div class="popup-row"><b>Movement:</b> ${p.moving ? 'Moving' : 'Still'}</div>
                <div class="popup-row"><b>Battery:</b> ${p.battery_level ?? '-'}%</div>
                <div class="popup-row"><b>Beacon:</b> ${p.beacon_id || '-'}</div>
                <div class="popup-row"><b>RSSI:</b> ${p.beacon_rssi ?? '-'}</div>
                <div class="popup-row"><b>Tamper:</b> ${p.tamper_status || 'normal'}</div>
                <div class="popup-row"><b>Last update UAE:</b> ${p.created_at}</div>
                <div class="popup-row"><b>Time near current place:</b> ${stopText}</div>
                <div class="popup-row"><a target="_blank" href="https://www.google.com/maps?q=${p.latitude},${p.longitude}">Open in Google Maps</a></div>
            `;
        }

        function groupByEmployee(items) {
            const grouped = {};
            items.forEach(p => {
                const key = String(p.employee_id);
                if (!grouped[key]) grouped[key] = [];
                grouped[key].push(p);
            });
            return grouped;
        }

        function currentPlaceTime(points) {
            if (points.length < 2) return '0 min';
            const latest = points[points.length - 1];
            let start = latest;
            for (let i = points.length - 2; i >= 0; i--) {
                if (distanceMeters(points[i], latest) <= 75) start = points[i];
                else break;
            }
            const mins = minutesBetween(start, latest);
            if (mins < 60) return `${Math.round(mins)} min`;
            return `${Math.floor(mins/60)} hr ${Math.round(mins%60)} min`;
        }

        function detectStops(points) {
            const stops = [];
            if (points.length < 2) return stops;
            let start = points[0];
            let last = points[0];
            for (let i = 1; i < points.length; i++) {
                const p = points[i];
                if (distanceMeters(start, p) <= 75) {
                    last = p;
                } else {
                    const mins = minutesBetween(start, last);
                    if (mins >= 10) stops.push({ employee_id:start.employee_id, staff_name:start.staff_name, latitude:start.latitude, longitude:start.longitude, start:start.created_at, end:last.created_at, minutes:mins });
                    start = p;
                    last = p;
                }
            }
            const mins = minutesBetween(start, last);
            if (mins >= 10) stops.push({ employee_id:start.employee_id, staff_name:start.staff_name, latitude:start.latitude, longitude:start.longitude, start:start.created_at, end:last.created_at, minutes:mins });
            return stops;
        }

        function renderStops(grouped) {
            const div = document.getElementById('stops');
            if (!document.getElementById('showStops').checked) {
                div.innerHTML = '<div class="small">Stop display is off.</div>';
                return;
            }
            let allStops = [];
            Object.values(grouped).forEach(points => allStops = allStops.concat(detectStops(points)));
            allStops = allStops.sort((a,b) => b.minutes - a.minutes).slice(0, 15);
            if (allStops.length === 0) {
                div.innerHTML = '<div class="small">No 10+ minute stops detected in selected period.</div>';
                return;
            }
            div.innerHTML = allStops.map(s => `<div class="stop-item"><b>ID ${s.employee_id}</b> ${s.staff_name || ''}<br>${Math.round(s.minutes)} min<br><span class="small">${s.start} to ${s.end}</span></div>`).join('');
        }

        function renderAll() {
            layerGroup.clearLayers();
            const search = document.getElementById('searchBox').value.toLowerCase().trim();
            const showTracks = document.getElementById('showTracks').checked;
            const showGeofence = document.getElementById('showGeofence').checked;
            const shouldFit = document.getElementById('fitMap').checked;
            const filtered = data.filter(p => !search || String(p.employee_id).toLowerCase().includes(search) || String(p.staff_name || '').toLowerCase().includes(search));
            const grouped = groupByEmployee(filtered);
            let bounds = [];

            Object.entries(grouped).forEach(([emp, points]) => {
                if (!points.length) return;
                const latlngs = points.map(p => [p.latitude, p.longitude]);
                bounds = bounds.concat(latlngs);
                if (showTracks) L.polyline(latlngs, {weight:4, opacity:0.75}).addTo(layerGroup);

                const latest = points[points.length - 1];
                const previous = points.length > 1 ? points[points.length - 2] : latest;
                const spd = speedKmh(previous, latest);
                const stopText = currentPlaceTime(points);

                const icon = L.divIcon({ html: markerHtml(latest.employee_id, latest.moving, latest.battery_level), className:'', iconSize:null });
                L.marker([latest.latitude, latest.longitude], {icon}).bindPopup(popupHtml(latest, spd, stopText)).addTo(layerGroup);

                if (showGeofence) {
                    L.circle([latest.latitude, latest.longitude], {radius:75, weight:1, fillOpacity:0.08}).addTo(layerGroup);
                }
            });

            renderStops(grouped);
            if (bounds.length && shouldFit) map.fitBounds(bounds, {padding:[40,40], maxZoom:17});
        }

        async function loadData() {
            const hours = document.getElementById('hours').value;
            document.getElementById('exportLink').href = `/api/export.csv?hours=${hours}`;
            try {
                const res = await fetch(`/api/tracks?hours=${hours}`);
                const json = await res.json();
                data = json.tracks || [];
                renderAll();
            } catch (e) {
                alert('Could not load tracking data. Check Render logs or /api/tracks.');
                console.error(e);
            }
        }

        function resetTimer() {
            if (timer) clearInterval(timer);
            const rate = Number(document.getElementById('refreshRate').value);
            if (rate > 0) timer = setInterval(loadData, rate);
        }

        function playback() {
            layerGroup.clearLayers();
            const grouped = groupByEmployee(data);
            Object.values(grouped).forEach(points => {
                let i = 0;
                const id = setInterval(() => {
                    if (i >= points.length) { clearInterval(id); return; }
                    const p = points[i];
                    L.circleMarker([p.latitude, p.longitude], {radius:5}).bindPopup(`ID ${p.employee_id}<br>${p.created_at}`).addTo(layerGroup);
                    i++;
                }, 250);
            });
        }

        loadData();
        resetTimer();
    </script>
</body>
</html>
    """
