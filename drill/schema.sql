CREATE TABLE IF NOT EXISTS card(
  card_id TEXT PRIMARY KEY, deck TEXT NOT NULL, kind TEXT NOT NULL,
  prompt_en TEXT NOT NULL, accept_json TEXT NOT NULL,
  reject_json TEXT NOT NULL DEFAULT '[]', note TEXT,
  tags_json TEXT NOT NULL DEFAULT '[]', content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sched(
  card_id TEXT PRIMARY KEY REFERENCES card(card_id) ON DELETE CASCADE,
  due_at TEXT NOT NULL, interval_days REAL NOT NULL DEFAULT 0,
  ease REAL NOT NULL DEFAULT 2.5, reps INTEGER NOT NULL DEFAULT 0,
  lapses INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'new',
  last_reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS review(
  review_id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id TEXT NOT NULL REFERENCES card(card_id) ON DELETE CASCADE,
  reviewed_at TEXT NOT NULL, grade INTEGER NOT NULL, latency_ms INTEGER,
  raw_text TEXT, accepted INTEGER NOT NULL, layer TEXT,
  interval_before REAL, interval_after REAL);
CREATE INDEX IF NOT EXISTS idx_sched_due ON sched(due_at);
CREATE INDEX IF NOT EXISTS idx_review_card ON review(card_id, reviewed_at);
CREATE TABLE IF NOT EXISTS setting(
  key TEXT PRIMARY KEY, value TEXT NOT NULL);
