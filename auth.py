"""
Autenticazione utente tramite Supabase Auth.

La sessione viene salvata anche in un cookie del browser (non solo in
st.session_state), così sopravvive ai refresh della pagina. Il cookie
scade dopo SESSION_TIMEOUT_MINUTES: da quel momento in poi la webapp
richiederà di nuovo l'accesso.
"""

from datetime import datetime, timedelta

import streamlit as st
import extra_streamlit_components as stx
from supabase_client import get_supabase_client

SESSION_TIMEOUT_MINUTES = 30
REMEMBER_ME_DAYS = 30

COOKIE_ACCESS = "sb_access_token"
COOKIE_REFRESH = "sb_refresh_token"
COOKIE_REMEMBER = "sb_remember"


def get_cookie_manager() -> stx.CookieManager:
    return stx.CookieManager(key="libri_app_cookie_manager")


def _set_session_cookies(cookie_manager, access_token: str, refresh_token: str, remember: bool = False):
    if remember:
        expires_at = datetime.now() + timedelta(days=REMEMBER_ME_DAYS)
    else:
        expires_at = datetime.now() + timedelta(minutes=SESSION_TIMEOUT_MINUTES)

    cookie_manager.set(COOKIE_ACCESS, access_token, expires_at=expires_at, key="set_access")
    cookie_manager.set(COOKIE_REFRESH, refresh_token, expires_at=expires_at, key="set_refresh")
    cookie_manager.set(
        COOKIE_REMEMBER, "1" if remember else "0", expires_at=expires_at, key="set_remember"
    )


def _clear_session_cookies(cookie_manager):
    for cookie_name, key in [
        (COOKIE_ACCESS, "del_access"),
        (COOKIE_REFRESH, "del_refresh"),
        (COOKIE_REMEMBER, "del_remember"),
    ]:
        try:
            cookie_manager.delete(cookie_name, key=key)
        except KeyError:
            pass


def sign_up(email: str, password: str, username: str):
    supabase = get_supabase_client()
    return supabase.auth.sign_up({
        "email": email,
        "password": password,
        "options": {"data": {"username": username}},
    })


def sign_in(email: str, password: str):
    supabase = get_supabase_client()
    return supabase.auth.sign_in_with_password({
        "email": email,
        "password": password,
    })


def sign_out():
    supabase = get_supabase_client()
    supabase.auth.sign_out()
    st.session_state.pop("user", None)
    st.session_state.pop("access_token", None)
    _clear_session_cookies(get_cookie_manager())


def get_current_user():
    """Restituisce l'utente collegato (dict con id, email) oppure None."""
    return st.session_state.get("user")


def _try_restore_session_from_cookie(cookie_manager):
    """
    Se esiste una sessione già collegata in st.session_state, non fa nulla.
    Altrimenti prova a leggere i token dal cookie e a ripristinare la
    sessione Supabase. Se il cookie è scaduto o assente, non succede nulla
    e più avanti comparirà il form di login.
    """
    if get_current_user():
        return

    cookies = cookie_manager.get_all()
    if cookies is None:
        return  # il componente cookie non ha ancora finito di caricare

    access_token = cookies.get(COOKIE_ACCESS)
    refresh_token = cookies.get(COOKIE_REFRESH)
    remember = cookies.get(COOKIE_REMEMBER) == "1"

    if not access_token or not refresh_token:
        return

    try:
        supabase = get_supabase_client()
        result = supabase.auth.set_session(access_token, refresh_token)
        st.session_state["user"] = {
            "id": result.user.id,
            "email": result.user.email,
        }
        st.session_state["access_token"] = result.session.access_token
        # rinnova la scadenza da questo accesso, mantenendo la stessa
        # preferenza (breve o "Ricordami") scelta al login
        _set_session_cookies(
            cookie_manager, result.session.access_token, result.session.refresh_token, remember
        )
    except Exception:
        # token scaduto/non valido: ignoriamo, l'utente rivedrà il login
        _clear_session_cookies(cookie_manager)


def require_login():
    """
    Prova prima a ripristinare la sessione da cookie; se non riesce,
    mostra un form di login/registrazione e ferma l'esecuzione della
    pagina finché l'utente non è collegato. Va chiamata all'inizio di app.py.
    """
    cookie_manager = get_cookie_manager()
    _try_restore_session_from_cookie(cookie_manager)

    if get_current_user():
        return  # sessione valida, prosegui con il resto della pagina

    st.title("📚 La mia libreria")
    st.subheader("Accedi o registrati per continuare")

    tab_login, tab_signup = st.tabs(["Accedi", "Registrati"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            remember_me = st.checkbox("Ricordami su questo dispositivo", value=True)
            submitted = st.form_submit_button("Accedi")

            if submitted:
                try:
                    result = sign_in(email, password)
                    st.session_state["user"] = {
                        "id": result.user.id,
                        "email": result.user.email,
                    }
                    st.session_state["access_token"] = result.session.access_token
                    _set_session_cookies(
                        cookie_manager,
                        result.session.access_token,
                        result.session.refresh_token,
                        remember_me,
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Accesso non riuscito: controlla email e password. ({e})")

    with tab_signup:
        with st.form("signup_form"):
            username = st.text_input("Nome utente", key="signup_username")
            email = st.text_input("Email", key="signup_email")
            password = st.text_input(
                "Password (almeno 6 caratteri)", type="password", key="signup_password"
            )
            submitted = st.form_submit_button("Crea account")

            if submitted:
                if not username.strip():
                    st.error("Il nome utente è obbligatorio.")
                elif len(password) < 6:
                    st.error("La password deve avere almeno 6 caratteri.")
                else:
                    try:
                        sign_up(email, password, username.strip())
                        st.success(
                            "Account creato! Se Supabase richiede la conferma "
                            "via email, controlla la posta prima di accedere. "
                            "Altrimenti, vai sulla tab 'Accedi'."
                        )
                    except Exception as e:
                        st.error(f"Registrazione non riuscita: {e}")

    st.stop()  # non far proseguire il resto della pagina finché non c'è login
