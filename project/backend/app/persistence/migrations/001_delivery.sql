-- Incremental local workflow; separate tables from calendar access.
CREATE TABLE IF NOT EXISTS delivery_runs (
    delivery_id UUID PRIMARY KEY,
    request_hash TEXT NOT NULL,
    request JSONB NOT NULL,
    status TEXT NOT NULL,
    handoff JSONB,
    report JSONB,
    report_timing JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS delivery_artifacts (
    artifact_id UUID PRIMARY KEY,
    delivery_id UUID NOT NULL REFERENCES delivery_runs(delivery_id),
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    content BYTEA NOT NULL
);
