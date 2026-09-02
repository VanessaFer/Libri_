"""
Webapp Libri - con autenticazione, salvataggio reale su Supabase,
gestione opere/edizioni separate e scheda libro dedicata.
"""

import streamlit as st
import io
import urllib.parse
import pandas as pd
from book_matching import find_book_candidates
from auth import require_login, get_current_user, sign_out
from library_db import (
    save_book_with_status, get_username,
    find_similar_works, create_work, get_work,
    get_book, get_editions_for_work, search_catalog_books, set_book_cover, set_book_page_count,
    add_to_user_library, get_user_book_entry, get_user_books,
    get_user_opinion, save_opinion, get_average_rating,
    split_authors, get_authors_for_work, link_authors_to_work,
    create_note, get_notes_for_book, delete_note,
    get_existing_titles, get_existing_authors, get_existing_publishers,
    get_user_tags, get_tags_for_work, add_tag_to_work, remove_tag_from_work, get_user_work_tags_map,
    rename_tag, delete_tag, import_wizard_save_candidate,
    save_import_progress, load_import_progress, clear_import_progress,
    get_user_links, add_link, delete_link, update_link, get_catalog_publishers,
)
from admin import (
    is_admin, get_stats, get_all_profiles, get_all_books, update_book, delete_book,
    get_pending_books, approve_book, reject_book,
)
from rating_widget import book_rating_input
from theme import inject_theme, status_badge, formato_badge, INK_GREEN, GOLD_LIGHT
from icons import BOOK_SVG, SEARCH_SVG, GEAR_SVG, UPLOAD_SVG, LINK_SVG

st.set_page_config(page_title="La mia libreria", page_icon="📚")
inject_theme()

require_login()
user = get_current_user()
user_is_admin = is_admin(user["id"])

def page_heading(svg: str, text: str):
    """Titolo di pagina con icona SVG (coerente con quelle della sidebar) invece di un'emoji."""
    big_svg = svg.replace('width="18" height="18"', 'width="28" height="28"')
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:12px; margin: 0.5rem 0 1rem;">'
        f'{big_svg}<h2 style="margin:0; font-family:\'EB Garamond\',Georgia,serif; '
        f'color:{INK_GREEN}; font-weight:600;">{text}</h2></div>',
        unsafe_allow_html=True,
    )


STATUS_OPTIONS = {
    "Letto": "letto",
    "In lettura": "in_lettura",
    "Comprato, non ancora letto": "comprato_non_letto",
    "Wishlist (vorrei leggerlo/acquistarlo)": "wishlist",
}


def status_selector(key_prefix: str) -> str:
    label = st.selectbox("Stato", options=list(STATUS_OPTIONS.keys()), key=f"{key_prefix}_status")
    return STATUS_OPTIONS[label]


# ---------------------------------------------------------------------------
# Flusso di salvataggio con risoluzione dell'opera (con conferma se ambigua)
# ---------------------------------------------------------------------------

def _resolve_author_names(book: dict) -> list[str]:
    """Preferisce la lista strutturata (authors_list) se presente, altrimenti scompone la stringa 'author'."""
    return book.get("authors_list") or split_authors(book.get("author"))


def start_add_flow(book: dict, status: str):
    """
    Cerca opere simili per titolo. Se non trova nulla, crea direttamente
    una nuova opera e salva. Se trova candidati, chiede conferma prima
    di procedere (per non unire per sbaglio libri diversi).
    """
    similar = find_similar_works(book.get("title", ""))
    if not similar:
        work_id = create_work(book.get("title"), _resolve_author_names(book))
        book_id = save_book_with_status(book, work_id, user["id"], status, auto_approve=user_is_admin)
        if book_id:
            st.session_state["last_added_book_id"] = book_id
            st.success(f"'{book['title']}' salvato nella tua libreria!")
    else:
        st.session_state["pending_add"] = {"book": book, "status": status, "candidates": similar}
        st.rerun()


def render_pending_add_confirmation():
    pending = st.session_state.get("pending_add")
    if not pending:
        return

    st.info(
        f"Abbiamo trovato opere con un titolo simile a **{pending['book']['title']}**. "
        "È una di queste (magari un'altra edizione), oppure è un'opera diversa?"
    )
    options = ["➕ È un'opera nuova, diversa da tutte"] + [
        f"{w['title']} — {w.get('author') or 'autore N/D'}" for w in pending["candidates"]
    ]
    choice = st.radio("Scegli", options, key="pending_add_choice")

    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button("✅ Conferma e salva"):
            author_names = _resolve_author_names(pending["book"])
            if choice == options[0]:
                work_id = create_work(pending["book"].get("title"), author_names)
            else:
                idx = options.index(choice) - 1
                work_id = pending["candidates"][idx]["id"]
                if author_names:
                    link_authors_to_work(work_id, author_names)

            book_id = save_book_with_status(pending["book"], work_id, user["id"], pending["status"], auto_approve=user_is_admin)
            if book_id:
                st.session_state["last_added_book_id"] = book_id
                st.success(f"'{pending['book']['title']}' salvato nella tua libreria!")
            del st.session_state["pending_add"]
            st.rerun()
    with col_cancel:
        if st.button("Annulla"):
            del st.session_state["pending_add"]
            st.rerun()


# ---------------------------------------------------------------------------
# Scheda libro: edizione in alto, altre edizioni sotto, opinione legata all'opera
# ---------------------------------------------------------------------------

