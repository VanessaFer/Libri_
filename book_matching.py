"""
Motore di matching libri.

Prende un testo grezzo (es. "Notre-Dame de Paris, Victor Hugo" oppure solo
un titolo) e restituisce una lista di libri candidati, cercando prima su
Google Books e poi, se serve, su OpenLibrary.

Pensato per essere riutilizzato da più "sorgenti" di input:
- import da Excel (una riga = una query)
- futura estrazione da foto (OCR/vision -> stesso formato testo)
- ricerca manuale nella webapp
"""

import requests
import time
import os
import re
import base64
from dotenv import load_dotenv

load_dotenv()


GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
OPENLIBRARY_URL = "https://openlibrary.org/search.json"
SBN_BASE_URL = "https://api.iccu.sbn.it/sbn/1.0.0"
SBN_TOKEN_URL = "https://api.iccu.sbn.it/oauth2/token"

# Piccolo ritardo tra le richieste quando si fa un import massivo,
# per non saturare le API in caso di più utenti che importano insieme.
REQUEST_DELAY_SECONDS = 0.3

# Il token OAuth2 di SBN dura un'ora: lo teniamo in cache qui invece di
# richiederne uno nuovo a ogni ricerca.
_sbn_token_cache = {"token": None, "expires_at": 0}


