"""
Funzioni riservate all'amministratore: statistiche generali, elenco utenti,
gestione del catalogo libri condiviso (modifica/eliminazione, utile per
unire duplicati quando più persone useranno la webapp).
"""

import streamlit as st
from supabase_client import get_supabase_client


def is_admin(user_id: str) -> bool:
    """Controlla se l'utente collegato ha il flag is_admin=true sul profilo."""
    supabase = get_supabase_client()
    result = supabase.table("profiles").select("is_admin").eq("id", user_id).execute()
    if not result.data:
        return False
    return bool(result.data[0].get("is_admin"))


def get_stats() -> dict:
    """Statistiche aggregate di base sul sistema."""
    supabase = get_supabase_client()
    users_count = len(supabase.table("profiles").select("id").execute().data)
    books_count = len(supabase.table("books").select("id").execute().data)
    user_books_count = len(supabase.table("user_books").select("id").execute().data)
    return {
        "utenti": users_count,
        "libri nel catalogo": books_count,
        "libri in librerie personali": user_books_count,
    }


def get_all_profiles() -> list[dict]:
    supabase = get_supabase_client()
    result = supabase.table("profiles").select("*").order("created_at", desc=True).execute()
    return result.data


def get_all_books(search: str = "") -> list[dict]:
    """Elenco libri nel catalogo condiviso, con filtro opzionale per titolo."""
    supabase = get_supabase_client()
    query = supabase.table("books").select("*").order("title")
    if search:
        query = query.ilike("title", f"%{search}%")
    result = query.execute()
    return result.data


def get_pending_books() -> list[dict]:
    """Libri creati manualmente in attesa di approvazione."""
    supabase = get_supabase_client()
    result = (
        supabase.table("books")
        .select("*")
        .eq("moderation_status", "pending")
        .order("created_at")
        .execute()
    )
    return result.data


def approve_book(book_id: str) -> bool:
    return update_book(book_id, {"moderation_status": "approved"})


def reject_book(book_id: str) -> bool:
    """
    Segna il libro come rifiutato: resta nel database (chi l'ha creato lo
    mantiene comunque nella propria libreria personale) ma non comparirà
    più nella ricerca del catalogo condiviso.
    """
    return update_book(book_id, {"moderation_status": "rejected"})


def update_book(book_id: str, updates: dict) -> bool:
    supabase = get_supabase_client()
    try:
        supabase.table("books").update(updates).eq("id", book_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante l'aggiornamento: {e}")
        return False


def delete_book(book_id: str) -> bool:
    """
    Elimina un libro dal catalogo condiviso. Attenzione: fallisce se il
    libro è ancora collegato a delle librerie utente (user_books), per
    evitare di rompere riferimenti - va prima rimosso dalle librerie
    interessate, o ri-collegato a un libro "gemello" in caso di merge.
    """
    supabase = get_supabase_client()
    try:
        supabase.table("books").delete().eq("id", book_id).execute()
        return True
    except Exception as e:
        st.error(f"Impossibile eliminare: probabilmente il libro è ancora in una libreria utente. ({e})")
        return False
