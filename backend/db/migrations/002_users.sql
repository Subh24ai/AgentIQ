-- AgentIQ users table (Supabase / Postgres)
-- Apply with: supabase db push, or paste into the Supabase SQL editor.
-- Backs self-service registration (POST /auth/register) + login lookup.
-- Passwords are bcrypt-hashed by the backend before insert; never store plaintext.

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

create table if not exists users (
    id              uuid primary key default gen_random_uuid(),
    created_at      timestamptz not null default now(),
    email           text not null unique,
    hashed_password text not null,
    role            text not null default 'reviewer'
);

-- Email is the login identifier; index for fast authentication lookups.
create unique index if not exists idx_users_email on users (lower(email));
