"""
Tema visivo "libresca": palette verde bosco + oro, font EB Garamond
(il sostituto libero più vicino a Simoncini Garamond, non disponibile
gratuitamente per il web).

I colori di base (sfondo, sidebar, colore primario) sono già impostati
in .streamlit/config.toml - qui ci occupiamo del font e dei dettagli
che il tema nativo di Streamlit non copre.
"""

import streamlit as st

# Palette, riutilizzata anche dalle funzioni badge qui sotto
INK_GREEN = "#2F5233"
SOFT_GREEN = "#5C6E56"
GOLD = "#B08D3E"
GOLD_LIGHT = "#EDDEB0"
SAGE_LIGHT = "#DCE3D2"
SAGE_TEXT = "#33472F"
PARCHMENT = "#F2ECDD"
CARD_BG = "#FAF6EA"
CARD_BORDER = "#8FA084"


def inject_theme():
    """Da chiamare una volta sola, subito dopo st.set_page_config()."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500;600&display=swap');

        html, body {{
            font-family: 'EB Garamond', Georgia, serif !important;
            color: {INK_GREEN} !important;
        }}

        h1, h2, h3, h4,
        .stMarkdown, .stMarkdown *,
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *,
        .stButton, .stButton *,
        input, textarea, select,
        .stRadio, .stRadio *,
        [data-testid="stMetricValue"], [data-testid="stMetricValue"] *,
        [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{
            font-family: 'EB Garamond', Georgia, serif !important;
            color: {INK_GREEN} !important;
        }}

        h1, h2, h3, h4 {{
            font-weight: 600 !important;
        }}

        .stButton > button {{
            border-color: {INK_GREEN} !important;
        }}
        .stButton > button:hover, .stButton > button:hover * {{
            border-color: {GOLD} !important;
            color: {GOLD} !important;
        }}

        [data-testid="stProgressBarTrack"] {{
            border: 1px solid {GOLD} !important;
        }}
        [data-testid="stProgressBarTrack"] > div {{
            background-color: {GOLD} !important;
        }}

        /* Bottoni "Apri scheda" e "Aggiungi alla libreria": stile pieno, come nel mockup approvato */
        [class*="st-key-mylib_open_"] button,
        [class*="st-key-mylib_open_"] button *,
        [class*="st-key-catalog_open_"] button,
        [class*="st-key-catalog_open_"] button *,
        [class*="st-key-addlib_"] button,
        [class*="st-key-addlib_"] button *,
        .st-key-open_last_added button,
        .st-key-open_last_added button * {{
            background-color: {INK_GREEN} !important;
            color: {PARCHMENT} !important;
            border: none !important;
        }}
        [class*="st-key-mylib_open_"] button:hover,
        [class*="st-key-mylib_open_"] button:hover *,
        [class*="st-key-catalog_open_"] button:hover,
        [class*="st-key-catalog_open_"] button:hover *,
        [class*="st-key-addlib_"] button:hover,
        [class*="st-key-addlib_"] button:hover *,
        .st-key-open_last_added button:hover,
        .st-key-open_last_added button:hover * {{
            background-color: {GOLD} !important;
            color: {INK_GREEN} !important;
        }}

        [data-testid="stSidebar"] {{
            background-color: {CARD_BG} !important;
            border-right: 1px solid {CARD_BORDER};
        }}

        /* Badge di stato e formato: classe dedicata per evitare che lo stile
           inline venga filtrato, e per non farsi sovrascrivere dalla regola
           generale del colore testo. */
        .libresca-badge-status {{
            display: inline-block !important;
            background: {GOLD_LIGHT} !important;
            color: {INK_GREEN} !important;
            font-size: 13px !important;
            padding: 3px 10px !important;
            border-radius: 20px !important;
            font-weight: 600 !important;
        }}
        .libresca-badge-formato {{
            display: inline-block !important;
            background: {SAGE_LIGHT} !important;
            color: {SAGE_TEXT} !important;
            font-size: 13px !important;
            padding: 3px 10px !important;
            border-radius: 20px !important;
        }}

        /* Bottoni "✕ Tag" nella scheda libro: stile a pillola, come i badge */
        .st-key-tag_remove_buttons button {{
            background: {SAGE_LIGHT} !important;
            color: {SAGE_TEXT} !important;
            border: none !important;
            border-radius: 20px !important;
            padding: 3px 12px !important;
            font-size: 13px !important;
            width: auto !important;
            min-height: 0 !important;
        }}
        .st-key-tag_remove_buttons button:hover {{
            background: {GOLD_LIGHT} !important;
            color: {INK_GREEN} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_badge(label: str) -> str:
    """HTML di un badge oro chiaro (per lo stato di lettura)."""
    return f'<span class="libresca-badge-status">{label}</span>'


def formato_badge(label: str) -> str:
    """HTML di un badge verde tenue (per il formato: cartaceo/digitale/audiolibro)."""
    return f'<span class="libresca-badge-formato">{label}</span>'
