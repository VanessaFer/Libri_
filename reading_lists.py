"""
Liste di lettura curate ("Esplora" → Liste): elenchi statici esterni
(es. "1001 libri da leggere nella vita") con lo stato di lettura calcolato
automaticamente, confrontando titolo (e autore, quando serve come conferma)
con i libri che l'utente ha segnato come "letto" nella propria libreria.

Le liste sono contenuto condiviso/statico (tabelle reading_lists e
reading_list_items, popolate una tantum via migration): non c'è nulla da
scrivere qui per gestirne la creazione, solo la lettura e il matching.
"""

from supabase_client import get_supabase_client


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def get_reading_lists() -> list[dict]:
    supabase = get_supabase_client()
    resp = supabase.table("reading_lists").select("*").order("name").execute()
    return resp.data


def get_reading_list_items(list_id: str) -> list[dict]:
    supabase = get_supabase_client()
    resp = (
        supabase.table("reading_list_items")
        .select("*")
        .eq("list_id", list_id)
        .order("position")
        .execute()
    )
    return resp.data


def _get_read_title_author_pairs(user_id: str) -> set[tuple[str, str]]:
    """Titolo+autore (normalizzati) di tutti i libri che l'utente ha letto."""
    supabase = get_supabase_client()
    resp = (
        supabase.table("user_books")
        .select("books(title, author)")
        .eq("user_id", user_id)
        .eq("status", "letto")
        .execute()
    )
    pairs = set()
    for row in resp.data:
        book = row.get("books")
        if not book:
            continue
        title = _normalize(book.get("title"))
        author = _normalize(book.get("author"))
        if title:
            pairs.add((title, author))
    return pairs


def get_reading_list_progress(user_id: str, list_id: str, items: list[dict] | None = None) -> dict:
    """
    Restituisce {"items": [...con campo 'read' aggiunto...], "read_count": n, "total": n}.
    Il match è per titolo esatto (normalizzato); se il titolo coincide, l'autore
    viene controllato in modo tollerante (basta che uno dei due nomi contenga
    l'altro), per non perdere corrispondenze per piccole differenze di formato
    (es. iniziali puntate, ordine nome/cognome).
    """
    if items is None:
        items = get_reading_list_items(list_id)

    read_pairs = _get_read_title_author_pairs(user_id)
    read_titles = {t for t, _ in read_pairs}

    enriched = []
    read_count = 0
    for item in items:
        title = _normalize(item.get("title"))
        author = _normalize(item.get("author"))
        is_read = False
        if title in read_titles:
            for read_title, read_author in read_pairs:
                if read_title != title:
                    continue
                if not author or not read_author or author in read_author or read_author in author:
                    is_read = True
                    break
        enriched.append({**item, "read": is_read})
        if is_read:
            read_count += 1

    return {"items": enriched, "read_count": read_count, "total": len(items)}
