"""
Connessione a Supabase.

Legge SUPABASE_URL e SUPABASE_KEY dal file .env (nella stessa cartella
del progetto) e crea un client riutilizzabile da tutto il resto dell'app.
"""

import os
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


@st.cache_resource
def get_supabase_client() -> Client:
    """
    Crea (una sola volta, grazie alla cache di Streamlit) il client Supabase.
    Solleva un errore chiaro se le variabili d'ambiente mancano, invece di
    fallire più avanti con un messaggio criptico.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error(
            "Configurazione mancante: crea un file `.env` nella cartella del "
            "progetto (puoi copiare `.env.example`) con SUPABASE_URL e "
            "SUPABASE_KEY presi da Supabase → Project Settings → API."
        )
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)
