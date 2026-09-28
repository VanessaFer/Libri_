"""
Script di popolamento una tantum (o periodico) della tabella
notable_authors, da lanciare A MANO IN LOCALE:

    python populate_notable_authors.py

NON fa parte della webapp: interroga Wikidata (stessa logica che prima
girava a ogni apertura della mappa) e scrive i risultati nella tabella
notable_authors su Supabase, così la mappa in Esplora può leggerli
all'istante invece di aspettare Wikidata ogni volta.

Richiede la SERVICE ROLE KEY di Supabase (non l'anon key che usa la
webapp): bypassa le policy RLS, quindi va tenuta SOLO in questo file .env
locale e MAI messa tra i secrets della webapp online. Si trova su
supabase.com -> il tuo progetto -> Settings -> API -> service_role key
(sezione "Project API keys", tienila segreta).

Aggiungi al tuo .env locale:
    SUPABASE_SERVICE_ROLE_KEY=...

Rilancia lo script ogni tanto se vuoi aggiornare/ampliare l'elenco degli
autori (i dati non cambiano spesso, non serve farlo più di una volta ogni
diversi mesi).
"""

import os
import re
import time

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "BibliophileLibraryApp/1.0 (script di popolamento, uso locale una tantum)"

# Stesso elenco di occupazioni letterarie usato altrove nel progetto: scrittore,
# poeta, romanziere, drammaturgo, saggista.
LITERARY_OCCUPATIONS = ["Q36180", "Q49757", "Q6625963", "Q214917", "Q11774202"]
MIN_SITELINKS = 30

# Fasce temporali (anno inizio, anno fine, quanti autori prendere per fascia):
# un contingente per epoca invece di una classifica unica per notorietà
# globale, altrimenti gli autori moderni (tradotti in centinaia di lingue su
# Wikipedia) schiaccerebbero quelli medievali/rinascimentali.
ERA_BUCKETS = [
    (1, 500, 12),
    (501, 1000, 12),
    (1001, 1400, 15),
    (1401, 1600, 15),
    (1601, 1750, 15),
    (1751, 1850, 15),
    (1851, 1920, 20),
    (1921, 1970, 20),
    (1971, 2026, 20),
]

POINT_RE = re.compile(r"Point\(([-\d.]+) ([-\d.]+)\)")


