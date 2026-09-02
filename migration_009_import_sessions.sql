-- ============================================================
-- MIGRAZIONE: salvataggio del progresso dell'import guidato
-- Da eseguire una sola volta nell'SQL Editor di Supabase.
-- Un solo import "in sospeso" per utente (se ne avvii uno nuovo mentre
-- uno precedente è ancora salvato, quello vecchio va prima ripreso o scartato).
-- ============================================================

create table import_sessions (
  user_id uuid primary key references profiles(id) on delete cascade,
  rows jsonb not null,
  current_index integer not null default 0,
  imported_count integer not null default 0,
  skipped jsonb not null default '[]'::jsonb,
  status_value text not null,
  updated_at timestamp with time zone default now()
);

alter table import_sessions enable row level security;
create policy "users manage own import session" on import_sessions for all using (auth.uid() = user_id);

grant select, insert, update, delete on import_sessions to authenticated;
