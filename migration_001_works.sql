-- ============================================================
-- MIGRAZIONE: separazione "opera" da "edizione"
-- Da eseguire una sola volta nell'SQL Editor di Supabase.
--
-- Cosa cambia:
-- - nuova tabella `works` = l'opera (es. "Notre-Dame de Paris"), indipendente dall'edizione
-- - `books` (le edizioni) si collega a `works` tramite work_id
-- - rating/consigliato/commento si spostano dalla singola edizione (user_books)
--   a una nuova tabella `user_work_opinions`, legata all'opera: così restano
--   UNITI anche se possiedi/leggi più edizioni dello stesso libro
-- - lo stato (letto/in lettura/wishlist/comprato) resta invece per edizione,
--   in user_books, perché ha senso che sia specifico per copia posseduta
-- ============================================================

-- 1. Nuova tabella opere
create table works (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  author text,
  created_at timestamp with time zone default now()
);

create index idx_works_title on works using gin (to_tsvector('italian', title));

alter table works enable row level security;
create policy "works are viewable by everyone" on works for select using (true);
create policy "authenticated users can insert works" on works for insert with check (auth.role() = 'authenticated');
create policy "admins can update any work" on works for update using (
  exists (select 1 from profiles where id = auth.uid() and is_admin = true)
);
create policy "admins can delete any work" on works for delete using (
  exists (select 1 from profiles where id = auth.uid() and is_admin = true)
);


-- 2. Collega le edizioni esistenti alle opere (creando un'opera per ogni
--    titolo+autore distinto già presente, e collegando le edizioni corrispondenti)
alter table books add column work_id uuid references works(id);

insert into works (title, author)
select distinct title, author from books where work_id is null;

update books b
set work_id = w.id
from works w
where b.work_id is null
  and b.title = w.title
  and (b.author = w.author or (b.author is null and w.author is null));


-- 3. Nuova tabella opinioni: una sola per utente+opera, indipendente dall'edizione
create table user_work_opinions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id) not null,
  work_id uuid references works(id) not null,
  rating integer check (rating between 1 and 5),
  recommended boolean,
  comment text,
  is_public boolean default true,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now(),
  unique (user_id, work_id)
);

alter table user_work_opinions enable row level security;
create policy "users view own or public opinions" on user_work_opinions
  for select using (auth.uid() = user_id or is_public = true);
create policy "users insert own opinions" on user_work_opinions
  for insert with check (auth.uid() = user_id);
create policy "users update own opinions" on user_work_opinions
  for update using (auth.uid() = user_id);
create policy "users delete own opinions" on user_work_opinions
  for delete using (auth.uid() = user_id);


-- 4. Rimuove rating/consigliato da user_books (si spostano su user_work_opinions)
--    ATTENZIONE: se avevi già dati di test in questi due campi, andranno persi.
alter table user_books drop column if exists rating;
alter table user_books drop column if exists recommended;


-- 5. Permessi di base per le nuove tabelle (coerente con "Automatically
--    expose new tables" disattivato nel progetto)
grant select, insert, update, delete on works to authenticated;
grant select on works to anon;
grant select, insert, update, delete on user_work_opinions to authenticated;
