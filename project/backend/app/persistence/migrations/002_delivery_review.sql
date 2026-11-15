CREATE TABLE IF NOT EXISTS delivery_report_decisions (
    delivery_id UUID NOT NULL REFERENCES delivery_runs(delivery_id),
    decision_id UUID NOT NULL,
    decision JSONB NOT NULL,
    operator TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (delivery_id, decision_id)
);