def render_book_detail(book_id: str):
    book = get_book(book_id)
    if not book:
        st.error("Libro non trovato.")
        if st.button("← Indietro"):
            st.session_state.pop("detail_book_id", None)
            st.rerun()
        return

    if st.button("← Indietro"):
        st.session_state.pop("detail_book_id", None)
        st.rerun()

    work = get_work(book["work_id"]) if book.get("work_id") else None

    col1, col2 = st.columns([1, 3])
    with col1:
        st.markdown(
            """
            <style>
            .st-key-cover_col img { margin-top: 0.9rem; }
            </style>
            """,
            unsafe_allow_html=True,
        )
        with st.container(key="cover_col"):
            if book.get("cover_url"):
                st.image(book["cover_url"], width=150)
            else:
                st.write("🖼️ (nessuna copertina)")
                new_cover_url = st.text_input(
                    "Incolla qui l'URL di una copertina", key=f"detail_cover_input_{book_id}", placeholder="https://..."
                )
                if new_cover_url and st.button("Salva copertina", key=f"detail_cover_save_{book_id}"):
                    if set_book_cover(book_id, new_cover_url):
                        st.success("Copertina aggiunta!")
                        st.rerun()

        st.markdown("**🏷️ Tag**")
        current_tags = get_tags_for_work(user["id"], work["id"]) if work else []
        if current_tags:
            with st.container(key="tag_remove_buttons"):
                for tag in current_tags:
                    if st.button(f"✕ {tag['name']}", key=f"remove_tag_{tag['id']}"):
                        if remove_tag_from_work(user["id"], work["id"], tag["id"]):
                            st.rerun()
        else:
            st.caption("Nessun tag.")

        if work:
            all_user_tags = get_user_tags(user["id"])
            current_tag_ids = {t["id"] for t in current_tags}
            available_tags = [t for t in all_user_tags if t["id"] not in current_tag_ids]

            picked_tag = st.selectbox(
                "Aggiungi o crea un tag",
                [t["name"] for t in available_tags],
                index=None,
                placeholder="Scegli un tag esistente o scrivine uno nuovo...",
                accept_new_options=True,
                key=f"tag_select_{work['id']}",
                label_visibility="collapsed",
            )

            if picked_tag and st.button(f"➕ Aggiungi '{picked_tag}'", key=f"tag_add_select_{work['id']}", use_container_width=True):
                existing = next((t for t in available_tags if t["name"] == picked_tag), None)
                ok = (
                    add_tag_to_work(user["id"], work["id"], tag_id=existing["id"])
                    if existing
                    else add_tag_to_work(user["id"], work["id"], tag_name=picked_tag)
                )
                if ok:
                    st.rerun()
    with col2:
        st.title(book.get("title", "Titolo sconosciuto"))

        authors_display = book.get("author") or "Autore N/D"
        if work:
            linked_authors = get_authors_for_work(work["id"])
            if linked_authors:
                authors_display = ", ".join(a["name"] for a in linked_authors)

        st.caption(
            f"{authors_display} · "
            f"{book.get('publisher') or 'editore N/D'} · {book.get('year') or 'anno N/D'}"
        )

        entry = get_user_book_entry(user["id"], book_id) or {}
        current_status = entry.get("status") or "wishlist"
        current_formato = entry.get("formato")
        current_pages_read = entry.get("pages_read")

        current_label = next(l for l, v in STATUS_OPTIONS.items() if v == current_status)
        new_status_label = st.selectbox(
            "Il tuo stato per questa edizione",
            list(STATUS_OPTIONS.keys()),
            index=list(STATUS_OPTIONS.keys()).index(current_label),
            key=f"detail_status_{book_id}",
        )
        new_status = STATUS_OPTIONS[new_status_label]

        new_formato = current_formato
        formato_relevant = new_status in ("comprato_non_letto", "in_lettura", "letto")
        if formato_relevant:
            formato_options = {"Cartaceo": "cartaceo", "Digitale": "digitale", "Audiolibro": "audiolibro"}
            labels = list(formato_options.keys())
            current_formato_label = next(
                (l for l, v in formato_options.items() if v == current_formato), None
            )
            selected_label = st.selectbox(
                "In che formato?",
                ["Non specificato"] + labels,
                index=(labels.index(current_formato_label) + 1) if current_formato_label else 0,
                key=f"detail_formato_{book_id}",
            )
            new_formato = formato_options.get(selected_label)  # None se "Non specificato"

        # Progresso di lettura: serve il numero di pagine dell'edizione.
        # Se manca, permetto di aggiungerlo qui (come per la copertina).
        new_pages_read = current_pages_read
        pages_relevant = new_status in ("in_lettura", "letto")
        if pages_relevant:
            if not book.get("page_count"):
                st.caption("Numero di pagine non specificato per questa edizione:")
                missing_pages = st.number_input(
                    "Aggiungi il numero totale di pagine", min_value=0, step=1, key=f"detail_pagecount_{book_id}"
                )
                if missing_pages and st.button("Salva numero di pagine", key=f"detail_pagecount_save_{book_id}"):
                    if set_book_page_count(book_id, int(missing_pages)):
                        st.success("Numero di pagine salvato!")
                        st.rerun()
            else:
                total_pages = book["page_count"]
                widget_key = f"detail_pagesread_{book_id}"

                # Inizializzo lo stato del widget solo se non esiste ancora
                # per questa sessione, altrimenti Streamlit ignorerebbe il
                # valore calcolato qui sotto e terrebbe quello precedente.
                if widget_key not in st.session_state:
                    if new_status == "letto" and not current_pages_read:
                        # Non hai mai specificato pagine lette per un libro
                        # già segnato come letto: presumiamo l'abbia letto
                        # tutto (utile per l'import di libri letti in passato).
                        st.session_state[widget_key] = total_pages
                    else:
                        st.session_state[widget_key] = min(current_pages_read or 0, total_pages)

                new_pages_read = st.number_input(
                    "Pagine lette finora",
                    min_value=0,
                    max_value=total_pages,
                    step=1,
                    key=widget_key,
                )
                progress_fraction = new_pages_read / total_pages if total_pages else 0
                percent = round(progress_fraction * 100)
                st.progress(progress_fraction)
                st.caption(f"📖 {new_pages_read}/{total_pages} pagine ({percent}%)")

        if new_status != current_status or new_formato != current_formato or new_pages_read != current_pages_read:
            kwargs = {}
            if formato_relevant:
                kwargs["formato"] = new_formato
            if pages_relevant and book.get("page_count"):
                kwargs["pages_read"] = new_pages_read
            ok = add_to_user_library(user["id"], book_id, new_status, **kwargs)
            if ok:
                st.success("Aggiornato.")
                current_status = new_status
                st.rerun()

    if book.get("synopsis"):
        with st.expander("📖 Sinossi"):
            st.write(book["synopsis"])

    st.divider()
    st.markdown("**📝 Annotazioni** (citazioni, note su passaggi specifici)")

    notes = get_notes_for_book(user["id"], book_id)
    for note in notes:
        with st.container(border=True):
            if note.get("page_or_location"):
                st.caption(f"📍 {note['page_or_location']}")
            if note.get("quote_text"):
                st.markdown(f"> {note['quote_text']}")
            if note.get("comment"):
                st.write(note["comment"])
            if st.button("🗑️ Elimina", key=f"delete_note_{note['id']}"):
                if delete_note(note["id"]):
                    st.rerun()

    with st.expander("➕ Aggiungi un'annotazione"):
        with st.form(key=f"new_note_{book_id}", clear_on_submit=True):
            note_page = st.text_input("Pagina o posizione (opzionale)", placeholder="es. p. 42, cap. 3")
            note_quote = st.text_area("Citazione (opzionale)", height=80)
            note_comment = st.text_area("Il tuo commento (opzionale)", height=80)
            if st.form_submit_button("Salva annotazione"):
                if not note_page.strip() and not note_quote.strip() and not note_comment.strip():
                    st.error("Compila almeno un campo.")
                else:
                    if create_note(user["id"], book_id, note_quote.strip() or None, note_page.strip() or None, note_comment.strip() or None):
                        st.success("Annotazione salvata!")
                        st.rerun()

    # Altre edizioni della stessa opera, cliccabili
    if work:
        other_editions = get_editions_for_work(work["id"], exclude_book_id=book_id)
        if other_editions:
            st.divider()
            st.caption("📚 Altre edizioni di quest'opera:")
            cols = st.columns(min(len(other_editions), 4) or 1)
            for i, ed in enumerate(other_editions):
                with cols[i % len(cols)]:
                    label = f"{ed.get('publisher') or 'edizione'} ({ed.get('year') or 'N/D'})"
                    if st.button(label, key=f"switch_edition_{ed['id']}"):
                        st.session_state["detail_book_id"] = ed["id"]
                        st.rerun()

    st.divider()

    if not work:
        st.info("Questa edizione non è ancora collegata a un'opera: impossibile salvare un'opinione condivisa.")
        return

    avg = get_average_rating(work["id"])
    if avg:
        media, n = avg
        st.caption(f"📖 Media dei lettori: {media:.1f}/5 ({n} valutazion{'e' if n == 1 else 'i'})")

    if current_status != "letto":
        st.info("Segna questa edizione come 'Letto' qui sopra per poter valutare l'opera.")
        return

    st.markdown("**La tua opinione su quest'opera** (condivisa tra tutte le edizioni)")
    existing = get_user_opinion(user["id"], work["id"]) or {}

    rating = book_rating_input(key=f"detail_{work['id']}", default=existing.get("rating") or 0)

    recommended_options = ["Non esprimersi", "Sì", "No"]
    recommended_default = {True: "Sì", False: "No", None: "Non esprimersi"}.get(
        existing.get("recommended"), "Non esprimersi"
    )
    recommended_label = st.radio(
        "Lo consiglieresti?",
        recommended_options,
        index=recommended_options.index(recommended_default),
        horizontal=True,
        key=f"detail_recommended_{work['id']}",
    )
    recommended_value = {"Sì": True, "No": False, "Non esprimersi": None}[recommended_label]

    comment = st.text_area(
        "Commento (opzionale)", value=existing.get("comment") or "", key=f"detail_comment_{work['id']}"
    )

    if st.button("💾 Salva opinione", key=f"save_opinion_{work['id']}"):
        ok = save_opinion(user["id"], work["id"], rating or None, recommended_value, comment.strip() or None)
        if ok:
            st.success("Opinione salvata!")
            st.rerun()

    # Forziamo il ritorno in cima alla pagina, ora che tutto il contenuto
    # della scheda è stato disegnato (un tentativo fatto troppo presto non funzionava)
    st.components.v1.html(
        """
        <script>
        setTimeout(function() {
            window.parent.scrollTo(0, 0);
            var doc = window.parent.document;
            var main = doc.querySelector('section.main') || doc.querySelector('[data-testid="stAppViewContainer"]') || doc.body;
            if (main) { main.scrollTop = 0; }
        }, 100);
        </script>
        """,
        height=0,
    )


