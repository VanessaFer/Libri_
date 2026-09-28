"""
Mappa interattiva degli autori: luoghi di nascita/morte con uno slider
temporale per vedere come cambiano nel tempo. La mappa viene disegnata con
Folium (plugin TimestampedGeoJson).

I dati per la modalità "generale" (i grandi autori della storia) vengono
letti dalla tabella notable_authors, precaricata una tantum dallo script
populate_notable_authors.py — non da Wikidata in tempo reale, per evitare i
caricamenti lenti di prima (soprattutto quando l'app si "risveglia" su
Streamlit Cloud e perde la cache in memoria).

La modalità "libreria" (autori della propria libreria, cercati per nome)
resta invece basata su ricerche dirette a Wikidata: qui i dati sono
per forza specifici per utente, non precaricabili in una tabella condivisa.
Attualmente non è collegata alla UI (rimossa perché troppo lenta), ma le
funzioni restano pronte come base per un'eventuale ripresa futura.
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

# Stesso elenco di occupazioni letterarie usato in on_this_day.py: scrittore,
# poeta, romanziere, drammaturgo, saggista.
LITERARY_OCCUPATIONS = ["Q36180", "Q49757", "Q6625963", "Q214917", "Q11774202"]

POINT_RE = re.compile(r"Point\(([-\d.]+) ([-\d.]+)\)")

NO_MOVEMENT_LABEL = "Non specificata"


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
    oppure None per le date precedenti all'anno 0 (a.C.), che uno slicing
    ingenuo tronca in modo scorretto.
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


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def get_general_authors_geo() -> list[dict]:
    """
    Grandi autori della storia in generale, letti dalla tabella
    notable_authors (precaricata da populate_notable_authors.py) invece che
    da Wikidata in tempo reale: molto più veloce da caricare.
    """
    supabase = get_supabase_client()
    resp = supabase.table("notable_authors").select("*").execute()

    events = []
    for row in resp.data:
        movements = [m.strip() for m in (row.get("movements") or "").split(",") if m.strip()]

        if row.get("birth_year") and row.get("birth_lat") is not None and row.get("birth_lon") is not None:
            events.append({
                "name": row["name"],
                "event": "nascita",
                "date": f"{row['birth_year']:04d}-01-01",
                "lat": row["birth_lat"],
                "lon": row["birth_lon"],
                "url": row.get("wikipedia_url"),
                "movements": movements,
            })

        if row.get("death_year") and row.get("death_lat") is not None and row.get("death_lon") is not None:
            events.append({
                "name": row["name"],
                "event": "morte",
                "date": f"{row['death_year']:04d}-01-01",
                "lat": row["death_lat"],
                "lon": row["death_lon"],
                "url": row.get("wikipedia_url"),
                "movements": movements,
            })

    return events


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
