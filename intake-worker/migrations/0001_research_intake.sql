CREATE TABLE IF NOT EXISTS research_challenges (
  challenge_id TEXT PRIMARY KEY,
  nonce TEXT NOT NULL,
  difficulty INTEGER NOT NULL,
  ip_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_challenges_ip_created
  ON research_challenges(ip_hash, created_at);

CREATE TABLE IF NOT EXISTS research_submissions (
  receipt_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  research_question TEXT NOT NULL,
  reference_notes TEXT NOT NULL DEFAULT '',
  visibility TEXT NOT NULL CHECK (visibility IN ('public', 'private')),
  requester_email TEXT NOT NULL DEFAULT '',
  ip_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued', 'imported', 'blocked')),
  attempts INTEGER NOT NULL DEFAULT 0,
  local_job_id TEXT NOT NULL DEFAULT '',
  last_error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  imported_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_submissions_queue
  ON research_submissions(status, created_at);
CREATE INDEX IF NOT EXISTS idx_research_submissions_ip_created
  ON research_submissions(ip_hash, created_at);