def _init_field_default(key: str, default_value: str):
    """Imposta un valore iniziale per un campo solo se non ne ha già uno in sessione."""
    if key not in st.session_state:
        st.session_state[key] = default_value


def _suggestion_picker(label: str, options: list[str], target_key: str, picker_key: str):
    """
    Menu a tendina con i valori già presenti nel catalogo; selezionandone uno,
    precompila il campo di testo collegato (target_key). Il campo resta comunque
    libero per scrivere un valore nuovo non ancora presente in lista.
    """
    NEW_VALUE_LABEL = "— scrivi un nuovo valore sotto —"
    choice = st.selectbox(label, [NEW_VALUE_LABEL] + options, key=picker_key)
    last_key = f"{picker_key}_last"
    if st.session_state.get(last_key) != choice:
        st.session_state[last_key] = choice
        if choice != NEW_VALUE_LABEL:
            st.session_state[target_key] = choice


def manual_entry_form(default_title: str = "", key_prefix: str = "manual"):
    """Form per inserire un'edizione a mano quando la ricerca automatica non la trova."""
    st.markdown("**Inserisci i dati manualmente**")

    status_label = st.selectbox(
        "Stato", options=list(STATUS_OPTIONS.keys()), key=f"{key_prefix}_status"
    )
    status_value = STATUS_OPTIONS[status_label]

    # Fuori dal form, così il numero di campi autore si aggiorna subito
    # quando cambi il numero, senza aspettare l'invio
    num_authors = st.number_input(
        "Quanti autori ha?", min_value=1, max_value=6, value=1, step=1, key=f"{key_prefix}_num_authors"
    )

    existing_titles = get_existing_titles()
    existing_authors = get_existing_authors()
    existing_publishers = get_existing_publishers()

    # Titolo: se arriva un default_title diverso da prima (es. nuova ricerca),
    # aggiorna il campo; altrimenti lascia quello che l'utente ha già scritto/scelto
    title_key = f"{key_prefix}_title"
    default_tracker_key = f"{key_prefix}_default_title_tracker"
    if st.session_state.get(default_tracker_key) != default_title:
        st.session_state[default_tracker_key] = default_title
        st.session_state[title_key] = default_title
    _suggestion_picker("Titolo già presente? (opzionale)", existing_titles, title_key, f"{key_prefix}_title_picker")

    author_keys = []
    for i in range(int(num_authors)):
        author_key = f"{key_prefix}_author_{i}"
        _init_field_default(author_key, "")
        label = "Autore già presente? (opzionale)" if num_authors == 1 else f"Autore {i + 1} già presente? (opzionale)"
        _suggestion_picker(label, existing_authors, author_key, f"{key_prefix}_author_picker_{i}")
        author_keys.append(author_key)

    publisher_key = f"{key_prefix}_publisher"
    _init_field_default(publisher_key, "")
    _suggestion_picker(
        "Casa editrice già presente? (opzionale)", existing_publishers, publisher_key, f"{key_prefix}_publisher_picker"
    )

    with st.form(key=f"{key_prefix}_form"):
        title = st.text_input("Titolo *", key=title_key)

        author_inputs = []
        for i in range(int(num_authors)):
            label = "Autore" if num_authors == 1 else f"Autore {i + 1}"
            author_inputs.append(st.text_input(label, key=author_keys[i]))

        col1, col2 = st.columns(2)
        with col1:
            isbn = st.text_input("ISBN (opzionale)")
            year = st.text_input("Anno (opzionale)")
            page_count_input = st.number_input(
                "Numero di pagine (opzionale, lascia 0 se non lo conosci)", min_value=0, step=1, value=0
            )
        with col2:
            publisher = st.text_input("Casa editrice (opzionale)", key=publisher_key)
            cover_url = st.text_input("URL copertina (opzionale)")

        synopsis = st.text_area("Sinossi (opzionale)", height=100)

        submitted = st.form_submit_button("Salva libro")

        if submitted:
            if not title.strip():
                st.error("Il titolo è obbligatorio.")
                return False

            author_names = [a.strip() for a in author_inputs if a.strip()]

            book = {
                "title": title.strip(),
                "author": ", ".join(author_names) or None,
                "authors_list": author_names,
                "isbn": isbn.strip() or None,
                "year": year.strip() or None,
                "publisher": publisher.strip() or None,
                "cover_url": cover_url.strip() or None,
                "synopsis": synopsis.strip() or None,
                "page_count": int(page_count_input) or None,
                "source_api": "manuale",
                "external_id": None,
            }
            start_add_flow(book, status_value)
            return True
    return False


