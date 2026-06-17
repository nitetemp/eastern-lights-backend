CREATE TABLE IF NOT EXISTS staff (
    id SERIAL PRIMARY KEY,
    employee_id TEXT UNIQUE NOT NULL,
    staff_name TEXT NOT NULL,
    device_id TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tracking_logs (
    id SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    accuracy DOUBLE PRECISION,
    beacon_id TEXT,
    beacon_rssi INTEGER,
    screen_active BOOLEAN,
    moving BOOLEAN,
    battery_level INTEGER,
    tamper_status TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
