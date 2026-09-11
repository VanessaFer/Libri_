"""
Mappa interattiva degli autori: luoghi di nascita/morte con uno slider
temporale per vedere come cambiano nel tempo. I dati geografici vengono
da Wikidata, la mappa viene disegnata con Folium (plugin TimestampedGeoJson).

Due modalità:
- "libreria": solo gli autori presenti nella libreria dell'utente (works ->
  work_authors -> authors), cercati singolarmente su Wikidata per nome.
- "generale": i grandi autori della storia in generale, indipendentemente
  dalla libreria, filtrati per notabilità (numero di sitelink Wikidata).

Entrambe le modalità restano in cache per un giorno: i dati non cambiano
da un momento all'altro, e ogni ricerca per nome comporta una chiamata
di rete a Wikidata (lente se ripetute a ogni apertura della mappa).
"""

import re
import time

import folium
import requests
import streamlit as st
from folium.plugins import TimestampedGeoJson

from supabase_client import get_supabase_client

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "BibliophileLibraryApp/1.0 (webapp personale di tracciamento libri)"

REQUEST_DELAY_SECONDS = 0.3
MIN_SITELINKS_GENERAL = 30

# Stesso elenco di occupazioni letterarie usato in on_this_day.py: scrittore,
# poeta, romanziere, drammaturgo, saggista. Usare un elenco esplicito (invece
# di un pattern con wildcard su tutte le sottocategorie) evita query troppo
# pesanti che vanno spesso in timeout sui server pubblici di Wikidata.
LITERARY_OCCUPATIONS = ["Q36180", "Q49757", "Q6625963", "Q214917", "Q11774202"]

POINT_RE = re.compile(r"Point\(([-\d.]+) ([-\d.]+)\)")