def _search_google_books(query: str, max_results: int = 5) -> list[dict]:
    """Cerca su Google Books e normalizza i risultati nel formato comune."""
    try:
        resp = requests.get(
            GOOGLE_BOOKS_URL,
            params={"q": query, "maxResults": max_results, "country": "IT"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return []

    results = []
    for item in data.get("items", []):
        info = item.get("volumeInfo", {})
        isbn = None
        for identifier in info.get("industryIdentifiers", []):
            if identifier.get("type") in ("ISBN_13", "ISBN_10"):
                isbn = identifier.get("identifier")
                if identifier.get("type") == "ISBN_13":
                    break  # preferiamo sempre ISBN_13 se disponibile

        results.append({
            "title": info.get("title"),
            "author": ", ".join(info.get("authors", [])) or None,
            "authors_list": info.get("authors", []),
            "isbn": isbn,
            "cover_url": info.get("imageLinks", {}).get("thumbnail"),
            "year": info.get("publishedDate"),
            "publisher": info.get("publisher"),
            "synopsis": info.get("description"),
            "page_count": info.get("pageCount") or None,
            "source_api": "google_books",
            "external_id": item.get("id"),
        })
    return results


def _search_openlibrary(query: str, max_results: int = 5) -> list[dict]:
    """Cerca su OpenLibrary e normalizza i risultati nel formato comune."""
    try:
        resp = requests.get(
            OPENLIBRARY_URL,
            params={"q": query, "limit": max_results},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return []

    results = []
    for doc in data.get("docs", []):
        isbn_list = doc.get("isbn", [])
        cover_id = doc.get("cover_i")
        publishers = doc.get("publisher", [])

        results.append({
            "title": doc.get("title"),
            "author": ", ".join(doc.get("author_name", [])) or None,
            "authors_list": doc.get("author_name", []),
            "isbn": isbn_list[0] if isbn_list else None,
            "cover_url": (
                f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
                if cover_id else None
            ),
            "year": str(doc.get("first_publish_year") or "") or None,
            "publisher": publishers[0] if publishers else None,
            # OpenLibrary non include la sinossi nei risultati di ricerca rapida
            # (servirebbe una chiamata aggiuntiva a /works/<id>.json - eventuale miglioramento futuro)
            "synopsis": None,
            "page_count": doc.get("number_of_pages_median") or None,
            "source_api": "openlibrary",
            "external_id": doc.get("key"),
        })
    return results


def _get_sbn_token() -> str | None:
    """
    Ottiene (o riusa dalla cache, se ancora valido) il token OAuth2 per SBN.
    Richiede SBN_CONSUMER_KEY e SBN_CONSUMER_SECRET nel file .env. Se mancano
    o la richiesta fallisce, restituisce None (la ricerca SBN verrà saltata).
    """
    now = time.time()
    if _sbn_token_cache["token"] and _sbn_token_cache["expires_at"] > now + 30:
        return _sbn_token_cache["token"]

    consumer_key = os.environ.get("SBN_CONSUMER_KEY")
    consumer_secret = os.environ.get("SBN_CONSUMER_SECRET")
    if not consumer_key or not consumer_secret:
        return None

    basic_auth = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
    try:
        resp = requests.post(
            SBN_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic_auth}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _sbn_token_cache["token"] = data["access_token"]
        _sbn_token_cache["expires_at"] = now + data.get("expires_in", 3600)
        return _sbn_token_cache["token"]
    except requests.RequestException:
        return None


def _parse_sbn_publish(publish: str):
    """'Firenze : G. Barbera, 1901' -> ('G. Barbera', '1901')"""
    if not publish:
        return None, None
    try:
        _, _, resto = publish.partition(" : ")
        resto = resto or publish
        editore, _, anno = resto.rpartition(", ")
        if not editore:
            return resto.strip() or None, None
        return editore.strip() or None, anno.strip() or None
    except Exception:
        return None, None


def _clean_sbn_author(raw: str) -> str | None:
    """Rimuove date di vita tra <...> e spazi/a-capo multipli dal nome autore."""
    if not raw:
        return None
    cleaned = re.sub(r"<[^>]*>", "", raw)
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _search_sbn(query: str, max_results: int = 5) -> list[dict]:
    """Cerca sul catalogo SBN (dati aperti ICCU) e normalizza i risultati nel formato comune."""
    token = _get_sbn_token()
    if not token:
        return []  # credenziali mancanti o token non ottenuto: si salta questa fonte

    try:
        resp = requests.get(
            f"{SBN_BASE_URL}/search",
            params={"monocampo": query, "format": "json", "page-size": max_results},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return []

    results = []
    for doc in data.get("response", {}).get("docs", []):
        isbd = doc.get("isbd", "") or ""
        title_part, _, author_part = isbd.partition(" / ")
        title = ((doc.get("pre_titolo") or "") + title_part).strip() or None

        author = _clean_sbn_author(doc.get("autore"))
        if not author and author_part:
            author = author_part.strip()
            for prefix in ("di ", "a cura di ", "traduzione di "):
                if author.lower().startswith(prefix):
                    author = author[len(prefix):].strip()
                    break

        publisher, year = _parse_sbn_publish(doc.get("publish"))
        # "Centro Internazionale del Libro Parlato" produce edizioni in
        # audiolibro per non vedenti: compare come "editore" ma è un ente,
        # non un vero editore commerciale - lo togliamo dal campo editore
        # (il resto del libro resta comunque valido e aggiungibile).
        if publisher and "centro internazionale del libro parlato" in publisher.lower():
            publisher = None
        isbn_list = doc.get("isbn") or []

        results.append({
            "title": title,
            "author": author,
            "authors_list": [author] if author else [],
            "isbn": isbn_list[0] if isbn_list else None,
            "cover_url": None,  # SBN non fornisce copertine
            "year": year,
            "publisher": publisher,
            "synopsis": None,  # SBN non fornisce sinossi
            "page_count": None,
            "source_api": "sbn",
            "external_id": doc.get("id"),
        })
    return results


def find_book_candidates(query: str, max_results: int = 5) -> list[dict]:
    """
    Cerca un libro su tre fonti e restituisce una lista di candidati.

    Strategia: Google Books (di solito più ricco per libri recenti/commerciali),
    poi SBN (catalogo delle biblioteche italiane, molto più forte sui libri
    italiani rispetto alle altre due fonti), poi OpenLibrary (più forte su
    edizioni storiche/rare anglofone). I risultati vengono combinati.
    """
    query = query.strip()
    if not query:
        return []

    google_results = _search_google_books(query, max_results)
    time.sleep(REQUEST_DELAY_SECONDS)
    sbn_results = _search_sbn(query, max_results)
    time.sleep(REQUEST_DELAY_SECONDS)
    openlibrary_results = _search_openlibrary(query, max_results)

    combined = google_results + sbn_results + openlibrary_results

    # Rimuove eventuali duplicati grossolani (stesso titolo+autore)
    seen = set()
    deduped = []
    for book in combined:
        key = (
            (book.get("title") or "").strip().lower(),
            (book.get("author") or "").strip().lower(),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(book)

    return deduped[:max_results]


if __name__ == "__main__":
    # Piccolo test manuale da riga di comando
    import sys
    query = " ".join(sys.argv[1:]) or "Notre-Dame de Paris Victor Hugo"
    candidates = find_book_candidates(query)
    for c in candidates:
        print(f"[{c['source_api']}] {c['title']} - {c['author']} ({c['year']}) - {c['publisher']}")
