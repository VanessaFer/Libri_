-- ============================================================
-- SCHEMA WEBAPP LIBRI
-- Da eseguire in Supabase: Project > SQL Editor > New query > incolla tutto > Run
-- ============================================================

-- PROFILES
-- Collegata a auth.users (gestita automaticamente da Supabase Auth)
create table profiles (
  id uuid references auth.users(id) on delete cascade primary key,
  username text unique not null,
  bio text,
  is_admin boolean default false,
  created_at timestamp with time zone default now()
);

-- Trigger: crea automaticamente un profilo quando qualcuno si registra
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, username)
  values (new.id, coalesce(new.raw_user_meta_data->>'username', split_part(new.email, '@', 1)));
  return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();


-- WORKS
-- L'opera in sé (es. "Notre-Dame de Paris"), indipendente dall'edizione.
-- Serve a raggruppare rating/commenti quando esistono più edizioni dello
-- stesso libro, invece di disperderli su righe diverse.
create table works (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  author text,
  created_at timestamp with time zone default now()
);

create index idx_works_title on works using gin (to_tsvector('italian', title));


-- AUTHORS
-- Un autore = una riga propria, collegata alle opere tramite work_authors.
-- Il campo `author` testuale su works/books resta come comodo riepilogo,
-- ma la fonte "vera" per singolo autore è questa tabella.
create table authors (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  created_at timestamp with time zone default now()
);

create table work_authors (
  work_id uuid references works(id) on delete cascade not null,
  author_id uuid references authors(id) on delete cascade not null,
  primary key (work_id, author_id)
);


-- BOOKS
-- Catalogo condiviso delle EDIZIONI: un'edizione esiste una sola volta,
-- indipendentemente da chi la aggiunge. Più edizioni della stessa opera
-- condividono lo stesso work_id.
create table books (
  id uuid primary key default gen_random_uuid(),
  work_id uuid references works(id),
  title text not null,
  author text,
  isbn text,
  cover_url text,
  year text,
  publisher text,
  page_count integer check (page_count > 0),
  synopsis text,
  page_count integer check (page_count is null or page_count > 0),
  source_api text,          -- 'google_books' oppure 'openlibrary'
  external_id text,         -- id del libro nell'API sorgente
  moderation_status text not null default 'approved'
    check (moderation_status in ('pending', 'approved', 'rejected')),
    -- 'pending' per le creazioni manuali in attesa di conferma admin;
    -- 'approved' in automatico per i risultati da Google Books/OpenLibrary
  created_at timestamp with time zone default now(),
  unique (isbn)              -- evita duplicati quando l'ISBN è noto
);

create index idx_books_title on books using gin (to_tsvector('italian', title));


-- USER_BOOKS
-- Relazione utente-edizione: solo lo stato di possesso/lettura, che ha
-- senso specifico per singola edizione (es. possiedi l'edizione Einaudi,
-- desideri quella Adelphi).
create table user_books (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id) not null,
  book_id uuid references books(id) not null,
  status text not null check (status in ('wishlist', 'comprato_non_letto', 'in_lettura', 'letto')),
  formato text check (formato in ('cartaceo', 'digitale', 'audiolibro')),
  pages_read integer check (pages_read is null or pages_read >= 0),
  pages_read integer check (pages_read >= 0),
  start_date date,
  end_date date,
  created_at timestamp with time zone default now(),
  unique (user_id, book_id)
);

create index idx_user_books_user on user_books (user_id);
create index idx_user_books_status on user_books (user_id, status);


-- USER_WORK_OPINIONS
-- L'opinione dell'utente sull'OPERA (non sulla singola edizione): rating,
-- consigliato sì/no, commento. Una sola per utente+opera, così restano
-- unite anche leggendo più edizioni dello stesso libro.
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


-- NOTES
-- Note legate a passaggi specifici, non solo recensione generale
create table notes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id) not null,
  book_id uuid references books(id) not null,
  page_or_location text,
  quote_text text,
  comment text,
  is_public boolean default false,
  created_at timestamp with time zone default now()
);

create index idx_notes_book on notes (book_id);


-- TAGS (personali, per utente)
create table tags (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id) not null,
  name text not null,
  unique (user_id, name)
);

-- WORK_TAGS: collega i tag all'OPERA (non alla singola edizione), coerente
-- con la scelta fatta per rating/opinioni.
create table work_tags (
  user_id uuid references profiles(id) not null,
  work_id uuid references works(id) not null,
  tag_id uuid references tags(id) not null,
  created_at timestamp with time zone default now(),
  primary key (user_id, work_id, tag_id)
);


-- GROUPS (bookclub)
create table groups (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  description text,
  created_by uuid references profiles(id),
  is_private boolean default true,
  created_at timestamp with time zone default now()
);

create table group_members (
  group_id uuid references groups(id) not null,
  user_id uuid references profiles(id) not null,
  joined_at timestamp with time zone default now(),
  primary key (group_id, user_id)
);


-- FOLLOWS (con filtro per tag/scaffale)
create table follows (
  id uuid primary key default gen_random_uuid(),
  follower_id uuid references profiles(id) not null,
  followed_id uuid references profiles(id) not null,
  tag_id uuid references tags(id),   -- null = segue tutto
  created_at timestamp with time zone default now(),
  unique (follower_id, followed_id, tag_id)
);


