"""
Operazioni sul database: catalogo edizioni (books), opere (works) che le
raggruppano, associazione utente-edizione (stato), e opinioni utente-opera
(rating/consigliato/commento, condivisi tra tutte le edizioni della stessa opera).
"""

import streamlit as st
from supabase_client import get_supabase_client

# Campi della tabella `books` (edizioni)
BOOK_FIELDS = {
    "title", "author", "isbn", "cover_url", "year",
    "publisher", "synopsis", "source_api", "external_id", "work_id", "page_count",
}


@st.cache_data(ttl=300)
def get_username(user_id: str) -> str | None:
    """Recupera lo username dal profilo. Cache di 5 minuti per non interrogare il DB ad ogni rerun."""
    supabase = get_supabase_client()
    result = supabase.table("profiles").select("username").eq("id", user_id).execute()
    if result.data:
        return result.data[0]["username"]
    return None


def _clean_book_dict(book: dict) -> dict:
    return {k: v for k, v in book.items() if k in BOOK_FIELDS}


# ---------------------------------------------------------------------------
# OPERE (works)
# ---------------------------------------------------------------------------

def find_similar_works(title: str, limit: int = 5) -> list[dict]:
    """
    Cerca opere già esistenti con titolo simile (ricerca parziale,
    case-insensitive). Usata per proporre il collegamento invece di
    creare un'opera duplicata quando aggiungi una nuova edizione.
    """
    if not title or not title.strip():
        return []
    supabase = get_supabase_client()
    result = (
        supabase.table("works")
        .select("*")
        .ilike("title", f"%{title.strip()}%")
        .limit(limit)
        .execute()
    )
    return result.data


def split_authors(author_string: str | None) -> list[str]:
    """Scompone una stringa 'Hugo, Dumas' in una lista di nomi puliti."""
    if not author_string:
        return []
    return [a.strip() for a in author_string.split(",") if a.strip()]


def find_or_create_author(name: str) -> str:
    """Riusa l'autore se esiste già (stesso nome esatto), altrimenti lo crea."""
    supabase = get_supabase_client()
    name = name.strip()
    existing = supabase.table("authors").select("id").eq("name", name).execute()
    if existing.data:
        return existing.data[0]["id"]
    inserted = supabase.table("authors").insert({"name": name}).execute()
    return inserted.data[0]["id"]


def link_authors_to_work(work_id: str, author_names: list[str]):
    """Collega (creando se serve) ciascun autore all'opera. Ignora i collegamenti già esistenti."""
    supabase = get_supabase_client()
    for name in author_names:
        name = name.strip()
        if not name:
            continue
        author_id = find_or_create_author(name)
        try:
            supabase.table("work_authors").insert(
                {"work_id": work_id, "author_id": author_id}
            ).execute()
        except Exception:
            pass  # già collegato: va bene così


def get_authors_for_work(work_id: str) -> list[dict]:
    """Autori collegati a un'opera, come lista di {id, name}."""
    supabase = get_supabase_client()
    result = (
        supabase.table("work_authors")
        .select("authors(id, name)")
        .eq("work_id", work_id)
        .execute()
    )
    return [r["authors"] for r in result.data if r.get("authors")]


def create_work(title: str, author_names: list[str] = None) -> str:
    """
    Crea una nuova opera. `author_names` è una lista di nomi (uno per
    autore): vengono collegati singolarmente tramite work_authors, e il
    campo `author` testuale viene popolato come riepilogo leggibile.
    """
    supabase = get_supabase_client()
    author_names = author_names or []
    display_author = ", ".join(a.strip() for a in author_names if a.strip()) or None

    inserted = supabase.table("works").insert({
        "title": title.strip(),
        "author": display_author,
    }).execute()
    work_id = inserted.data[0]["id"]

    if author_names:
        link_authors_to_work(work_id, author_names)

    return work_id


def get_work(work_id: str) -> dict | None:
    supabase = get_supabase_client()
    result = supabase.table("works").select("*").eq("id", work_id).execute()
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# EDIZIONI (books)
# ---------------------------------------------------------------------------

