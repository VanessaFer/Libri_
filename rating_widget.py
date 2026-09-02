"""
Widget di rating "a libri" (📖 aperto = valutato / 📕 chiuso = non ancora)
al posto delle stelline classiche. Streamlit non ha un widget nativo con
icone personalizzate per il rating, quindi lo simuliamo con una riga di
bottoni cliccabili, ingranditi con un po' di CSS mirato solo a questo widget.
"""

import streamlit as st

FILLED = "📖"  # libro aperto: posizione valutata
EMPTY = "📕"   # libro chiuso: posizione non ancora valutata


def book_rating_input(key: str, default: int = 0, max_rating: int = 5) -> int:
    """
    Mostra `max_rating` bottoni in fila; cliccando sul n-esimo, il rating
    diventa n (cliccare di nuovo sullo stesso valore lo azzera, per poter
    "non esprimere" un rating già dato). Il valore corrente vive in
    st.session_state[key] così sopravvive ai rerun della pagina.
    """
    state_key = f"book_rating_{key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = default

    current = st.session_state[state_key]
    container_key = f"rating_container_{key}"

    # CSS mirato: ingrandisce solo i bottoni dentro questo specifico widget,
    # senza toccare l'aspetto degli altri bottoni della webapp
    st.markdown(
        f"""
        <style>
        .st-key-{container_key} button {{
            font-size: 2.2rem !important;
            line-height: 1 !important;
            padding: 0.3rem 0.5rem !important;
            min-height: 3rem !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key=container_key):
        cols = st.columns(max_rating + 1)  # +1 per l'etichetta testuale finale
        for i in range(1, max_rating + 1):
            icon = FILLED if i <= current else EMPTY
            with cols[i - 1]:
                if st.button(icon, key=f"{key}_btn_{i}"):
                    st.session_state[state_key] = 0 if current == i else i
                    st.rerun()

        with cols[-1]:
            st.caption(f"{current}/5" if current else "non valutato")

    return st.session_state[state_key]