# ============================================================
# LAYOUT PAGINA
# ============================================================

def render_tag_management(user_id: str, key_prefix: str):
    """Elenco dei tag dell'utente con possibilità di rinominarli o eliminarli. Riutilizzabile ovunque."""
    my_tags = get_user_tags(user_id)
    if not my_tags:
        st.caption("Non hai ancora creato nessun tag.")
        return
    for tag in my_tags:
        with st.form(key=f"{key_prefix}_tag_edit_{tag['id']}"):
            col_name, col_save, col_delete = st.columns([3, 1, 1])
            with col_name:
                new_name = st.text_input(
                    "Nome", value=tag["name"], key=f"{key_prefix}_tag_name_{tag['id']}", label_visibility="collapsed"
                )
            with col_save:
                if st.form_submit_button("💾 Rinomina", use_container_width=True):
                    if new_name.strip() and rename_tag(tag["id"], new_name.strip()):
                        st.success("Rinominato.")
                        st.rerun()
            with col_delete:
                if st.form_submit_button("🗑️ Elimina", use_container_width=True):
                    if delete_tag(tag["id"]):
                        st.success("Eliminato.")
                        st.rerun()


def render_admin_panel():
    page_heading(GEAR_SVG, "Pannello admin")
    st.markdown("**Statistiche generali**")
    stats = get_stats()
    cols = st.columns(len(stats))
    for col, (label, value) in zip(cols, stats.items()):
        col.metric(label, value)

    st.divider()
    st.markdown("**Utenti registrati**")
    for p in get_all_profiles():
        admin_tag = " 🛠️" if p.get("is_admin") else ""
        st.write(f"- {p.get('username', 'N/D')}{admin_tag} · registrato il {p.get('created_at', '')[:10]}")

    st.divider()
    st.markdown("**📝 Libri in attesa di approvazione**")
    pending = get_pending_books()
    if not pending:
        st.caption("Nessun libro in attesa al momento.")
    for b in pending:
        col_info, col_approve, col_reject = st.columns([3, 1, 1])
        with col_info:
            st.write(f"**{b.get('title')}** — {b.get('author') or 'autore N/D'}")
            st.caption(f"creato il {b.get('created_at', '')[:10]}")
        with col_approve:
            if st.button("✅ Approva", key=f"approve_{b['id']}"):
                if approve_book(b["id"]):
                    st.success("Approvato.")
                    st.rerun()
        with col_reject:
            if st.button("🚫 Rifiuta", key=f"reject_{b['id']}"):
                if reject_book(b["id"]):
                    st.info("Rifiutato.")
                    st.rerun()

    st.divider()
    with st.expander("🏷️ Gestione tag (rinomina o elimina i tuoi tag)"):
        render_tag_management(user["id"], key_prefix="admin")

    st.divider()
    with st.expander("🔗 Gestione link utili (modifica o elimina)"):
        render_link_management(user["id"])

    st.divider()
    st.markdown("**Gestione catalogo libri** (correzioni, unione duplicati)")
    book_search = st.text_input("Cerca un libro nel catalogo da modificare", key="admin_book_search")
    if book_search:
        for b in get_all_books(search=book_search):
            with st.form(key=f"admin_edit_{b['id']}"):
                st.write(f"ID: `{b['id']}`")
                new_title = st.text_input("Titolo", value=b.get("title") or "", key=f"admin_title_{b['id']}")
                new_author = st.text_input(
                    "Autore (testo visualizzato per questa edizione)",
                    value=b.get("author") or "", key=f"admin_author_{b['id']}",
                )
                st.caption(
                    "⚠️ Questo campo cambia solo il testo mostrato per questa edizione, "
                    "non il collegamento agli autori dell'opera (work_authors)."
                )
                col1, col2 = st.columns(2)
                with col1:
                    new_publisher = st.text_input("Editore", value=b.get("publisher") or "", key=f"admin_publisher_{b['id']}")
                    new_isbn = st.text_input("ISBN", value=b.get("isbn") or "", key=f"admin_isbn_{b['id']}")
                    new_page_count = st.number_input(
                        "Numero di pagine", min_value=0, step=1,
                        value=b.get("page_count") or 0, key=f"admin_pagecount_{b['id']}",
                    )
                with col2:
                    new_year = st.text_input("Anno", value=b.get("year") or "", key=f"admin_year_{b['id']}")
                    new_cover_url = st.text_input("URL copertina", value=b.get("cover_url") or "", key=f"admin_cover_{b['id']}")
                new_synopsis = st.text_area("Sinossi", value=b.get("synopsis") or "", key=f"admin_synopsis_{b['id']}", height=80)

                col_save, col_delete = st.columns(2)
                with col_save:
                    if st.form_submit_button("💾 Salva modifiche"):
                        updates = {
                            "title": new_title,
                            "author": new_author or None,
                            "publisher": new_publisher or None,
                            "isbn": new_isbn or None,
                            "year": new_year or None,
                            "cover_url": new_cover_url or None,
                            "synopsis": new_synopsis or None,
                            "page_count": int(new_page_count) or None,
                        }
                        if update_book(b["id"], updates):
                            st.success("Aggiornato.")
                            st.rerun()
                with col_delete:
                    if st.form_submit_button("🗑️ Elimina libro"):
                        if delete_book(b["id"]):
                            st.success("Eliminato.")
                            st.rerun()
            st.divider()


FORMATO_LABELS = {"cartaceo": "Cartaceo", "digitale": "Digitale", "audiolibro": "Audiolibro"}

# Etichette brevi per i badge nella griglia (quella completa, usata nel filtro
# e nel selettore di stato, resta più descrittiva perché lì serve chiarezza)
STATUS_BADGE_LABELS = {
    "wishlist": "Wishlist",
    "comprato_non_letto": "Comprato, non letto",
    "in_lettura": "In lettura",
    "letto": "Letto",
}