def upsert_book(book: dict, work_id: str, auto_approve: bool = False) -> str:
    """
    Inserisce l'edizione nella tabella `books` se non esiste già (confronto
    per ISBN quando disponibile, altrimenti per titolo+autore esatti),
    collegandola all'opera indicata. Restituisce l'id dell'edizione.

    auto_approve=True salta la coda di approvazione (usato quando chi crea
    il libro è un admin: non avrebbe senso chiedere di approvare se stessi).
    """
    supabase = get_supabase_client()
    clean = _clean_book_dict(book)
    clean["work_id"] = work_id

    if clean.get("isbn"):
        existing = supabase.table("books").select("id").eq("isbn", clean["isbn"]).execute()
        if existing.data:
            return existing.data[0]["id"]
    else:
        # Senza ISBN, due edizioni sono "la stessa" solo se titolo, autore,
        # anno ED editore coincidono tutti - altrimenti sono edizioni diverse
        # della stessa opera (es. stesso titolo ma anno diverso).
        query = (
            supabase.table("books")
            .select("id")
            .eq("title", clean.get("title", ""))
            .eq("work_id", work_id)
        )
        for field in ("author", "year", "publisher"):
            value = clean.get(field)
            if value:
                query = query.eq(field, value)
            else:
                query = query.is_(field, "null")
        existing = query.execute()
        if existing.data:
            return existing.data[0]["id"]

    # I libri creati manualmente restano "in attesa" finché un admin non li
    # approva, a meno che chi li crea sia già admin (auto_approve=True);
    # quelli trovati via API (fonte già affidabile) sono sempre approvati subito.
    if clean.get("source_api") != "manuale" or auto_approve:
        clean["moderation_status"] = "approved"
    else:
        clean["moderation_status"] = "pending"

    inserted = supabase.table("books").insert(clean).execute()
    return inserted.data[0]["id"]


def get_book(book_id: str) -> dict | None:
    supabase = get_supabase_client()
    result = supabase.table("books").select("*").eq("id", book_id).execute()
    return result.data[0] if result.data else None


