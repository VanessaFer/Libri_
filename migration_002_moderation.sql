-- ============================================================
-- MIGRAZIONE: approvazione admin per i libri creati manualmente
-- Da eseguire una sola volta nell'SQL Editor di Supabase.
-- ============================================================

alter table books
  add column moderation_status text not null default 'approved'
  check (moderation_status in ('pending', 'approved', 'rejected'));

-- I libri già presenti (creati finora) restano approvati automaticamente,
-- grazie al default 'approved' qui sopra: non serve toccare i dati esistenti.
-- Da ora in poi, l'applicazione imposterà 'pending' solo per le nuove
-- creazioni manuali; i risultati da Google Books/OpenLibrary restano
-- sempre 'approved' automaticamente (fonte già affidabile).
