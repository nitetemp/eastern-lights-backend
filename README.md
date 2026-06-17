# Eastern Lights Backend

Simple FastAPI backend + rudimentary web dashboard for the Eastern Lights staff tracker Android app.

## Files

- `main.py` - API and dashboard
- `requirements.txt` - Python packages
- `.env.example` - sample environment file
- `database.sql` - SQL table creation script

## Database setup

Create a PostgreSQL database in Neon/Supabase/Render, then run the SQL in `database.sql`.

## Local setup

1. Rename `.env.example` to `.env`
2. Put your PostgreSQL connection string in `.env`
3. Install packages:

```bash
pip install -r requirements.txt
```

4. Run:

```bash
uvicorn main:app --reload
```

5. Open:

```text
http://127.0.0.1:8000
```

## API endpoints

### Health check

```text
GET /health
```

### Register staff/device

```text
POST /register
Header: x-api-key: eastern-lights-secret-key
```

Body:

```json
{
  "employee_id": "EMP001",
  "staff_name": "Rahul",
  "device_id": "android-device-id"
}
```

### Upload tracking data

```text
POST /track
Header: x-api-key: eastern-lights-secret-key
```

Body:

```json
{
  "employee_id": "EMP001",
  "latitude": 24.4539,
  "longitude": 54.3773,
  "accuracy": 12.5,
  "beacon_id": "Office_Beacon_01",
  "beacon_rssi": -55,
  "screen_active": true,
  "moving": true,
  "battery_level": 80,
  "tamper_status": "normal"
}
```
"# eastern-lights-backend" 