def set_book_cover(book_id: str, cover_url: str) -> bool:
    """
    Imposta la copertina di un'edizione quando manca. La policy sul
    database permette questa operazione solo se cover_url era ancora
    vuoto: non può sovrascrivere una copertina già presente.
    """
    supabase = get_supabase_client()
    try:
        supabase.table("books").update({"cover_url": cover_url}).eq("id", book_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante il salvataggio della copertina: {e}")
        return False


def set_book_page_count(book_id: str, page_count: int) -> bool:
    """
    Imposta il numero di pagine di un'edizione quando manca. La policy sul
    database permette questa operazione solo se page_count era ancora vuoto.
    """
    supabase = get_supabase_client()
    try:
        supabase.table("books").update({"page_count": page_count}).eq("id", book_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante il salvataggio del numero di pagine: {e}")
        return False


def get_editions_for_work(work_id: str, exclude_book_id: str = None) -> list[dict]:
    """Tutte le edizioni collegate alla stessa opera (per il selettore 'altre edizioni')."""
    supabase = get_supabase_client()
    query = supabase.table("books").select("*").eq("work_id", work_id)
    result = query.execute()
    editions = result.data
    if exclude_book_id:
        editions = [e for e in editions if e["id"] != exclude_book_id]
    return editions


def search_catalog_books(query: str, limit: int = 10) -> list[dict]:
    """
    Cerca libri già presenti nel catalogo condiviso (creati da te o da altri
    utenti), mostrando solo quelli approvati. Usata nella ricerca insieme a
    Google Books/OpenLibrary, per riusare edizioni già catalogate invece di
    crearne di duplicate.
    """
    if not query or not query.strip():
        return []
    supabase = get_supabase_client()
    result = (
        supabase.table("books")
        .select("*")
        .ilike("title", f"%{query.strip()}%")
        .eq("moderation_status", "approved")
        .limit(limit)
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# STATO utente-edizione (user_books)
# ---------------------------------------------------------------------------

_NOT_PROVIDED = object()


def add_to_user_library(user_id: str, book_id: str, status: str, formato=_NOT_PROVIDED, pages_read=_NOT_PROVIDED) -> bool:
    """
    Collega un'edizione all'utente con uno stato (e opzionalmente formato e
    pagine lette). Se già presente per quell'utente, aggiorna invece di
    duplicare la riga. Ogni campo opzionale viene toccato solo se
    esplicitamente passato (anche None, per azzerarlo intenzionalmente) -
    se non passato per niente, il valore esistente resta invariato.
    """
    supabase = get_supabase_client()
    payload = {"user_id": user_id, "book_id": book_id, "status": status}
    if formato is not _NOT_PROVIDED:
        payload["formato"] = formato
    if pages_read is not _NOT_PROVIDED:
        payload["pages_read"] = pages_read
    try:
        supabase.table("user_books").upsert(
            payload, on_conflict="user_id,book_id",
        ).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante il salvataggio dello stato: {e}")
        return False


def get_user_status_for_book(user_id: str, book_id: str) -> str | None:
    supabase = get_supabase_client()
    result = (
        supabase.table("user_books")
        .select("status")
        .eq("user_id", user_id)
        .eq("book_id", book_id)
        .execute()
    )
    return result.data[0]["status"] if result.data else None


def get_user_book_entry(user_id: str, book_id: str) -> dict | None:
    """Riga completa (stato + formato + pagine lette) per questa edizione e questo utente, se esiste."""
    supabase = get_supabase_client()
    result = (
        supabase.table("user_books")
        .select("status, formato, pages_read")
        .eq("user_id", user_id)
        .eq("book_id", book_id)
        .execute()
    )
    return result.data[0] if result.data else None


def get_user_books(user_id: str, status: str = None) -> list[dict]:
    """Libreria dell'utente, con i dati dell'edizione già uniti (join), in ordine di inserimento."""
    supabase = get_supabase_client()
    query = (
        supabase.table("user_books")
        .select("*, books(*)")
        .eq("user_id", user_id)
        .order("created_at")
    )
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return result.data


# ---------------------------------------------------------------------------
# OPINIONI utente-opera (user_work_opinions): rating, consigliato, commento
# ---------------------------------------------------------------------------

def get_user_opinion(user_id: str, work_id: str) -> dict | None:
    """L'opinione dell'utente su un'opera, se esiste già (per pre-compilare il form)."""
    supabase = get_supabase_client()
    result = (
        supabase.table("user_work_opinions")
        .select("*")
        .eq("user_id", user_id)
        .eq("work_id", work_id)
        .execute()
    )
    return result.data[0] if result.data else None


def save_opinion(user_id: str, work_id: str, rating=None, recommended=None, comment=None, is_public=True) -> bool:
    """
    Salva (o aggiorna) l'opinione dell'utente sull'opera. Un solo record
    per utente+opera: se leggi due edizioni dello stesso libro, l'opinione
    resta unica invece di sdoppiarsi.
    """
    supabase = get_supabase_client()
    payload = {
        "user_id": user_id,
        "work_id": work_id,
        "rating": rating,
        "recommended": recommended,
        "comment": comment,
        "is_public": is_public,
    }
    try:
        supabase.table("user_work_opinions").upsert(
            payload, on_conflict="user_id,work_id"
        ).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante il salvataggio dell'opinione: {e}")
        return False


def get_average_rating(work_id: str) -> tuple[float, int] | None:
    """
    Media delle valutazioni pubbliche per un'opera. Restituisce
    (media, numero_di_valutazioni) oppure None se non c'è nessuna valutazione.
    """
    supabase = get_supabase_client()
    result = (
        supabase.table("user_work_opinions")
        .select("rating")
        .eq("work_id", work_id)
        .eq("is_public", True)
        .not_.is_("rating", "null")
        .execute()
    )
    ratings = [r["rating"] for r in result.data if r.get("rating") is not None]
    if not ratings:
        return None
    return (sum(ratings) / len(ratings), len(ratings))


# ---------------------------------------------------------------------------
# ANNOTAZIONI (notes): citazioni e commenti legati a un passaggio specifico
# di un'EDIZIONE (il numero di pagina ha senso solo per l'edizione precisa)
# ---------------------------------------------------------------------------

def create_note(user_id: str, book_id: str, quote_text: str = None, page_or_location: str = None,
                 comment: str = None, is_public: bool = False) -> bool:
    supabase = get_supabase_client()
    try:
        supabase.table("notes").insert({
            "user_id": user_id,
            "book_id": book_id,
            "quote_text": quote_text or None,
            "page_or_location": page_or_location or None,
            "comment": comment or None,
            "is_public": is_public,
        }).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante il salvataggio dell'annotazione: {e}")
        return False


def get_notes_for_book(user_id: str, book_id: str) -> list[dict]:
    """Le proprie annotazioni per questa edizione (le altre restano private finché non è costruita la parte social)."""
    supabase = get_supabase_client()
    result = (
        supabase.table("notes")
        .select("*")
        .eq("book_id", book_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


def delete_note(note_id: str) -> bool:
    supabase = get_supabase_client()
    try:
        supabase.table("notes").delete().eq("id", note_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante l'eliminazione: {e}")
        return False


# ---------------------------------------------------------------------------
# TAG (scaffali personali) collegati alle OPERE
# ---------------------------------------------------------------------------

def get_user_tags(user_id: str) -> list[dict]:
    """Tutti i tag creati da questo utente, in ordine alfabetico."""
    supabase = get_supabase_client()
    result = supabase.table("tags").select("*").eq("user_id", user_id).order("name").execute()
    return result.data


def find_or_create_tag(user_id: str, name: str) -> str:
    supabase = get_supabase_client()
    name = name.strip()
    existing = supabase.table("tags").select("id").eq("user_id", user_id).eq("name", name).execute()
    if existing.data:
        return existing.data[0]["id"]
    inserted = supabase.table("tags").insert({"user_id": user_id, "name": name}).execute()
    return inserted.data[0]["id"]


def get_tags_for_work(user_id: str, work_id: str) -> list[dict]:
    """I tag (di questo utente) assegnati a un'opera."""
    supabase = get_supabase_client()
    result = (
        supabase.table("work_tags")
        .select("tags(id, name)")
        .eq("user_id", user_id)
        .eq("work_id", work_id)
        .execute()
    )
    return [r["tags"] for r in result.data if r.get("tags")]


def add_tag_to_work(user_id: str, work_id: str, tag_id: str = None, tag_name: str = None) -> bool:
    """Collega un tag a un'opera, creandolo se serve (passando tag_name invece di tag_id)."""
    if not tag_id:
        tag_id = find_or_create_tag(user_id, tag_name)
    supabase = get_supabase_client()
    try:
        supabase.table("work_tags").insert(
            {"user_id": user_id, "work_id": work_id, "tag_id": tag_id}
        ).execute()
        return True
    except Exception:
        return False  # già collegato: va bene così


def remove_tag_from_work(user_id: str, work_id: str, tag_id: str) -> bool:
    supabase = get_supabase_client()
    try:
        supabase.table("work_tags").delete().eq("user_id", user_id).eq("work_id", work_id).eq("tag_id", tag_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante la rimozione del tag: {e}")
        return False


def get_user_work_tags_map(user_id: str) -> dict:
    """
    Mappa work_id -> insieme di tag_id, per filtrare velocemente 'La mia
    libreria' per tag senza fare una query per ogni libro.
    """
    supabase = get_supabase_client()
    result = supabase.table("work_tags").select("work_id, tag_id").eq("user_id", user_id).execute()
    mapping = {}
    for row in result.data:
        mapping.setdefault(row["work_id"], set()).add(row["tag_id"])
    return mapping


def import_wizard_save_candidate(book: dict, user_id: str, status: str, auto_approve: bool = False) -> dict:
    """
    Salva un candidato scelto durante l'import guidato: collega
    automaticamente a un'opera esistente se il titolo corrisponde
    esattamente, altrimenti ne crea una nuova - senza chiedere conferma,
    per non interrompere il flusso a coda su centinaia di libri.
    """
    title = book.get("title") or ""
    author_names = book.get("authors_list") or split_authors(book.get("author"))

    similar = find_similar_works(title)
    exact_match = next(
        (w for w in similar if (w.get("title") or "").strip().lower() == title.strip().lower()),
        None,
    )
    if exact_match:
        work_id = exact_match["id"]
        if author_names:
            link_authors_to_work(work_id, author_names)
    else:
        work_id = create_work(title, author_names)

    book_id = upsert_book(book, work_id, auto_approve)
    add_to_user_library(user_id, book_id, status)
    return {"book_id": book_id, "work_id": work_id}


def save_import_progress(user_id: str, rows: list, index: int, imported: int, skipped: list, status_value: str) -> bool:
    """Salva (o aggiorna) il punto in cui è arrivato l'import guidato, per poterlo riprendere dopo."""
    supabase = get_supabase_client()
    try:
        supabase.table("import_sessions").upsert({
            "user_id": user_id,
            "rows": rows,
            "current_index": index,
            "imported_count": imported,
            "skipped": skipped,
            "status_value": status_value,
        }, on_conflict="user_id").execute()
        return True
    except Exception as e:
        st.error(f"Errore nel salvataggio del progresso: {e}")
        return False


def load_import_progress(user_id: str) -> dict | None:
    """Recupera un import guidato salvato a metà, se esiste."""
    supabase = get_supabase_client()
    result = supabase.table("import_sessions").select("*").eq("user_id", user_id).execute()
    return result.data[0] if result.data else None


def clear_import_progress(user_id: str) -> bool:
    """Cancella l'import salvato (usato a import completato, o se lo scarti)."""
    supabase = get_supabase_client()
    try:
        supabase.table("import_sessions").delete().eq("user_id", user_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore nella cancellazione del progresso salvato: {e}")
        return False


# ---------------------------------------------------------------------------
# LINK UTILI (personali): librerie, biblioteche, case editrici, ecc.
# ---------------------------------------------------------------------------

def get_user_links(user_id: str) -> list[dict]:
    supabase = get_supabase_client()
    result = (
        supabase.table("useful_links")
        .select("*")
        .eq("user_id", user_id)
        .order("category")
        .order("name")
        .execute()
    )
    return result.data


def add_link(user_id: str, category: str, name: str, url: str, logo_url: str = None) -> bool:
    supabase = get_supabase_client()
    try:
        supabase.table("useful_links").insert({
            "user_id": user_id,
            "category": category.strip(),
            "name": name.strip(),
            "url": url.strip(),
            "logo_url": logo_url,
        }).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante il salvataggio del link: {e}")
        return False


def update_link(link_id: str, name: str = None, url: str = None, logo_url: str = None) -> bool:
    supabase = get_supabase_client()
    updates = {}
    if name is not None:
        updates["name"] = name.strip()
    if url is not None:
        updates["url"] = url.strip()
    if logo_url is not None:
        updates["logo_url"] = logo_url.strip() or None
    if not updates:
        return True
    try:
        supabase.table("useful_links").update(updates).eq("id", link_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante la modifica del link: {e}")
        return False


def delete_link(link_id: str) -> bool:
    supabase = get_supabase_client()
    try:
        supabase.table("useful_links").delete().eq("id", link_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante l'eliminazione del link: {e}")
        return False


def get_catalog_publishers(user_id: str) -> list[str]:
    """Editori distinti tra i libri che l'utente ha nella propria libreria."""
    supabase = get_supabase_client()
    result = (
        supabase.table("user_books")
        .select("books(publisher)")
        .eq("user_id", user_id)
        .execute()
    )
    publishers = {
        (r.get("books") or {}).get("publisher")
        for r in result.data
        if (r.get("books") or {}).get("publisher")
    }
    return sorted(publishers)


def rename_tag(tag_id: str, new_name: str) -> bool:
    supabase = get_supabase_client()
    try:
        supabase.table("tags").update({"name": new_name.strip()}).eq("id", tag_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante la rinomina del tag: {e}")
        return False


def delete_tag(tag_id: str) -> bool:
    """Elimina il tag; i collegamenti alle opere (work_tags) vengono rimossi in automatico."""
    supabase = get_supabase_client()
    try:
        supabase.table("tags").delete().eq("id", tag_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore durante l'eliminazione del tag: {e}")
        return False


# ---------------------------------------------------------------------------
# Valori già esistenti nel catalogo, per i suggerimenti nel form manuale
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def get_existing_titles(limit: int = 500) -> list[str]:
    supabase = get_supabase_client()
    result = supabase.table("works").select("title").order("title").limit(limit).execute()
    return sorted({r["title"] for r in result.data if r.get("title")})


@st.cache_data(ttl=60)
def get_existing_authors(limit: int = 1000) -> list[str]:
    supabase = get_supabase_client()
    result = supabase.table("authors").select("name").order("name").limit(limit).execute()
    return sorted({r["name"] for r in result.data if r.get("name")})


@st.cache_data(ttl=60)
def get_existing_publishers(limit: int = 500) -> list[str]:
    supabase = get_supabase_client()
    result = supabase.table("books").select("publisher").not_.is_("publisher", "null").limit(limit).execute()
    return sorted({r["publisher"] for r in result.data if r.get("publisher")})


# ---------------------------------------------------------------------------
# Funzione di comodo: salva edizione + stato in un colpo solo, dato un work_id già risolto
# ---------------------------------------------------------------------------

def save_book_with_status(
    book: dict, work_id: str, user_id: str, status: str, auto_approve: bool = False, formato=_NOT_PROVIDED
) -> str | None:
    """Crea/riusa l'edizione (collegata al work_id dato) e la associa all'utente. Restituisce il book_id."""
    try:
        book_id = upsert_book(book, work_id, auto_approve)
        ok = add_to_user_library(user_id, book_id, status, formato=formato)
        return book_id if ok else None
    except Exception as e:
        st.error(f"Errore durante il salvataggio del libro: {e}")
        return None