def _run_sparql(query: str, retries: int = 5) -> list[dict]:
    """Esegue una query SPARQL, ritentando in caso di errori temporanei del
    server (502/503/timeout, comuni con l'endpoint pubblico di Wikidata sotto carico)."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                WIKIDATA_SPARQL_URL,
                params={"query": query, "format": "json"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json().get("results", {}).get("bindings", [])
        except requests.RequestException as e:
            last_error = e
            if attempt < retries:
                wait = 5 * attempt
                print(f"  (tentativo {attempt} fallito: {e} - riprovo tra {wait}s)")
                time.sleep(wait)
    print(f"  Errore persistente dopo {retries} tentativi: {last_error}")
    return []


def _parse_point(value):
    if not value:
        return None
    match = POINT_RE.match(value)
    if not match:
        return None
    lon, lat = match.groups()
    return float(lat), float(lon)


def _safe_date10(value):
    """Scarta le date precedenti all'anno 0 (formato Wikidata con il segno
    meno), che altrimenti finirebbero troncate in modo scorretto."""
    if not value or value.startswith("-"):
        return None
    return value[:10]


def get_top_person_qids_all_eras() -> list[str]:
    """QID degli autori più noti (per sitelink) in ciascuna fascia temporale.
    Una richiesta per fascia (più lento, ma più affidabile di un'unica
    mega-query con tutte le fasce unite: quella tende ad andare in timeout
    sui server pubblici di Wikidata)."""
    occupations_values = " ".join(f"wd:{qid}" for qid in LITERARY_OCCUPATIONS)
    all_qids = []
    for start_year, end_year, limit in ERA_BUCKETS:
        print(f"  Fascia {start_year}-{end_year}...")
        query = f"""
        SELECT ?person WHERE {{
          VALUES ?occupation {{ {occupations_values} }}
          ?person wdt:P106 ?occupation .
          ?person wdt:P569 ?dob .
          FILTER(YEAR(?dob) >= {start_year} && YEAR(?dob) <= {end_year})
          ?person wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks > {MIN_SITELINKS})
        }}
        ORDER BY DESC(?sitelinks)
        LIMIT {limit}
        """
        rows = _run_sparql(query)
        all_qids.extend(
            row["person"]["value"].rstrip("/").split("/")[-1]
            for row in rows if row.get("person")
        )
        time.sleep(2)
    return all_qids


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def get_authors_data(qids: list[str]) -> list[dict]:
    """Per ciascun QID: nome, link Wikipedia IT, luogo/anno/coordinate di
    nascita e morte (una riga per persona, non una per evento). Le richieste
    sono spezzate in blocchi da 40 QID, per non appesantire troppo ciascuna
    singola query."""
    authors: dict[str, dict] = {}
    batches = list(_chunks(qids, 40))
    for i, batch in enumerate(batches, start=1):
        print(f"  Dati biografici: blocco {i}/{len(batches)}...")
        values_clause = " ".join(f"wd:{qid}" for qid in batch)
        query = f"""
        SELECT DISTINCT ?person ?personLabel ?dob ?dobCoord ?dobPlaceLabel
                         ?dod ?dodCoord ?dodPlaceLabel ?article WHERE {{
          VALUES ?person {{ {values_clause} }}
          OPTIONAL {{
            ?person wdt:P569 ?dob .
            ?person wdt:P19 ?dobPlace .
            ?dobPlace wdt:P625 ?dobCoord .
          }}
          OPTIONAL {{
            ?person wdt:P570 ?dod .
            ?person wdt:P20 ?dodPlace .
            ?dodPlace wdt:P625 ?dodCoord .
          }}
          OPTIONAL {{
            ?article schema:about ?person ;
                     schema:isPartOf <https://it.wikipedia.org/> .
          }}
          SERVICE wikibase:label {{
            bd:serviceParam wikibase:language "it,en".
            ?person rdfs:label ?personLabel .
            ?dobPlace rdfs:label ?dobPlaceLabel .
            ?dodPlace rdfs:label ?dodPlaceLabel .
          }}
        }}
        """
        rows = _run_sparql(query)

        for row in rows:
            person_url = row.get("person", {}).get("value", "")
            qid = person_url.rstrip("/").split("/")[-1]
            entry = authors.setdefault(qid, {
                "name": row.get("personLabel", {}).get("value"),
                "wikidata_id": qid,
                "wikipedia_url": row.get("article", {}).get("value"),
                "birth_year": None, "birth_place": None, "birth_lat": None, "birth_lon": None,
                "death_year": None, "death_place": None, "death_lat": None, "death_lon": None,
            })

            dob = _safe_date10(row.get("dob", {}).get("value"))
            dob_coord = _parse_point(row.get("dobCoord", {}).get("value"))
            if dob and dob_coord and entry["birth_year"] is None:
                entry["birth_year"] = int(dob[:4])
                entry["birth_place"] = row.get("dobPlaceLabel", {}).get("value")
                entry["birth_lat"], entry["birth_lon"] = dob_coord

            dod = _safe_date10(row.get("dod", {}).get("value"))
            dod_coord = _parse_point(row.get("dodCoord", {}).get("value"))
            if dod and dod_coord and entry["death_year"] is None:
                entry["death_year"] = int(dod[:4])
                entry["death_place"] = row.get("dodPlaceLabel", {}).get("value")
                entry["death_lat"], entry["death_lon"] = dod_coord

        time.sleep(2)

    return list(authors.values())


def get_movements(qids: list[str]) -> dict[str, str]:
    """QID -> correnti letterarie separate da virgola (stringa vuota se nessuna
    nota). Anche qui, a blocchi da 40 QID per stare leggeri."""
    result = {}
    batches = list(_chunks(qids, 40))
    for i, batch in enumerate(batches, start=1):
        print(f"  Correnti letterarie: blocco {i}/{len(batches)}...")
        values_clause = " ".join(f"wd:{qid}" for qid in batch)
        query = f"""
        SELECT ?person (GROUP_CONCAT(DISTINCT ?movementLabel; separator="||") AS ?movements) WHERE {{
          VALUES ?person {{ {values_clause} }}
          OPTIONAL {{
            ?person wdt:P135 ?movement .
            ?movement rdfs:label ?movementLabel .
            FILTER(LANG(?movementLabel) = "it")
          }}
        }}
        GROUP BY ?person
        """
        rows = _run_sparql(query)
        for row in rows:
            qid = row["person"]["value"].rstrip("/").split("/")[-1]
            raw = row.get("movements", {}).get("value") or ""
            result[qid] = ", ".join(m for m in raw.split("||") if m)
        time.sleep(2)
    return result


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        print(
            "Mancano SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY nel file .env.\n"
            "La service role key si trova su supabase.com -> progetto -> Settings -> API."
        )
        return

    supabase = create_client(supabase_url, service_key)

    print("Cerco gli autori più notevoli per fascia temporale su Wikidata...")
    qids = sorted(set(get_top_person_qids_all_eras()))
    print(f"Trovati {len(qids)} autori distinti. Recupero i dati geografici/biografici...")

    authors = get_authors_data(qids)
    time.sleep(0.5)

    print("Recupero le correnti letterarie...")
    movements = get_movements(qids)
    for author in authors:
        author["movements"] = movements.get(author["wikidata_id"], "")

    print(f"Scrivo {len(authors)} autori su Supabase (tabella notable_authors)...")
    # Svuota la tabella prima di riscrivere, per evitare doppioni se rilanci lo script
    supabase.table("notable_authors").delete().neq(
        "id", "00000000-0000-0000-0000-000000000000"
    ).execute()

    batch_size = 100
    for i in range(0, len(authors), batch_size):
        batch = authors[i:i + batch_size]
        supabase.table("notable_authors").insert(batch).execute()
        print(f"  ...{min(i + batch_size, len(authors))}/{len(authors)}")

    print("Fatto! La mappa in Esplora ora leggerà da questa tabella, molto più veloce.")


if __name__ == "__main__":
    main()