-- WISHLIST_ALERTS (parte Vinted/Libraccio)
create table wishlist_alerts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id) not null,
  book_id uuid references books(id) not null,
  found_listing_url text,
  found_price text,
  source text,               -- 'vinted' oppure 'libraccio'
  notified_at timestamp with time zone default now()
);


-- ============================================================
-- ROW LEVEL SECURITY (fondamentale: ogni utente vede/modifica solo i propri dati)
-- ============================================================

alter table profiles enable row level security;
alter table user_books enable row level security;
alter table notes enable row level security;
alter table tags enable row level security;
alter table work_tags enable row level security;
alter table follows enable row level security;
alter table wishlist_alerts enable row level security;
alter table books enable row level security;
alter table works enable row level security;
alter table authors enable row level security;
alter table work_authors enable row level security;
alter table user_work_opinions enable row level security;

-- profiles: tutti possono leggere i profili pubblici, ognuno modifica solo il proprio
create policy "profiles are viewable by everyone" on profiles for select using (true);
create policy "users can update own profile" on profiles for update using (auth.uid() = id);

-- books: catalogo condiviso, tutti possono leggere e inserire nuovi libri
create policy "books are viewable by everyone" on books for select using (true);
create policy "authenticated users can insert books" on books for insert with check (auth.role() = 'authenticated');

-- solo gli admin possono modificare/eliminare libri dal catalogo condiviso
-- (utile per unire duplicati o correggere dati sbagliati)
create policy "admins can update any book" on books for update using (
  exists (select 1 from profiles where id = auth.uid() and is_admin = true)
);
create policy "admins can delete any book" on books for delete using (
  exists (select 1 from profiles where id = auth.uid() and is_admin = true)
);

-- eccezioni mirate: chiunque autenticato può compilare un dato mancante
-- (non sovrascrivere uno già presente, quello resta riservato agli admin)
create policy "authenticated users can add missing cover" on books
  for update using (cover_url is null and auth.role() = 'authenticated');
create policy "authenticated users can add missing page_count" on books
  for update using (page_count is null and auth.role() = 'authenticated');

-- user_books: solo il proprietario vede/modifica i propri libri
create policy "users manage own user_books" on user_books for all using (auth.uid() = user_id);

-- notes: proprietario vede sempre le proprie; le altre solo se is_public = true
create policy "users view own notes" on notes for select using (auth.uid() = user_id or is_public = true);
create policy "users manage own notes" on notes for insert with check (auth.uid() = user_id);
create policy "users update own notes" on notes for update using (auth.uid() = user_id);
create policy "users delete own notes" on notes for delete using (auth.uid() = user_id);

-- tags e work_tags: solo il proprietario
create policy "users manage own tags" on tags for all using (auth.uid() = user_id);
create policy "users manage own work_tags" on work_tags for all using (auth.uid() = user_id);

-- follows: chiunque autenticato può vedere/creare i propri follow
create policy "users manage own follows" on follows for all using (auth.uid() = follower_id);

-- wishlist_alerts: solo il proprietario
create policy "users manage own alerts" on wishlist_alerts for all using (auth.uid() = user_id);

-- works: tutti leggono e creano, solo gli admin modificano/eliminano (unione duplicati)
create policy "works are viewable by everyone" on works for select using (true);
create policy "authenticated users can insert works" on works for insert with check (auth.role() = 'authenticated');
create policy "admins can update any work" on works for update using (
  exists (select 1 from profiles where id = auth.uid() and is_admin = true)
);
create policy "admins can delete any work" on works for delete using (
  exists (select 1 from profiles where id = auth.uid() and is_admin = true)
);

-- authors: tutti leggono e creano, solo gli admin modificano/eliminano (unione duplicati)
create policy "authors are viewable by everyone" on authors for select using (true);
create policy "authenticated users can insert authors" on authors for insert with check (auth.role() = 'authenticated');
create policy "admins can update any author" on authors for update using (
  exists (select 1 from profiles where id = auth.uid() and is_admin = true)
);
create policy "admins can delete any author" on authors for delete using (
  exists (select 1 from profiles where id = auth.uid() and is_admin = true)
);

-- work_authors: chiunque autenticato può collegare/scollegare autori a un'opera
create policy "work_authors are viewable by everyone" on work_authors for select using (true);
create policy "authenticated users can link authors" on work_authors for insert with check (auth.role() = 'authenticated');
create policy "authenticated users can unlink authors" on work_authors for delete using (auth.role() = 'authenticated');

-- user_work_opinions: proprietario vede sempre le proprie; le altre solo se is_public = true
create policy "users view own or public opinions" on user_work_opinions
  for select using (auth.uid() = user_id or is_public = true);
create policy "users insert own opinions" on user_work_opinions
  for insert with check (auth.uid() = user_id);
create policy "users update own opinions" on user_work_opinions
  for update using (auth.uid() = user_id);
create policy "users delete own opinions" on user_work_opinions
  for delete using (auth.uid() = user_id);


-- ============================================================
-- PERMESSI DI BASE (necessari perché "Automatically expose new tables"
-- è disattivato nel progetto - le policy RLS sopra filtrano le righe,
-- ma serve comunque il permesso di base per interrogare le tabelle)
-- ============================================================

grant usage on schema public to authenticated, anon;
grant select, insert, update, delete on all tables in schema public to authenticated;
grant select on all tables in schema public to anon;

-- così anche le tabelle create in futuro erediteranno questi permessi
alter default privileges in schema public grant select, insert, update, delete on tables to authenticated;
alter default privileges in schema public grant select on tables to anon;
