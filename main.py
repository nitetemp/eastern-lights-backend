import os
from typing import Optional

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
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


@app.get("/", response_class=HTMLResponse)
def dashboard():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT ON (employee_id)
                employee_id, latitude, longitude, beacon_id,
                beacon_rssi, screen_active, moving, 
                battery_level, tamper_status,
                created_at + INTERVAL '4 hours' as created_at
            FROM tracking_logs
            ORDER BY employee_id, created_at DESC
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
        emp, lat, lon, beacon, rssi, screen, moving, battery, tamper, created = r
        maps_link = "-"
        if lat is not None and lon is not None:
            maps_link = f'<a target="_blank" href="https://www.google.com/maps?q={lat},{lon}">{lat}, {lon}</a>'
        table_rows += f"""
        <tr>
            <td>{emp}</td>
            <td>{maps_link}</td>
            <td>{beacon or '-'}</td>
            <td>{rssi if rssi is not None else '-'}</td>
            <td><span class="{'good' if screen else 'bad'}">{'Active' if screen else 'Inactive'}</span></td>
            <td>{'Moving' if moving else 'Still'}</td>
            <td>{battery if battery is not None else '-'}%</td>
            <td>{tamper or 'normal'}</td>
            <td>{created}</td>
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
            .card {{ background:white; padding:16px; border-radius:14px; box-shadow:0 2px 12px rgba(0,0,0,.08); overflow-x:auto; }}
            table {{ width:100%; border-collapse:collapse; min-width:900px; }}
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
            <div>Rudimentary live tracking dashboard</div>
        </div>
        {error_html}
        <div class="card">
            <table>
                <tr>
                    <th>Employee ID</th>
                    <th>GPS</th>
                    <th>Beacon</th>
                    <th>RSSI</th>
                    <th>Screen</th>
                    <th>Movement</th>
                    <th>Battery</th>
                    <th>Tamper</th>
                    <th>Last Update</th>
                </tr>
                {table_rows}
            </table>
        </div>
    </body>
    </html>
    """
