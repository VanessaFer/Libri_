"""
"Accadde oggi": nascite e morti di autori letterari nella data odierna,
recuperate da Wikidata tramite una query SPARQL.

Considera scrittori, poeti, romanzieri, drammaturghi e saggisti, filtrati
per un minimo di notabilità (numero di sitelink su Wikidata) per evitare
nomi troppo oscuri o poco affidabili nei dati.

Il risultato viene tenuto in cache per qualche ora (la data non cambia
nel frattempo), così non si interroga Wikidata a ogni caricamento pagina.
"""

from datetime import date

import requests
import streamlit as st

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
# Wikidata chiede uno User-Agent descrittivo per le richieste automatiche
USER_AGENT = "BibliophileLibraryApp/1.0 (webapp personale di tracciamento libri)"

# Occupazioni letterarie considerate: scrittore, poeta, romanziere,
# drammaturgo, saggista
LITERARY_OCCUPATIONS = ["Q36180", "Q49757", "Q6625963", "Q214917", "Q11774202"]

MIN_SITELINKS = 10  # soglia minima di notabilità

SPARQL_TEMPLATE = """
SELECT DISTINCT ?person ?personLabel ?event ?year ?sitelinks ?article WHERE {{
  VALUES ?occupation {{ {occupations} }}
  ?person wdt:P106 ?occupation .
  ?person wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks > {min_sitelinks})
  {{
    ?person wdt:P569 ?date .
    BIND("nascita" AS ?event)
  }}
  UNION
  {{
    ?person wdt:P570 ?date .
    BIND("morte" AS ?event)
  }}
  FILTER(MONTH(?date) = {month} && DAY(?date) = {day})
  BIND(YEAR(?date) AS ?year)
  OPTIONAL {{
    ?article schema:about ?person ;
             schema:isPartOf <https://it.wikipedia.org/> .
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "it,en". }}
}}
ORDER BY DESC(?sitelinks)
LIMIT {limit}
"""


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def get_todays_literary_events(limit: int = 5) -> list[dict]:
    """
    Restituisce fino a `limit` eventi (nascita/morte di autori letterari)
    avvenuti nel giorno-mese odierno, in anni diversi, ordinati per
    notorietà dell'autore. Ogni elemento: {name, event, year, url}.
    In caso di errore di rete/timeout restituisce una lista vuota,
    così il resto della pagina continua a funzionare normalmente.
    """
    today = date.today()
    query = SPARQL_TEMPLATE.format(
        occupations=" ".join(f"wd:{qid}" for qid in LITERARY_OCCUPATIONS),
        min_sitelinks=MIN_SITELINKS,
        month=today.month,
        day=today.day,
        limit=limit,
    )

    try:
        resp = requests.get(
            WIKIDATA_SPARQL_URL,
            params={"query": query, "format": "json"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return []

    events = []
    for row in data.get("results", {}).get("bindings", []):
        wikipedia_url = row.get("article", {}).get("value")
        wikidata_url = row.get("person", {}).get("value")
        events.append({
            "name": row.get("personLabel", {}).get("value"),
            "event": row.get("event", {}).get("value"),
            "year": row.get("year", {}).get("value"),
            "url": wikipedia_url or wikidata_url,
        })
    return events
