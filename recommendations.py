"""
Motore dei consigli personalizzati ("Esplora").

Logica generale, per due modalità:
- "amati": semi presi dalle opere valutate con rating >= 4 (user_work_opinions)
- "letti": semi presi da tutti i libri con status 'letto' (user_books)

Per i work_id raccolti, si guarda quali tag e autori ricorrono più spesso,
e si usano i nomi più frequenti come query verso find_book_candidates
(la stessa funzione usata da "Cerca e aggiungi", che interroga Google
Books + SBN + OpenLibrary). I risultati vengono ripuliti dai libri già
presenti nello scaffale dell'utente (per ISBN, o per coppia titolo+autore
quando l'ISBN non è disponibile/coincide).

Il calcolo viene rifatto ogni volta che la sezione viene aperta: nessuna
cache per ora, semplice da capire e sufficiente per un uso personale.
"""

from collections import Counter

import streamlit as st

from book_matching import find_book_candidates
from supabase_client import get_supabase_client

TOP_TAGS_COUNT = 3
TOP_AUTHORS_COUNT = 3
RESULTS_PER_QUERY = 5
MAX_TOTAL_RESULTS = 15
RATING_THRESHOLD = 4


def _seed_work_ids_from_ratings(user_id: str, min_rating: int) -> list[str]:
    supabase = get_supabase_client()
    resp = (
        supabase.table("user_work_opinions")
        .select("work_id")
        .eq("user_id", user_id)
        .gte("rating", min_rating)
        .execute()
    )
    return list({row["work_id"] for row in resp.data if row.get("work_id")})


def _seed_work_ids_from_read_status(user_id: str) -> list[str]:
    supabase = get_supabase_client()
    resp = (
        supabase.table("user_books")
        .select("books(work_id)")
        .eq("user_id", user_id)
        .eq("status", "letto")
        .execute()
    )
    work_ids = set()
    for row in resp.data:
        book = row.get("books")
        if book and book.get("work_id"):
            work_ids.add(book["work_id"])
    return list(work_ids)


def _top_tag_names(user_id: str, work_ids: list[str], top_n: int) -> list[str]:
    if not work_ids:
        return []
    supabase = get_supabase_client()
    resp = (
        supabase.table("work_tags")
        .select("tags(name)")
        .eq("user_id", user_id)
        .in_("work_id", work_ids)
        .execute()
    )
    counter = Counter()
    for row in resp.data:
        tag = row.get("tags")
        if tag and tag.get("name"):
            counter[tag["name"]] += 1
    return [name for name, _ in counter.most_common(top_n)]


def _top_author_names(work_ids: list[str], top_n: int) -> list[str]:
    if not work_ids:
        return []
    supabase = get_supabase_client()
    resp = (
        supabase.table("work_authors")
        .select("authors(name)")
        .in_("work_id", work_ids)
        .execute()
    )
    counter = Counter()
    for row in resp.data:
        author = row.get("authors")
        if author and author.get("name"):
            counter[author["name"]] += 1
    return [name for name, _ in counter.most_common(top_n)]


def _owned_keys(user_id: str) -> tuple[set[str], set[tuple[str, str]]]:
    """Restituisce (isbn già posseduti, coppie titolo+autore già possedute)."""
    supabase = get_supabase_client()
    resp = (
        supabase.table("user_books")
        .select("books(isbn, title, author)")
        .eq("user_id", user_id)
        .execute()
    )
    isbns = set()
    title_author_pairs = set()
    for row in resp.data:
        book = row.get("books")
        if not book:
            continue
        if book.get("isbn"):
            isbns.add(book["isbn"])
        title = (book.get("title") or "").strip().lower()
        author = (book.get("author") or "").strip().lower()
        if title:
            title_author_pairs.add((title, author))
    return isbns, title_author_pairs


@st.cache_data(ttl=12 * 60 * 60, show_spinner=False)
def get_recommendations(user_id: str, mode: str) -> list[dict]:
    """
    mode: "amati" (rating >= 4) oppure "letti" (tutti i libri letti).
    Restituisce una lista di libri candidati (stesso formato di
    find_book_candidates), già filtrata da ciò che l'utente ha già
    nello scaffale, con un campo aggiuntivo "matched_on" che indica
    il tag/autore che ha originato il suggerimento.
    """
    if mode == "amati":
        work_ids = _seed_work_ids_from_ratings(user_id, RATING_THRESHOLD)
    else:
        work_ids = _seed_work_ids_from_read_status(user_id)

    if not work_ids:
        return []

    top_authors = _top_author_names(work_ids, TOP_AUTHORS_COUNT)
    top_tags = _top_tag_names(user_id, work_ids, TOP_TAGS_COUNT)
    queries = [(q, "autore") for q in top_authors] + [(q, "tag") for q in top_tags]

    if not queries:
        return []

    owned_isbns, owned_title_author = _owned_keys(user_id)

    results = []
    seen = set()
    for query_text, query_type in queries:
        candidates = find_book_candidates(query_text, max_results=RESULTS_PER_QUERY)
        for book in candidates:
            isbn = book.get("isbn")
            title = (book.get("title") or "").strip().lower()
            author = (book.get("author") or "").strip().lower()

            if isbn and isbn in owned_isbns:
                continue
            if (title, author) in owned_title_author:
                continue

            dedup_key = isbn or (title, author)
            if not title or dedup_key in seen:
                continue
            seen.add(dedup_key)

            book["matched_on"] = query_text
            book["matched_on_type"] = query_type
            results.append(book)

        if len(results) >= MAX_TOTAL_RESULTS:
            break

    return results[:MAX_TOTAL_RESULTS]