def render_my_library():
    page_heading(BOOK_SVG, "La mia libreria")

    all_entries = get_user_books(user["id"])

    if not all_entries:
        st.info("Non hai ancora aggiunto nessun libro. Vai su '🔍 Cerca e aggiungi' per iniziare.")
        return

    counts = {}
    for e in all_entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1

    cols = st.columns(len(STATUS_OPTIONS))
    for col, (label, value) in zip(cols, STATUS_OPTIONS.items()):
        col.metric(label.split(" (")[0], counts.get(value, 0))

    st.divider()

    # Se il bottone "✕" è stato premuto al giro precedente, svuota il campo
    # PRIMA che venga creato in questo giro (non si può farlo dopo)
    if st.session_state.get("_clear_library_search"):
        st.session_state["library_search"] = ""
        st.session_state["_clear_library_search"] = False

    col_search, col_clear = st.columns([6, 1])
    with col_search:
        search_query = st.text_input(
            "🔍 Cerca per titolo o autore", key="library_search", placeholder="Scrivi per filtrare..."
        )
    with col_clear:
        st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True)  # allinea il bottone col campo
        if st.button("✕", key="clear_library_search_btn"):
            st.session_state["_clear_library_search"] = True
            st.rerun()

    status_filter_options = ["Tutti"] + list(STATUS_OPTIONS.keys())
    selected_filter = st.radio("Filtra per stato", status_filter_options, horizontal=True, key="library_filter")

    if selected_filter == "Tutti":
        entries = all_entries
    else:
        target_status = STATUS_OPTIONS[selected_filter]
        entries = [e for e in all_entries if e.get("status") == target_status]

    if search_query.strip():
        q = search_query.strip().lower()
        entries = [
            e for e in entries
            if q in ((e.get("books") or {}).get("title") or "").lower()
            or q in ((e.get("books") or {}).get("author") or "").lower()
        ]

    user_tags = get_user_tags(user["id"])
    if user_tags:
        selected_tag_names = st.multiselect(
            "Filtra per tag", [t["name"] for t in user_tags], key="library_tag_filter"
        )
        if selected_tag_names:
            selected_tag_ids = {t["id"] for t in user_tags if t["name"] in selected_tag_names}
            work_tags_map = get_user_work_tags_map(user["id"])
            entries = [
                e for e in entries
                if work_tags_map.get((e.get("books") or {}).get("work_id"), set()) & selected_tag_ids
            ]

        with st.expander("🏷️ Gestisci i miei tag (rinomina o elimina)"):
            render_tag_management(user["id"], key_prefix="mylib")

    if not entries:
        st.info("Nessun libro corrisponde alla ricerca/filtro.")
        return

    # Se il bottone di reset è stato premuto al giro precedente, riporta
    # l'ordinamento a "Nessun ordinamento" PRIMA che il widget venga creato
    if st.session_state.get("_reset_library_sort"):
        st.session_state["library_sort"] = "Nessun ordinamento"
        st.session_state["_reset_library_sort"] = False

    with st.expander("⚙️ Opzioni di visualizzazione"):
        view_mode = st.radio("Visualizzazione", ["Griglia", "Elenco"], horizontal=True, key="library_view_mode")
        st.caption("💡 Passa a 'Elenco' per esportare o condividere i titoli dei tuoi libri.")

        col_sort, col_reset = st.columns([4, 1])
        with col_sort:
            sort_option = st.selectbox(
                "Ordina per",
                [
                    "Nessun ordinamento",
                    "Titolo (A-Z)",
                    "Autore (A-Z)",
                    "Anno di pubblicazione (dal più antico)",
                    "Anno di pubblicazione (dal più recente)",
                ],
                key="library_sort",
            )
        with col_reset:
            st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True)
            if st.button("🔄", key="reset_library_sort_btn", help="Ripristina ordinamento"):
                st.session_state["_reset_library_sort"] = True
                st.rerun()

    if sort_option == "Titolo (A-Z)":
        entries = sorted(entries, key=lambda e: ((e.get("books") or {}).get("title") or "").lower())
    elif sort_option == "Autore (A-Z)":
        entries = sorted(entries, key=lambda e: ((e.get("books") or {}).get("author") or "").lower())
    elif sort_option in ("Anno di pubblicazione (dal più antico)", "Anno di pubblicazione (dal più recente)"):
        with_year = [e for e in entries if (e.get("books") or {}).get("year")]
        without_year = [e for e in entries if not (e.get("books") or {}).get("year")]
        reverse = sort_option == "Anno di pubblicazione (dal più recente)"
        with_year = sorted(with_year, key=lambda e: (e.get("books") or {}).get("year"), reverse=reverse)
        entries = with_year + without_year  # i libri senza anno restano sempre in fondo

    if view_mode == "Elenco":
        share_text = "\n".join(
            f"{(e.get('books') or {}).get('title', 'Titolo sconosciuto')} — "
            f"{(e.get('books') or {}).get('author') or 'Autore N/D'}"
            for e in entries
        )
        telegram_url = "https://t.me/share/url?text=" + urllib.parse.quote(share_text)
        whatsapp_url = "https://wa.me/?text=" + urllib.parse.quote(share_text)

        df = pd.DataFrame([
            {
                "Titolo": (e.get("books") or {}).get("title", ""),
                "Autore": (e.get("books") or {}).get("author") or "",
            }
            for e in entries
        ])
        excel_buffer = io.BytesIO()
        df.to_excel(excel_buffer, index=False, engine="openpyxl")

        col_telegram, col_whatsapp = st.columns(2)
        with col_telegram:
            st.link_button("📤 Telegram", telegram_url, use_container_width=True)
        with col_whatsapp:
            st.link_button("📤 WhatsApp", whatsapp_url, use_container_width=True)

        with st.expander("Altre opzioni di condivisione"):
            st.caption("Per condividere altrove (es. Instagram), copia il testo con l'icona qui sotto:")
            st.code(share_text, language=None)

        st.download_button(
            "⬇️ Scarica in Excel",
            data=excel_buffer.getvalue(),
            file_name="la_mia_libreria.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        st.divider()

        for entry in entries:
            book = entry.get("books") or {}
            author = book.get("author") or "Autore N/D"
            st.write(f"**{book.get('title', 'Titolo sconosciuto')}** — {author}")

        return

    cols_per_row = 3
    cols = st.columns(cols_per_row)
    for i, entry in enumerate(entries):
        book = entry.get("books") or {}
        with cols[i % cols_per_row]:
            with st.container(border=True):
                if book.get("cover_url"):
                    st.image(book["cover_url"], use_container_width=True)
                else:
                    st.write("🖼️")

                st.markdown(f"**{book.get('title', 'Titolo sconosciuto')}**")
                status_label = STATUS_BADGE_LABELS.get(entry.get("status"), entry.get("status"))
                st.caption(book.get("author") or "Autore N/D")

                badges_html = status_badge(status_label)
                formato_label = FORMATO_LABELS.get(entry.get("formato"))
                if formato_label:
                    badges_html += " " + formato_badge(formato_label)
                st.markdown(badges_html, unsafe_allow_html=True)

                if entry.get("status") == "in_lettura" and entry.get("pages_read") and book.get("page_count"):
                    percent = round(entry["pages_read"] / book["page_count"] * 100)
                    st.progress(entry["pages_read"] / book["page_count"])
                    st.caption(f"📖 {entry['pages_read']}/{book['page_count']} pagine ({percent}%)")

                if st.button("📖 Apri scheda", key=f"mylib_open_{entry['id']}", use_container_width=True):
                    st.session_state["detail_book_id"] = book.get("id")
                    st.rerun()

        # A ogni fine riga (o all'ultimo libro), aggiungo un po' di spazio verticale
        if (i + 1) % cols_per_row == 0 or i == len(entries) - 1:
            st.write("")


def _favicon_url(url: str) -> str:
    """Piccola icona del sito (favicon), recuperata automaticamente per qualsiasi indirizzo reale."""
    domain = urllib.parse.urlparse(url).netloc or url
    return f"https://www.google.com/s2/favicons?sz=128&domain={domain}"


DEFAULT_USEFUL_LINKS = [
    ("Librerie indipendenti", "Il Libraio", "https://www.illibraio.it"),
    ("Librerie indipendenti", "AbeBooks", "https://www.abebooks.it"),
    ("Biblioteche", "OPAC SBN", "https://opac.sbn.it"),
]


def render_useful_links():
    page_heading(LINK_SVG, "Link utili")

    my_links = get_user_links(user["id"])
    existing_names = {l["name"].lower() for l in my_links}

    missing_defaults = [d for d in DEFAULT_USEFUL_LINKS if d[1].lower() not in existing_names]
    if missing_defaults:
        st.caption("Link suggeriti, non ancora aggiunti:")
        cols = st.columns(len(missing_defaults))
        for col, (category, name, url) in zip(cols, missing_defaults):
            with col:
                if st.button(f"➕ {name}", key=f"quickadd_{name}", use_container_width=True):
                    if add_link(user["id"], category, name, url, _favicon_url(url)):
                        st.rerun()
        st.divider()

    if my_links:
        by_category = {}
        for l in my_links:
            by_category.setdefault(l["category"], []).append(l)

        cards_per_row = 4
        for category, links in by_category.items():
            st.markdown(f"**{category}**")
            cols = st.columns(cards_per_row)
            for i, l in enumerate(links):
                with cols[i % cards_per_row]:
                    with st.container(border=True):
                        logo = l.get("logo_url")
                        if logo:
                            st.markdown(
                                f'<div style="text-align:center; margin-bottom:0.6rem;"><img src="{logo}" width="64"></div>',
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                '<div style="text-align:center; margin-bottom:0.6rem;">🔗</div>',
                                unsafe_allow_html=True,
                            )
                        st.markdown(
                            f'<p style="text-align:center; font-weight:600; margin-bottom:0.6rem;">{l["name"]}</p>',
                            unsafe_allow_html=True,
                        )
                        st.link_button("Apri", l["url"], use_container_width=True)
            st.write("")
    else:
        st.caption("Non hai ancora aggiunto nessun link.")

    st.divider()
    with st.expander("➕ Aggiungi un link"):
        existing_categories = sorted({l["category"] for l in my_links})
        with st.form(key="add_link_form", clear_on_submit=True):
            category = st.selectbox(
                "Categoria",
                existing_categories,
                index=None,
                placeholder="Scegli una categoria esistente o scrivine una nuova...",
                accept_new_options=True,
            )
            name = st.text_input("Nome")
            url = st.text_input("URL", placeholder="https://...")
            logo_override = st.text_input(
                "URL del logo (opzionale)",
                placeholder="Lascia vuoto per usare automaticamente la favicon del sito",
            )
            if st.form_submit_button("Salva link"):
                if not category or not category.strip() or not name.strip() or not url.strip():
                    st.error("Compila almeno categoria, nome e URL.")
                else:
                    final_url = url.strip()
                    if not final_url.startswith("http"):
                        final_url = "https://" + final_url
                    final_logo = logo_override.strip() or _favicon_url(final_url)
                    if add_link(user["id"], category.strip(), name.strip(), final_url, final_logo):
                        st.success("Link salvato!")
                        st.rerun()


def render_link_management(user_id: str):
    """Modifica/eliminazione dei link utili - vive nel pannello admin."""
    my_links = get_user_links(user_id)
    if not my_links:
        st.caption("Non hai ancora aggiunto nessun link.")
        return
    for l in my_links:
        with st.form(key=f"admin_link_edit_{l['id']}"):
            st.write(f"**{l['name']}** — *{l['category']}*")
            new_url = st.text_input("URL", value=l["url"], key=f"admin_link_url_{l['id']}")
            new_logo = st.text_input(
                "Logo (opzionale)", value=l.get("logo_url") or "", key=f"admin_link_logo_{l['id']}"
            )
            col_save, col_delete = st.columns(2)
            with col_save:
                if st.form_submit_button("💾 Salva", use_container_width=True):
                    final_logo = new_logo.strip() or _favicon_url(new_url)
                    if update_link(l["id"], url=new_url, logo_url=final_logo):
                        st.success("Aggiornato.")
                        st.rerun()
            with col_delete:
                if st.form_submit_button("🗑️ Elimina", use_container_width=True):
                    if delete_link(l["id"]):
                        st.success("Eliminato.")
                        st.rerun()
        st.divider()


def render_import():
    page_heading(UPLOAD_SVG, "Importa libri")

    # Se è in corso un import guidato in questa sessione, mostriamo quello
    if st.session_state.get("import_queue_active"):
        _render_import_queue()
        return

    # Altrimenti controlliamo se c'è un import salvato da riprendere
    # (es. dopo aver chiuso la pagina o riavviato Streamlit)
    saved = load_import_progress(user["id"])
    if saved:
        st.info(
            f"Hai un import in corso, salvato a metà: "
            f"{saved['current_index']}/{len(saved['rows'])} libri già processati."
        )
        col_resume, col_discard = st.columns(2)
        with col_resume:
            if st.button("▶️ Riprendi import", use_container_width=True):
                st.session_state["import_queue_rows"] = saved["rows"]
                st.session_state["import_queue_index"] = saved["current_index"]
                st.session_state["import_queue_imported"] = saved["imported_count"]
                st.session_state["import_queue_skipped"] = saved["skipped"]
                st.session_state["import_queue_status"] = saved["status_value"]
                st.session_state["import_queue_active"] = True
                st.rerun()
        with col_discard:
            if st.button("🗑️ Scarta e ricomincia da capo", use_container_width=True):
                clear_import_progress(user["id"])
                st.rerun()
        return

    st.write(
        "Carica un file Excel (anche con più fogli, uno per categoria). Per ogni "
        "libro cercheremo automaticamente i dati nelle tre fonti (Google Books, SBN, "
        "OpenLibrary): dovrai solo confermare il risultato giusto, libro per libro. "
        "I libri per cui non trovi un match corretto restano in un elenco da inserire a mano dopo."
    )

    uploaded_file = st.file_uploader("File Excel (.xlsx)", type=["xlsx", "xls"])

    sheets_data = None
    if uploaded_file:
        try:
            xls = pd.ExcelFile(uploaded_file)
            sheets_data = {name: xls.parse(name) for name in xls.sheet_names}
        except Exception as e:
            st.error(f"Errore nella lettura del file: {e}")

    if not sheets_data:
        return

    st.success(f"Trovati {len(sheets_data)} fogli: {', '.join(sheets_data.keys())}")

    first_df = next(iter(sheets_data.values()))
    columns = list(first_df.columns)

    col1, col2 = st.columns(2)
    with col1:
        title_col = st.selectbox("Colonna del titolo", columns, key="import_title_col")
    with col2:
        author_col = st.selectbox("Colonna dell'autore", columns, key="import_author_col")

    status_options_list = list(STATUS_OPTIONS.keys())
    default_index = status_options_list.index("Letto") if "Letto" in status_options_list else 0
    status_label = st.selectbox(
        "Stato da assegnare a tutti i libri importati",
        status_options_list, index=default_index, key="import_status",
    )
    status_value = STATUS_OPTIONS[status_label]

    all_rows = []
    for sheet_name, df in sheets_data.items():
        if title_col not in df.columns:
            st.warning(f"Il foglio '{sheet_name}' non ha la colonna '{title_col}': verrà saltato.")
            continue
        for _, row in df.iterrows():
            title = str(row.get(title_col, "")).strip()
            if not title or title.lower() == "nan":
                continue
            author = str(row.get(author_col, "")).strip() if author_col in df.columns else ""
            if author.lower() == "nan":
                author = ""
            all_rows.append({"title": title, "author": author or None})

    st.write(f"**{len(all_rows)} libri pronti per l'import.**")
    with st.expander("Anteprima (prime 20 righe)"):
        st.dataframe(pd.DataFrame(all_rows).head(20), use_container_width=True)

    if st.button("🚀 Avvia import guidato", type="primary"):
        st.session_state["import_queue_rows"] = all_rows
        st.session_state["import_queue_index"] = 0
        st.session_state["import_queue_imported"] = 0
        st.session_state["import_queue_skipped"] = []
        st.session_state["import_queue_status"] = status_value
        st.session_state["import_queue_active"] = True
        save_import_progress(user["id"], all_rows, 0, 0, [], status_value)
        st.rerun()


def _render_import_queue():
    rows = st.session_state["import_queue_rows"]
    index = st.session_state["import_queue_index"]
    total = len(rows)
    status_value = st.session_state["import_queue_status"]

    if index >= total:
        _render_import_summary()
        return

    current = rows[index]
    st.progress(index / total if total else 1.0)
    st.caption(f"Libro {index + 1} di {total}")
    label = current["title"] + (f" — {current['author']}" if current["author"] else "")
    st.markdown(f"**Sto cercando:** {label}")

    cache_key = f"import_candidates_{index}"
    if cache_key not in st.session_state:
        query = f"{current['title']} {current['author'] or ''}".strip()
        with st.spinner("Ricerca in corso..."):
            st.session_state[cache_key] = find_book_candidates(query)
    candidates = st.session_state[cache_key]

    def _advance(skipped=False):
        if skipped:
            st.session_state["import_queue_skipped"].append(current)
        else:
            st.session_state["import_queue_imported"] += 1
        st.session_state.pop(cache_key, None)
        st.session_state["import_queue_index"] += 1
        save_import_progress(
            user["id"],
            rows,
            st.session_state["import_queue_index"],
            st.session_state["import_queue_imported"],
            st.session_state["import_queue_skipped"],
            status_value,
        )
        st.rerun()

    if not candidates:
        st.warning("Nessun risultato trovato per questo libro.")
    else:
        for i, book in enumerate(candidates):
            col1, col2 = st.columns([1, 4])
            with col1:
                if book.get("cover_url"):
                    st.image(book["cover_url"], width=80)
                else:
                    st.write("🖼️")
            with col2:
                st.markdown(f"**{book.get('title', 'Titolo sconosciuto')}**")
                st.caption(
                    f"{book.get('author') or 'Autore N/D'} · {book.get('year') or 'anno N/D'} · "
                    f"{book.get('publisher') or 'editore N/D'}"
                )
                st.caption(f"Fonte: {book['source_api']}")
                if book.get("synopsis"):
                    with st.expander("📖 Leggi la sinossi"):
                        st.write(book["synopsis"])
                if st.button("✅ Scegli questo", key=f"import_pick_{index}_{i}"):
                    import_wizard_save_candidate(book, user["id"], status_value, user_is_admin)
                    _advance(skipped=False)
            st.divider()

    if st.button("🚫 Nessuno di questi è giusto: salta (lo inserirò a mano)", key=f"import_skip_{index}"):
        _advance(skipped=True)


def _render_import_summary():
    imported = st.session_state["import_queue_imported"]
    skipped = st.session_state["import_queue_skipped"]

    clear_import_progress(user["id"])  # import completato: non serve più il salvataggio

    st.success(f"✅ Import completato! {imported} libri importati, {len(skipped)} da inserire a mano.")

    if skipped:
        df_skipped = pd.DataFrame(skipped).rename(columns={"title": "Titolo", "author": "Autore"})
        st.markdown("**Libri saltati:**")
        st.dataframe(df_skipped, use_container_width=True)

        excel_buffer = io.BytesIO()
        df_skipped.to_excel(excel_buffer, index=False, engine="openpyxl")
        st.download_button(
            "⬇️ Scarica l'elenco dei libri saltati",
            data=excel_buffer.getvalue(),
            file_name="libri_da_inserire_a_mano.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if st.button("🔄 Nuovo import"):
        for key in ["import_queue_rows", "import_queue_index", "import_queue_imported",
                    "import_queue_skipped", "import_queue_status", "import_queue_active"]:
            st.session_state.pop(key, None)
        st.rerun()



def render_search_and_add():
    page_heading(SEARCH_SVG, "Cerca e aggiungi")
    query = st.text_input("Titolo (e opzionalmente autore)", placeholder="es. Notre-Dame de Paris Victor Hugo")

    if query:
        catalog_matches = search_catalog_books(query)
        if catalog_matches:
            st.markdown("**📚 Già nel catalogo:**")
            for cb in catalog_matches:
                col1, col2 = st.columns([1, 4])
                with col1:
                    if cb.get("cover_url"):
                        st.image(cb["cover_url"], width=80)
                    else:
                        st.write("🖼️")
                with col2:
                    st.markdown(f"**{cb.get('title')}**")
                    st.caption(f"{cb.get('author') or 'Autore N/D'} · {cb.get('publisher') or 'editore N/D'} · {cb.get('year') or 'anno N/D'}")
                    status = status_selector(key_prefix=f"catalog_{cb['id']}")
                    col_add, col_open = st.columns(2)
                    with col_add:
                        if st.button("Aggiungi alla libreria", key=f"addlib_catalog_{cb['id']}"):
                            if add_to_user_library(user["id"], cb["id"], status):
                                st.success(f"'{cb['title']}' salvato nella tua libreria!")
                    with col_open:
                        if st.button("📖 Apri scheda", key=f"catalog_open_{cb['id']}"):
                            st.session_state["detail_book_id"] = cb["id"]
                            st.rerun()
                st.divider()
            st.caption("Nessuno di questi ti convince? Sotto trovi anche i risultati da Google Books/OpenLibrary.")

        with st.spinner("Ricerca in corso..."):
            candidates = find_book_candidates(query)

        if not candidates:
            st.warning("Nessun risultato trovato tramite ricerca automatica.")
            st.info("Puoi comunque inserire questo libro a mano qui sotto:")
            manual_entry_form(default_title=query, key_prefix="fallback")
        else:
            st.write(f"Trovati {len(candidates)} risultati:")
            for i, book in enumerate(candidates):
                col1, col2 = st.columns([1, 4])
                with col1:
                    cover_key = f"cover_override_{i}"
                    current_cover = st.session_state.get(cover_key) or book.get("cover_url")
                    if current_cover:
                        st.image(current_cover, width=80)
                    else:
                        st.write("🖼️ (nessuna copertina)")
                with col2:
                    st.markdown(f"**{book.get('title', 'Titolo sconosciuto')}**")
                    st.caption(f"{book.get('author', 'Autore N/D')} · {book.get('year', 'anno N/D')} · {book.get('publisher', 'editore N/D')}")
                    st.caption(f"Fonte: {book['source_api']}")

                    if not book.get("cover_url"):
                        cover_url_input = st.text_input(
                            "Incolla qui l'URL di una copertina (opzionale)",
                            key=f"cover_input_{i}", placeholder="https://...",
                        )
                        if cover_url_input:
                            st.session_state[cover_key] = cover_url_input

                    if book.get("synopsis"):
                        with st.expander("📖 Leggi la sinossi"):
                            st.write(book["synopsis"])
                    else:
                        manual_synopsis = st.text_area(
                            "Sinossi non disponibile per questa fonte — scrivila tu (opzionale)",
                            key=f"synopsis_input_{i}", height=80,
                        )

                    status = status_selector(key_prefix=f"result_{i}")

                    if st.button("Aggiungi alla libreria", key=f"addlib_result_{i}"):
                        final_cover = st.session_state.get(cover_key) or book.get("cover_url")
                        final_synopsis = book.get("synopsis") or manual_synopsis.strip() or None
                        book_to_save = {**book, "cover_url": final_cover, "synopsis": final_synopsis}
                        start_add_flow(book_to_save, status)
                st.divider()

            st.caption("Nessuno di questi corrisponde a quello che cerchi?")
            with st.expander("➕ Inserisci il libro manualmente"):
                manual_entry_form(default_title=query, key_prefix="manual_alt")

    st.divider()
    with st.expander("➕ Aggiungi un libro manualmente (senza cercare)"):
        manual_entry_form(key_prefix="manual_direct")

    if st.session_state.get("last_added_book_id"):
        if st.button("📖 Apri la scheda dell'ultimo libro salvato", key="open_last_added"):
            st.session_state["detail_book_id"] = st.session_state["last_added_book_id"]
            st.rerun()


# ============================================================
# LAYOUT PAGINA con menu laterale
# ============================================================

# ============================================================
# LAYOUT PAGINA con menu laterale (link con icone SVG vere)
# ============================================================

username = get_username(user["id"]) or user["email"]
current_nav = st.query_params.get("nav", "libreria")

NAV_LINK_STYLE = (
    "display:flex; align-items:center; gap:10px; padding:8px 12px; "
    "border-radius:8px; text-decoration:none; margin-bottom:4px; "
    f"font-family:'EB Garamond',Georgia,serif; font-size:16px; color:{INK_GREEN};"
)
NAV_LINK_ACTIVE_STYLE = NAV_LINK_STYLE + f"background:{GOLD_LIGHT}; font-weight:600;"

with st.sidebar:
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:10px; margin-bottom:0.5rem;">'
        f'{BOOK_SVG}<span style="font-family:\'EB Garamond\',Georgia,serif; font-size:28px; '
        f'font-weight:600; color:{INK_GREEN};">Libri</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(f"👤 {username}")
    if st.button("Esci"):
        sign_out()
        st.rerun()

    st.divider()

    nav_links = [
        ("libreria", "La mia libreria", BOOK_SVG),
        ("cerca", "Cerca e aggiungi", SEARCH_SVG),
        ("importa", "Importa libri", UPLOAD_SVG),
        ("link", "Link utili", LINK_SVG),
    ]
    if user_is_admin:
        nav_links.append(("admin", "Admin", GEAR_SVG))

    for key, label, svg in nav_links:
        style = NAV_LINK_ACTIVE_STYLE if current_nav == key else NAV_LINK_STYLE
        st.markdown(f'<a href="?nav={key}" target="_self" style="{style}">{svg} {label}</a>', unsafe_allow_html=True)

# Un link cliccato ricarica la pagina: la scheda libro eventualmente aperta
# si chiude automaticamente insieme al resto dello stato non salvato.
render_pending_add_confirmation()

if st.session_state.get("detail_book_id"):
    render_book_detail(st.session_state["detail_book_id"])
elif current_nav == "admin" and user_is_admin:
    render_admin_panel()
elif current_nav == "cerca":
    render_search_and_add()
elif current_nav == "importa":
    render_import()
elif current_nav == "link":
    render_useful_links()
else:
    render_my_library()
