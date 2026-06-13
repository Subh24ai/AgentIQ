-- AgentIQ initial schema (Supabase / Postgres)
-- Apply with: supabase db push, or paste into the Supabase SQL editor.

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

-- ---------------------------------------------------------------------------
-- runs: one row per pipeline execution
-- ---------------------------------------------------------------------------
create table if not exists runs (
    id          uuid primary key default gen_random_uuid(),
    created_at  timestamptz not null default now(),
    lead        jsonb not null,
    status      text not null default 'started',
    token_usage jsonb not null default '{}'::jsonb
);

-- ---------------------------------------------------------------------------
-- outreach_log: emails generated / sent for a run
-- ---------------------------------------------------------------------------
create table if not exists outreach_log (
    id              uuid primary key default gen_random_uuid(),
    run_id          uuid not null references runs(id) on delete cascade,
    created_at      timestamptz not null default now(),
    recipient_email text not null,
    subject         text not null,
    body            text not null,
    sent_at         timestamptz,
    gmail_thread_id text
);

-- ---------------------------------------------------------------------------
-- hitl_reviews: human-in-the-loop review decisions
-- ---------------------------------------------------------------------------
create table if not exists hitl_reviews (
    id            uuid primary key default gen_random_uuid(),
    run_id        uuid not null references runs(id) on delete cascade,
    created_at    timestamptz not null default now(),
    eval_score    float,
    draft         jsonb,
    decision      text,
    reviewer_notes text,
    reviewed_at   timestamptz
);

-- ---------------------------------------------------------------------------
-- eval_results: per-agent evaluation scores
-- ---------------------------------------------------------------------------
create table if not exists eval_results (
    id         uuid primary key default gen_random_uuid(),
    run_id     uuid not null references runs(id) on delete cascade,
    created_at timestamptz not null default now(),
    agent      text not null,
    score      float,
    feedback   text,
    passed     boolean
);

-- Indexes on foreign keys for fast per-run lookups.
create index if not exists idx_outreach_log_run_id on outreach_log (run_id);
create index if not exists idx_hitl_reviews_run_id on hitl_reviews (run_id);
create index if not exists idx_eval_results_run_id on eval_results (run_id);