def _run_sparql(query: str) -> list[dict]:
    try:
        resp = requests.get(
            WIKIDATA_SPARQL_URL,
            params={"query": query, "format": "json"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("results", {}).get("bindings", [])
    except requests.RequestException:
        return []


def _parse_point(value: str | None):
    """'Point(12.4964 41.9028)' -> (lat, lon)  [Wikidata usa lon lat, non lat lon]"""
    if not value:
        return None
    match = POINT_RE.match(value)
    if not match:
        return None
    lon, lat = match.groups()
    return float(lat), float(lon)


def _safe_date10(value: str | None) -> str | None:
    """
    Restituisce i primi 10 caratteri (YYYY-MM-DD) di una data ISO di Wikidata,
    oppure None per le date precedenti all'anno 0 (a.C.). Queste ultime
    arrivano da Wikidata in un formato con il segno meno (es. "-0043-01-03..."
    per Cicerone), che uno slicing ingenuo tronca in modo scorretto e che i
    browser gestiscono comunque male nello slider temporale: meglio escluderle
    con chiarezza che rischiare di rompere l'intera timeline.
    """
    if not value or value.startswith("-"):
        return None
    return value[:10]


def _rows_to_events(rows: list[dict]) -> list[dict]:
    """Trasforma le righe SPARQL in eventi puntuali (una riga per nascita, una per morte)."""
    events = []
    for row in rows:
        name = row.get("personLabel", {}).get("value")
        person_url = row.get("person", {}).get("value")

        dob = _safe_date10(row.get("dob", {}).get("value"))
        dob_coord = _parse_point(row.get("dobCoord", {}).get("value"))
        if dob and dob_coord:
            events.append({
                "name": name, "event": "nascita", "date": dob,
                "lat": dob_coord[0], "lon": dob_coord[1], "url": person_url,
            })

        dod = _safe_date10(row.get("dod", {}).get("value"))
        dod_coord = _parse_point(row.get("dodCoord", {}).get("value"))
        if dod and dod_coord:
            events.append({
                "name": name, "event": "morte", "date": dod,
                "lat": dod_coord[0], "lon": dod_coord[1], "url": person_url,
            })
    return events


# Fasce temporali (anno inizio, anno fine, quanti autori prendere per fascia).
# Selezionare un contingente per epoca, invece di una classifica unica per
# notorietà globale, evita che gli autori moderni (tradotti in centinaia di
# lingue su Wikipedia) "schiaccino" quelli medievali/rinascimentali, che
# altrimenti sparirebbero quasi del tutto dalla mappa.
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


def _top_person_qids_all_eras() -> list[str]:
    """
    QID degli autori più noti (per sitelink) in ciascuna fascia temporale,
    tutti recuperati in un'unica richiesta a Wikidata (una sotto-query per
    fascia, unite con UNION) invece di una richiesta separata per fascia:
    ogni richiesta di rete ha un costo fisso di latenza che si somma in
    fretta se ripetuto 9 volte di fila.
    """
    occupations_values = " ".join(f"wd:{qid}" for qid in LITERARY_OCCUPATIONS)
    era_blocks = []
    for start_year, end_year, limit in ERA_BUCKETS:
        era_blocks.append(f"""
        {{
          SELECT ?person WHERE {{
            VALUES ?occupation {{ {occupations_values} }}
            ?person wdt:P106 ?occupation .
            ?person wdt:P569 ?dob .
            FILTER(YEAR(?dob) >= {start_year} && YEAR(?dob) <= {end_year})
            ?person wikibase:sitelinks ?sitelinks .
            FILTER(?sitelinks > {MIN_SITELINKS_GENERAL})
          }}
          ORDER BY DESC(?sitelinks)
          LIMIT {limit}
        }}
        """)

    query = f"""
    SELECT DISTINCT ?person WHERE {{
      {" UNION ".join(era_blocks)}
    }}
    """
    rows = _run_sparql(query)
    return [
        row["person"]["value"].rstrip("/").split("/")[-1]
        for row in rows if row.get("person")
    ]


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def get_general_authors_geo() -> list[dict]:
    """Grandi autori della storia in generale, con coordinate di nascita/morte
    e la/le correnti letterarie a cui sono associati (quando note su Wikidata).
    Gli autori vengono scelti a piccoli gruppi per fascia temporale (vedi
    ERA_BUCKETS), non con un'unica classifica globale, per avere una
    distribuzione più equilibrata nel tempo."""
    qids = sorted(set(_top_person_qids_all_eras()))
    if not qids:
        return []

    values_clause = " ".join(f"wd:{qid}" for qid in qids)
    query = f"""
    SELECT DISTINCT ?person ?personLabel ?dob ?dobCoord ?dod ?dodCoord WHERE {{
      VALUES ?person {{ {values_clause} }}
      OPTIONAL {{
        ?person wdt:P569 ?dob .
        ?person wdt:P19 ?pob .
        ?pob wdt:P625 ?dobCoord .
      }}
      OPTIONAL {{
        ?person wdt:P570 ?dod .
        ?person wdt:P20 ?pod .
        ?pod wdt:P625 ?dodCoord .
      }}
      FILTER(BOUND(?dobCoord) || BOUND(?dodCoord))
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "it,en". }}
    }}
    """
    events = _rows_to_events(_run_sparql(query))

    person_urls = sorted({ev["url"] for ev in events if ev.get("url")})
    movements_by_person = _get_movements_for_persons(person_urls)
    for ev in events:
        ev["movements"] = movements_by_person.get(ev["url"], [])

    return events


NO_MOVEMENT_LABEL = "Non specificata"


def _get_movements_for_persons(person_urls: list[str]) -> dict[str, list[str]]:
    """Recupera, per un elenco di persone Wikidata, le correnti/movimenti
    letterari (proprietà P135) a cui sono associate. Restituisce un dizionario
    url-persona -> lista di nomi di movimento (vuota se nessuno noto)."""
    if not person_urls:
        return {}

    qids = [url.rstrip("/").split("/")[-1] for url in person_urls]
    values_clause = " ".join(f"wd:{qid}" for qid in qids)

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

    result = {}
    for row in rows:
        person_url = row.get("person", {}).get("value")
        raw = row.get("movements", {}).get("value") or ""
        movements = [m for m in raw.split("||") if m]
        result[person_url] = movements
    return result


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def get_library_authors_geo(author_names: tuple[str, ...]) -> list[dict]:
    """Autori presenti nella libreria dell'utente, cercati per nome su Wikidata."""
    all_events = []
    for name in author_names:
        escaped = name.replace('"', '\\"').replace("\\", "\\\\")
        query = f"""
        SELECT DISTINCT ?person ?personLabel ?dob ?dobCoord ?dod ?dodCoord WHERE {{
          VALUES ?occupation {{ {" ".join(f"wd:{qid}" for qid in LITERARY_OCCUPATIONS)} }}
          ?person wdt:P106 ?occupation .
          ?person rdfs:label ?nameLabel .
          FILTER(LANG(?nameLabel) IN ("it", "en"))
          FILTER(LCASE(STR(?nameLabel)) = LCASE("{escaped}"))
          OPTIONAL {{
            ?person wdt:P569 ?dob .
            ?person wdt:P19 ?pob .
            ?pob wdt:P625 ?dobCoord .
          }}
          OPTIONAL {{
            ?person wdt:P570 ?dod .
            ?person wdt:P20 ?pod .
            ?pod wdt:P625 ?dodCoord .
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "it,en". }}
        }}
        LIMIT 1
        """
        rows = _run_sparql(query)
        all_events.extend(_rows_to_events(rows))
        time.sleep(REQUEST_DELAY_SECONDS)
    return all_events


def get_library_author_names(user_id: str) -> list[str]:
    """Nomi distinti degli autori delle opere presenti nella libreria dell'utente."""
    supabase = get_supabase_client()
    resp = (
        supabase.table("user_books")
        .select("books(work_id)")
        .eq("user_id", user_id)
        .execute()
    )
    work_ids = {
        row["books"]["work_id"]
        for row in resp.data
        if row.get("books") and row["books"].get("work_id")
    }
    if not work_ids:
        return []

    resp2 = (
        supabase.table("work_authors")
        .select("authors(name)")
        .in_("work_id", list(work_ids))
        .execute()
    )
    names = {
        row["authors"]["name"]
        for row in resp2.data
        if row.get("authors") and row["authors"].get("name")
    }
    return sorted(names)


def build_timeline_map(events: list[dict]) -> folium.Map:
    """Costruisce la mappa Folium con lo slider temporale a partire dagli eventi."""
    fmap = folium.Map(
        location=[30, 10],
        zoom_start=2,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
    )

    features = []
    for ev in events:
        color = "#2e7d32" if ev["event"] == "nascita" else "#6d4c41"  # verde per nascita, marrone per morte
        movements = ev.get("movements") or []
        movements_html = f"<br><i>{', '.join(movements)}</i>" if movements else ""
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [ev["lon"], ev["lat"]]},
            "properties": {
                "time": ev["date"],
                "popup": f"<b>{ev['name']}</b><br>{ev['event']} — {ev['date'][:4]}{movements_html}",
                "icon": "circle",
                "iconstyle": {
                    "fillColor": color,
                    "fillOpacity": 0.8,
                    "stroke": "true",
                    "color": color,
                    "weight": 1,
                    "radius": 6,
                },
            },
        })

    TimestampedGeoJson(
        {"type": "FeatureCollection", "features": features},
        period="P5Y",
        duration="P5Y",
        add_last_point=True,
        auto_play=False,
        loop=False,
        max_speed=5,
        loop_button=True,
        date_options="YYYY",
        time_slider_drag_update=True,
    ).add_to(fmap)

    return fmap
