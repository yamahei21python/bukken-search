PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS buildings(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 norm_address TEXT, name TEXT, norm_name TEXT,
 lat REAL, lon REAL, age_years INTEGER, structure TEXT, floors TEXT,
 autolock INTEGER, elevator INTEGER, delivery_box INTEGER,
 UNIQUE(norm_address, norm_name));
CREATE TABLE IF NOT EXISTS units(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 building_id INTEGER REFERENCES buildings(id),
 floor INTEGER, area_m2 REAL, layout TEXT, direction TEXT, corner INTEGER,
 tub_status TEXT DEFAULT 'unknown', tub_confidence REAL DEFAULT 0,
 UNIQUE(building_id, floor, area_m2, layout));
CREATE TABLE IF NOT EXISTS listings(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 unit_id INTEGER REFERENCES units(id),
 site TEXT, url TEXT UNIQUE, rent_yen INTEGER, admin_yen INTEGER,
 shikikin TEXT, reikin TEXT, agent TEXT,
 first_seen TEXT DEFAULT (datetime('now','localtime')),
 last_seen TEXT DEFAULT (datetime('now','localtime')), active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS listing_snapshots(
 id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER REFERENCES listings(id),
 fetched_at TEXT DEFAULT (datetime('now','localtime')),
 rent_yen INTEGER, admin_yen INTEGER, active INTEGER, equip_text TEXT);
CREATE TABLE IF NOT EXISTS costs(
 listing_id INTEGER PRIMARY KEY REFERENCES listings(id),
 key_money_yen INTEGER, deposit_yen INTEGER, agency_yen INTEGER,
 guarantee_first_yen INTEGER, guarantee_renew_yen INTEGER,
 insurance_yen INTEGER, key_exchange_yen INTEGER, cleaning_yen INTEGER,
 support_yen INTEGER, water_fixed_yen INTEGER, renewal_fee_yen INTEGER,
 contract_months INTEGER DEFAULT 24, free_rent_months REAL DEFAULT 0,
 regular_lease INTEGER DEFAULT 1, fetched INTEGER DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS stations(
 id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER REFERENCES units(id),
 name TEXT, line TEXT, walk_min INTEGER);
CREATE TABLE IF NOT EXISTS amenities(unit_id INTEGER REFERENCES units(id), name TEXT,
 PRIMARY KEY(unit_id, name));
CREATE TABLE IF NOT EXISTS evidence(
 id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER REFERENCES units(id),
 tub_status TEXT, quote TEXT, url TEXT, photo_url TEXT,
 method TEXT, confidence REAL,
 checked_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS favorites(unit_id INTEGER PRIMARY KEY REFERENCES units(id),
 memo TEXT, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS viewings(
 id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER REFERENCES units(id),
 viewed_on TEXT, score INTEGER, memo TEXT);
CREATE TABLE IF NOT EXISTS contacts(
 id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER REFERENCES units(id),
 contacted_on TEXT DEFAULT (datetime('now','localtime')),
 question TEXT, answer TEXT, agent TEXT);
CREATE TABLE IF NOT EXISTS notifications(
 id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER REFERENCES listings(id),
 kind TEXT, message TEXT,
 created_at TEXT DEFAULT (datetime('now','localtime')));
