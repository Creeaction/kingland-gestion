"""
KingLand Gestion — outil interne de suivi (factures, coûts, recrutement).
Studio à deux (Arkhion Studio). Lance-le avec :  streamlit run app.py
"""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from db import (
    SessionLocal, init_db,
    Facture, Offre, Candidature,
    CATEGORIES, STATUTS_FACTURE, TYPES_POSTE, STATUTS_OFFRE,
    STATUTS_CANDIDATURE, MOYENS_PAIEMENT,
    get_setting, set_setting,
    list_users, create_user, delete_user, check_login,
    backend_label,
)
from ai_extract import extract_facture

st.set_page_config(page_title="KingLand Gestion", page_icon="🛡️", layout="wide")
init_db()


# ------------------------------------------------------------------ #
#  Authentification (2 personnes, mots de passe dans les secrets)
# ------------------------------------------------------------------ #
def _users() -> dict:
    """Récupère les identifiants depuis les secrets Streamlit.
    Format attendu dans .streamlit/secrets.toml :

        [auth]
        esteban = "monMotDePasse"
        associe = "autreMotDePasse"

    À défaut, un couple de test est fourni (À CHANGER)."""
    try:
        return dict(st.secrets["auth"])
    except Exception:
        return {"esteban": "kingland", "associe": "kingland"}


def login_gate() -> str | None:
    if st.session_state.get("user"):
        return st.session_state["user"]

    st.markdown("## 🛡️ KingLand — Gestion du projet")
    st.caption("Espace privé Arkhion Studio")
    with st.form("login"):
        u = st.text_input("Identifiant").strip().lower()
        p = st.text_input("Mot de passe", type="password")
        ok = st.form_submit_button("Se connecter")
    if ok:
        # 1) comptes créés en base  2) comptes des secrets (secours)
        disp = check_login(u, p)
        if not disp:
            users = _users()
            if u in users and str(users[u]) == p:
                disp = u.capitalize()
        if disp:
            st.session_state["user"] = disp
            st.rerun()
        else:
            st.error("Identifiant ou mot de passe incorrect.")
    return None


# ------------------------------------------------------------------ #
#  Helpers données
# ------------------------------------------------------------------ #
@st.cache_data(ttl=300, show_spinner=False)
def factures_df() -> pd.DataFrame:
    with SessionLocal() as s:
        rows = s.query(Facture).order_by(Facture.date_facture.desc()).all()
        data = [{
            "id": f.id, "Date": f.date_facture, "Fournisseur": f.fournisseur,
            "Catégorie": f.categorie, "Description": f.description,
            "Montant HT": f.montant_ht, "TVA %": f.tva, "Montant TTC": f.montant_ttc,
            "Statut": f.statut, "Paiement": f.moyen_paiement,
            "Réf.": f.reference, "Fichier": "📎" if f.fichier_nom else "",
            "Lien": f.lien_fichier, "Par": f.cree_par,
        } for f in rows]
    return pd.DataFrame(data)


def eur(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",")


# ------------------------------------------------------------------ #
#  Pages
# ------------------------------------------------------------------ #
def page_dashboard():
    st.header("📊 Tableau de bord")
    df = factures_df()
    if df.empty:
        st.info("Aucune facture pour l'instant. Ajoute-en dans l'onglet **Factures**.")
        return

    total_ttc = df["Montant TTC"].sum()
    a_payer = df.loc[df["Statut"] == "À payer", "Montant TTC"].sum()
    df["mois"] = pd.to_datetime(df["Date"]).dt.to_period("M").astype(str)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total dépensé (TTC)", eur(total_ttc))
    c2.metric("Reste à payer", eur(a_payer))
    c3.metric("Nombre de factures", len(df))

    st.divider()
    g1, g2 = st.columns(2)

    with g1:
        st.subheader("Dépenses par catégorie")
        cat = df.groupby("Catégorie", as_index=False)["Montant TTC"].sum()
        chart = alt.Chart(cat).mark_arc(innerRadius=55).encode(
            theta="Montant TTC:Q",
            color=alt.Color("Catégorie:N", legend=alt.Legend(orient="bottom")),
            tooltip=["Catégorie", alt.Tooltip("Montant TTC:Q", format=",.2f")],
        )
        st.altair_chart(chart, use_container_width=True)

    with g2:
        st.subheader("Répartition des paiements par personne")
        pers = df.copy()
        pers["Personne"] = (pers["Par"].fillna("").str.strip().str.capitalize()
                            .replace("", "Non précisé"))
        pers = pers.groupby("Personne", as_index=False)["Montant TTC"].sum()
        tot = pers["Montant TTC"].sum()
        pers["Part"] = (pers["Montant TTC"] / tot * 100) if tot else 0
        donut = alt.Chart(pers).mark_arc(innerRadius=55).encode(
            theta="Montant TTC:Q",
            color=alt.Color("Personne:N", legend=alt.Legend(orient="bottom")),
            tooltip=["Personne",
                     alt.Tooltip("Montant TTC:Q", format=",.2f", title="Montant TTC"),
                     alt.Tooltip("Part:Q", format=".1f", title="Part %")],
        )
        st.altair_chart(donut, use_container_width=True)

    st.subheader("Dépenses par mois")
    par_mois = df.groupby("mois", as_index=False)["Montant TTC"].sum().sort_values("mois")
    bar = alt.Chart(par_mois).mark_bar().encode(
        x=alt.X("mois:N", title="Mois"),
        y=alt.Y("Montant TTC:Q", title="€ TTC"),
        tooltip=["mois", alt.Tooltip("Montant TTC:Q", format=",.2f")],
    )
    st.altair_chart(bar, use_container_width=True)

    st.subheader("Top fournisseurs")
    top = (df.groupby("Fournisseur", as_index=False)["Montant TTC"].sum()
             .sort_values("Montant TTC", ascending=False).head(10))
    st.dataframe(top, use_container_width=True, hide_index=True)


FACT_KEYS = ["f_date", "f_fournisseur", "f_categorie", "f_ht", "f_tva",
             "f_statut", "f_paiement", "f_reference", "f_lien", "f_desc"]


def _num(x) -> float:
    try:
        return float(str(x).replace("€", "").replace(",", ".").strip() or 0)
    except Exception:
        return 0.0


def _seed_prefill(data: dict) -> None:
    """Range les champs lus par l'IA dans l'état des widgets (tout reste modifiable)."""
    from datetime import datetime
    try:
        st.session_state["f_date"] = datetime.strptime(
            str(data.get("date_facture") or ""), "%Y-%m-%d").date()
    except Exception:
        st.session_state["f_date"] = date.today()
    st.session_state["f_fournisseur"] = str(data.get("fournisseur") or "")
    cat = data.get("categorie") or "Divers"
    st.session_state["f_categorie"] = cat if cat in CATEGORIES else "Divers"
    st.session_state["f_ht"] = _num(data.get("montant_ht"))
    st.session_state["f_tva"] = _num(data.get("tva")) or 20.0
    stt = data.get("statut") or "À payer"
    st.session_state["f_statut"] = stt if stt in STATUTS_FACTURE else "À payer"
    moy = data.get("moyen_paiement") or ""
    st.session_state["f_paiement"] = moy if moy in MOYENS_PAIEMENT else "Autre"
    st.session_state["f_reference"] = str(data.get("reference") or "")


def _clean_facture(data: dict) -> dict:
    """Normalise un dict brut renvoyé par l'IA vers des valeurs prêtes à enregistrer."""
    from datetime import datetime
    try:
        d = datetime.strptime(str(data.get("date_facture") or ""), "%Y-%m-%d").date()
    except Exception:
        d = date.today()
    cat = data.get("categorie") or "Divers"
    moy = data.get("moyen_paiement") or ""
    stt = data.get("statut") or "À payer"
    return {
        "date": d,
        "fournisseur": str(data.get("fournisseur") or ""),
        "categorie": cat if cat in CATEGORIES else "Divers",
        "montant_ht": _num(data.get("montant_ht")),
        "tva": _num(data.get("tva")) or 20.0,
        "statut": stt if stt in STATUTS_FACTURE else "À payer",
        "moyen_paiement": moy if moy in MOYENS_PAIEMENT else "Autre",
        "reference": str(data.get("reference") or ""),
    }


def _annotate_duplicates(rows: list[dict]) -> list[dict]:
    """Marque chaque ligne comme doublon (vs base + à l'intérieur du lot)."""
    with SessionLocal() as s:
        existing = s.query(Facture.fournisseur, Facture.reference,
                           Facture.date_facture, Facture.montant_ht).all()
    ref_set, amt_set = set(), set()
    for f, r, dt, ht in existing:
        fl = (f or "").strip().lower()
        if r:
            ref_set.add(str(r).strip().lower())
        amt_set.add((fl, str(dt), round(float(ht or 0), 2)))

    seen_ref, seen_amt = set(), set()
    for row in rows:
        fl = row["fournisseur"].strip().lower()
        ref = (row["reference"] or "").strip().lower()
        key_amt = (fl, str(row["date"]), round(row["montant_ht"], 2))
        raison = ""
        if ref and (ref in ref_set or ref in seen_ref):
            raison = "Référence déjà présente"
        elif key_amt in amt_set or key_amt in seen_amt:
            raison = "Même fournisseur / date / montant"
        row["doublon"] = bool(raison)
        row["raison"] = raison
        if ref:
            seen_ref.add(ref)
        seen_amt.add(key_amt)
    return rows


def _batch_import_ui(user: str):
    ups = st.file_uploader(
        "Importer plusieurs factures à la fois (PDF, PNG, JPG)",
        type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True, key="batch_upload",
    )
    if ups and st.button(f"🤖 Analyser les {len(ups)} factures"):
        api_key = get_setting("openai_api_key")
        if not api_key:
            st.error("Aucune clé API enregistrée. Va dans ⚙️ Paramètres pour la saisir.")
        else:
            rows, files, errors = [], {}, []
            prog = st.progress(0.0, text="Analyse en cours…")
            for i, up in enumerate(ups):
                try:
                    row = _clean_facture(extract_facture(up.getvalue(), up.name, api_key=api_key))
                except Exception as e:
                    errors.append(f"{up.name} : {e}")
                    row = _clean_facture({})
                row.update({"idx": i, "fichier_nom": up.name, "fichier_type": up.type or ""})
                files[i] = up.getvalue()
                rows.append(row)
                prog.progress((i + 1) / len(ups), text=f"{i + 1}/{len(ups)}")
            st.session_state["batch"] = _annotate_duplicates(rows)
            st.session_state["batch_files"] = files
            st.session_state["batch_errors"] = errors
            st.rerun()

    batch = st.session_state.get("batch")
    if not batch:
        return

    errs = st.session_state.get("batch_errors") or []
    if errs:
        st.warning("Factures illisibles (à compléter à la main) :\n- " + "\n- ".join(errs))
    n_dup = sum(1 for r in batch if r["doublon"])
    st.info(f"{len(batch)} facture(s) analysée(s), dont {n_dup} doublon(s) potentiel(s) "
            "décoché(s) par défaut. Vérifie, corrige, puis enregistre.")

    df = pd.DataFrame([{
        "idx": r["idx"], "Importer": not r["doublon"], "Doublon": r["raison"],
        "Date": pd.to_datetime(r["date"]), "Fournisseur": r["fournisseur"],
        "Catégorie": r["categorie"], "Montant HT": r["montant_ht"], "TVA %": r["tva"],
        "Statut": r["statut"], "Paiement": r["moyen_paiement"], "Réf.": r["reference"],
        "Fichier": r["fichier_nom"],
    } for r in batch]).set_index("idx")

    edited = st.data_editor(
        df, use_container_width=True, hide_index=True, num_rows="fixed", key="batch_editor",
        column_config={
            "Importer": st.column_config.CheckboxColumn("Importer"),
            "Doublon": st.column_config.TextColumn("Doublon", disabled=True),
            "Date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
            "Catégorie": st.column_config.SelectboxColumn("Catégorie", options=CATEGORIES),
            "Statut": st.column_config.SelectboxColumn("Statut", options=STATUTS_FACTURE),
            "Paiement": st.column_config.SelectboxColumn("Paiement", options=MOYENS_PAIEMENT),
            "Montant HT": st.column_config.NumberColumn("Montant HT", format="%.2f", min_value=0.0),
            "TVA %": st.column_config.NumberColumn("TVA %", format="%.1f", min_value=0.0),
            "Fichier": st.column_config.TextColumn("Fichier", disabled=True),
        },
    )

    n_sel = int(edited["Importer"].sum())
    col1, col2 = st.columns(2)
    if col1.button(f"💾 Enregistrer les {n_sel} facture(s) sélectionnée(s)", disabled=n_sel == 0):
        files = st.session_state.get("batch_files", {})
        meta = {r["idx"]: r for r in batch}
        with SessionLocal() as s:
            for idx, row in edited.iterrows():
                if not row["Importer"]:
                    continue
                m = meta.get(int(idx), {})
                s.add(Facture(
                    date_facture=pd.to_datetime(row["Date"]).date(),
                    fournisseur=str(row["Fournisseur"] or ""),
                    categorie=str(row["Catégorie"] or "Divers"),
                    montant_ht=float(row["Montant HT"] or 0), tva=float(row["TVA %"] or 0),
                    statut=str(row["Statut"] or "À payer"),
                    moyen_paiement=str(row["Paiement"] or ""),
                    reference=str(row["Réf."] or ""), cree_par=user,
                    fichier=files.get(int(idx)),
                    fichier_nom=m.get("fichier_nom", ""), fichier_type=m.get("fichier_type", ""),
                ))
            s.commit()
        for k in ["batch", "batch_files", "batch_errors", "batch_upload", "batch_editor"]:
            st.session_state.pop(k, None)
        factures_df.clear()
        st.success(f"{n_sel} facture(s) enregistrée(s).")
        st.rerun()
    if col2.button("Annuler l'import en lot"):
        for k in ["batch", "batch_files", "batch_errors", "batch_upload", "batch_editor"]:
            st.session_state.pop(k, None)
        st.rerun()


def _save_facture_edits(edited: pd.DataFrame) -> None:
    """Réécrit en base les lignes éditées dans le tableau (indexé par id)."""
    with SessionLocal() as s:
        for fid, row in edited.iterrows():
            obj = s.get(Facture, int(fid))
            if obj is None:
                continue
            try:
                obj.date_facture = pd.to_datetime(row["Date"]).date()
            except Exception:
                pass
            obj.fournisseur = str(row["Fournisseur"] or "")
            obj.categorie = str(row["Catégorie"] or "Divers")
            obj.description = str(row["Description"] or "")
            obj.montant_ht = float(row["Montant HT"] or 0)
            obj.tva = float(row["TVA %"] or 0)
            obj.statut = str(row["Statut"] or "À payer")
            obj.moyen_paiement = str(row["Paiement"] or "")
            obj.reference = str(row["Réf."] or "")
            obj.lien_fichier = str(row["Lien"] or "")
            obj.cree_par = str(row["Par"] or "")
        s.commit()


def page_factures(user: str):
    st.header("🧾 Factures")

    st.session_state.setdefault("f_tva", 20.0)  # défaut TVA en saisie manuelle

    with st.expander("➕ Ajouter une facture", expanded=bool(st.session_state.get("prefilled"))):
        up = st.file_uploader(
            "📎 Importer une facture (PDF, PNG, JPG) — lecture automatique par l'IA",
            type=["pdf", "png", "jpg", "jpeg"], key="fact_upload",
        )
        if up is not None:
            if st.button("🤖 Analyser la facture avec l'IA"):
                api_key = get_setting("openai_api_key")
                if not api_key:
                    st.error("Aucune clé API enregistrée. Va dans ⚙️ Paramètres "
                             "pour la saisir (une seule fois).")
                else:
                    try:
                        with st.spinner("Lecture de la facture en cours…"):
                            data = extract_facture(up.getvalue(), up.name, api_key=api_key)
                        _seed_prefill(data)
                        st.session_state["prefilled"] = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"Analyse impossible : {e}")

        if st.session_state.get("prefilled"):
            st.success("Champs pré-remplis par l'IA — vérifie et corrige avant d'enregistrer.")

        a, b, c = st.columns(3)
        d = a.date_input("Date", key="f_date")
        fournisseur = b.text_input("Fournisseur", key="f_fournisseur")
        categorie = c.selectbox("Catégorie", CATEGORIES, key="f_categorie")
        a2, b2, c2 = st.columns(3)
        ht = a2.number_input("Montant HT (€)", min_value=0.0, step=10.0, format="%.2f", key="f_ht")
        tva = b2.number_input("TVA (%)", min_value=0.0, step=1.0, format="%.1f", key="f_tva")
        statut = c2.selectbox("Statut", STATUTS_FACTURE, key="f_statut")
        a3, b3, c3 = st.columns(3)
        paiement = a3.selectbox("Moyen de paiement", MOYENS_PAIEMENT, key="f_paiement")
        reference = b3.text_input("Référence / n° facture", key="f_reference")
        lien = c3.text_input("Lien vers le fichier (Drive, etc.)", key="f_lien")
        description = st.text_area("Description", height=70, key="f_desc")

        st.metric("💶 Montant TTC", eur(ht * (1 + tva / 100.0)))

        if st.button("💾 Enregistrer la facture"):
            fichier_bytes = up.getvalue() if up is not None else None
            fichier_nom = up.name if up is not None else ""
            fichier_type = (up.type or "") if up is not None else ""
            with SessionLocal() as s:
                s.add(Facture(
                    date_facture=d, fournisseur=fournisseur, categorie=categorie,
                    description=description, montant_ht=ht, tva=tva, statut=statut,
                    moyen_paiement=paiement, reference=reference, lien_fichier=lien,
                    cree_par=user,
                    fichier=fichier_bytes, fichier_nom=fichier_nom, fichier_type=fichier_type,
                ))
                s.commit()
            for k in FACT_KEYS + ["prefilled", "fact_upload"]:
                st.session_state.pop(k, None)
            factures_df.clear()
            st.success("Facture ajoutée." + (" Justificatif enregistré." if fichier_bytes else ""))
            st.rerun()

    with st.expander("📦 Importer plusieurs factures d'un coup"):
        _batch_import_ui(user)

    df = factures_df()
    if df.empty:
        st.info("Aucune facture enregistrée.")
        return

    f1, f2, f3 = st.columns(3)
    cat_filter = f1.multiselect("Filtrer par catégorie", CATEGORIES)
    stat_filter = f2.multiselect("Filtrer par statut", STATUTS_FACTURE)
    search = f3.text_input("Recherche (fournisseur / description)")

    view = df.copy()
    if cat_filter:
        view = view[view["Catégorie"].isin(cat_filter)]
    if stat_filter:
        view = view[view["Statut"].isin(stat_filter)]
    if search:
        m = (view["Fournisseur"].str.contains(search, case=False, na=False) |
             view["Description"].str.contains(search, case=False, na=False))
        view = view[m]

    st.caption(f"{len(view)} facture(s) · Total TTC filtré : {eur(view['Montant TTC'].sum())}")
    st.caption("✏️ Tu peux corriger les cellules directement (fournisseur, catégorie, montant…), "
               "puis clique **Enregistrer les modifications**.")
    edit_df = view.drop(columns=["Montant TTC", "Fichier"]).set_index("id")
    edited = st.data_editor(
        edit_df, use_container_width=True, hide_index=True, num_rows="fixed",
        key="fact_editor",
        column_config={
            "Date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
            "Catégorie": st.column_config.SelectboxColumn("Catégorie", options=CATEGORIES),
            "Statut": st.column_config.SelectboxColumn("Statut", options=STATUTS_FACTURE),
            "Paiement": st.column_config.SelectboxColumn("Paiement", options=MOYENS_PAIEMENT),
            "Montant HT": st.column_config.NumberColumn("Montant HT", format="%.2f", min_value=0.0),
            "TVA %": st.column_config.NumberColumn("TVA %", format="%.1f", min_value=0.0),
            "Lien": st.column_config.LinkColumn("Lien"),
        },
    )
    if st.button("💾 Enregistrer les modifications"):
        _save_facture_edits(edited)
        factures_df.clear()
        st.success("Modifications enregistrées.")
        st.rerun()

    st.download_button(
        "⬇️ Exporter en CSV", view.drop(columns=["id"]).to_csv(index=False).encode("utf-8"),
        file_name="factures_kingland.csv", mime="text/csv",
    )

    with st.expander("📎 Justificatifs importés (télécharger)"):
        with SessionLocal() as s:
            avec_fichier = (s.query(Facture.id, Facture.fournisseur, Facture.date_facture,
                                    Facture.fichier_nom)
                            .filter(Facture.fichier_nom != "")
                            .order_by(Facture.date_facture.desc()).all())
        if avec_fichier:
            opt = st.selectbox(
                "Facture avec justificatif", avec_fichier,
                format_func=lambda r: f"#{r.id} · {r.date_facture} · {r.fournisseur} · {r.fichier_nom}",
            )
            with SessionLocal() as s:
                obj = s.get(Facture, int(opt.id))
                st.download_button(
                    "⬇️ Télécharger le fichier",
                    data=obj.fichier or b"",
                    file_name=obj.fichier_nom or f"facture_{obj.id}",
                    mime=obj.fichier_type or "application/octet-stream",
                )
        else:
            st.caption("Aucun fichier importé pour l'instant.")

    with st.expander("🗑️ Supprimer une facture"):
        ids = view["id"].tolist()
        if ids:
            fid = st.selectbox(
                "Facture à supprimer", ids,
                format_func=lambda i: f"#{i} · {view.loc[view['id']==i,'Fournisseur'].values[0]} "
                                      f"· {eur(view.loc[view['id']==i,'Montant TTC'].values[0])}",
            )
            if st.button("Confirmer la suppression", type="primary"):
                with SessionLocal() as s:
                    obj = s.get(Facture, int(fid))
                    if obj:
                        s.delete(obj)
                        s.commit()
                factures_df.clear()
                st.rerun()


def page_budgets():
    st.header("🎯 Budgets par poste")
    st.caption("Définis un budget cible par catégorie et suis la consommation. "
               "Les budgets sont enregistrés le temps de la session.")

    defaults = {
        "Assets & animations": 30000.0,
        "Marketing": 5000.0,
        "Doublage": 0.0,
        "Cinématiques externes": 0.0,
        "Hébergement & domaines": 200.0,
    }
    if "budgets" not in st.session_state:
        st.session_state["budgets"] = {c: defaults.get(c, 0.0) for c in CATEGORIES}

    df = factures_df()
    depenses = (df.groupby("Catégorie")["Montant TTC"].sum().to_dict()
                if not df.empty else {})

    for cat in CATEGORIES:
        col1, col2 = st.columns([1, 2])
        budget = col1.number_input(
            cat, min_value=0.0, step=100.0, format="%.0f",
            value=float(st.session_state["budgets"].get(cat, 0.0)), key=f"bud_{cat}",
        )
        st.session_state["budgets"][cat] = budget
        depense = float(depenses.get(cat, 0.0))
        with col2:
            if budget > 0:
                ratio = min(depense / budget, 1.0)
                st.progress(ratio, text=f"{eur(depense)} / {eur(budget)} ({ratio*100:.0f} %)")
            else:
                st.caption(f"Dépensé : {eur(depense)} (pas de budget défini)")


def page_recrutement(user: str):
    st.header("👥 Recrutement")
    tab_offres, tab_cand = st.tabs(["Offres de poste", "Candidatures reçues"])

    # ---- Offres ----
    with tab_offres:
        with st.expander("➕ Nouvelle offre"):
            with st.form("add_offre", clear_on_submit=True):
                a, b = st.columns(2)
                intitule = a.text_input("Intitulé du poste")
                type_poste = b.selectbox("Type", TYPES_POSTE)
                desc = st.text_area("Description", height=90)
                statut = st.selectbox("Statut", STATUTS_OFFRE)
                if st.form_submit_button("Créer l'offre"):
                    with SessionLocal() as s:
                        s.add(Offre(intitule=intitule, type_poste=type_poste,
                                    description=desc, statut=statut, cree_par=user))
                        s.commit()
                    st.rerun()

        with SessionLocal() as s:
            offres = s.query(Offre).order_by(Offre.date_creation.desc()).all()
            offres_data = [{
                "id": o.id, "Intitulé": o.intitule, "Type": o.type_poste,
                "Statut": o.statut, "Créée le": o.date_creation, "Description": o.description,
            } for o in offres]
        if offres_data:
            st.dataframe(pd.DataFrame(offres_data).drop(columns=["id"]),
                         use_container_width=True, hide_index=True)
            with st.expander("🗑️ Supprimer une offre"):
                oid = st.selectbox("Offre", [o["id"] for o in offres_data],
                                   format_func=lambda i: next(o["Intitulé"] for o in offres_data if o["id"] == i))
                if st.button("Supprimer l'offre", type="primary", key="del_offre"):
                    with SessionLocal() as s:
                        obj = s.get(Offre, int(oid))
                        if obj:
                            s.delete(obj); s.commit()
                    st.rerun()
        else:
            st.info("Aucune offre pour l'instant.")

    # ---- Candidatures ----
    with tab_cand:
        with SessionLocal() as s:
            postes = [o.intitule for o in s.query(Offre).all()]
        with st.expander("➕ Nouvelle candidature"):
            with st.form("add_cand", clear_on_submit=True):
                a, b = st.columns(2)
                nom = a.text_input("Nom du candidat")
                poste = b.selectbox("Poste visé", postes + ["Autre / spontanée"]) if postes \
                    else b.text_input("Poste visé")
                a2, b2 = st.columns(2)
                contact = a2.text_input("Contact (email / Discord)")
                lien = b2.text_input("Portfolio / CV (lien)")
                a3, b3 = st.columns(2)
                statut = a3.selectbox("Statut", STATUTS_CANDIDATURE)
                evaluation = b3.slider("Évaluation", 0, 5, 0)
                notes = st.text_area("Notes", height=80)
                if st.form_submit_button("Enregistrer la candidature"):
                    with SessionLocal() as s:
                        s.add(Candidature(
                            nom=nom, poste_vise=poste, contact=contact, lien=lien,
                            statut=statut, evaluation=evaluation, notes=notes, cree_par=user,
                        ))
                        s.commit()
                    st.rerun()

        with SessionLocal() as s:
            cands = s.query(Candidature).order_by(Candidature.date_reception.desc()).all()
            cdata = [{
                "id": c.id, "Nom": c.nom, "Poste visé": c.poste_vise, "Contact": c.contact,
                "Lien": c.lien, "Statut": c.statut, "Éval.": "⭐" * c.evaluation,
                "Reçue le": c.date_reception, "Notes": c.notes,
            } for c in cands]

        if cdata:
            cdf = pd.DataFrame(cdata)
            filt = st.multiselect("Filtrer par statut", STATUTS_CANDIDATURE)
            if filt:
                cdf = cdf[cdf["Statut"].isin(filt)]
            st.dataframe(
                cdf.drop(columns=["id"]), use_container_width=True, hide_index=True,
                column_config={"Lien": st.column_config.LinkColumn("Lien")},
            )
            with st.expander("✏️ Modifier le statut / supprimer"):
                cid = st.selectbox("Candidature", cdf["id"].tolist(),
                                   format_func=lambda i: cdf.loc[cdf["id"]==i, "Nom"].values[0])
                new_stat = st.selectbox("Nouveau statut", STATUTS_CANDIDATURE, key="upd_stat")
                col_u, col_d = st.columns(2)
                if col_u.button("Mettre à jour"):
                    with SessionLocal() as s:
                        obj = s.get(Candidature, int(cid))
                        if obj:
                            obj.statut = new_stat; s.commit()
                    st.rerun()
                if col_d.button("Supprimer", type="primary"):
                    with SessionLocal() as s:
                        obj = s.get(Candidature, int(cid))
                        if obj:
                            s.delete(obj); s.commit()
                    st.rerun()
        else:
            st.info("Aucune candidature reçue.")


# ------------------------------------------------------------------ #
#  App
# ------------------------------------------------------------------ #
def page_parametres():
    st.header("⚙️ Paramètres")
    st.subheader("Clé API OpenAI")
    st.caption("Nécessaire pour la lecture automatique des factures. "
               "À saisir une seule fois : elle est conservée pour toi et pour Matth.")

    current = get_setting("openai_api_key")
    if current:
        masque = current[:7] + "…" + current[-4:]
        st.success(f"Une clé est enregistrée ({masque}).")
    else:
        st.warning("Aucune clé enregistrée — la lecture automatique est désactivée.")

    new_key = st.text_input("Saisir ou remplacer la clé", type="password",
                            placeholder="sk-...", key="param_key")
    c1, c2 = st.columns(2)
    if c1.button("💾 Enregistrer la clé"):
        if new_key.strip():
            set_setting("openai_api_key", new_key.strip())
            st.session_state.pop("param_key", None)
            st.success("Clé enregistrée.")
            st.rerun()
        else:
            st.error("Colle une clé avant d'enregistrer.")
    if current and c2.button("🗑️ Supprimer la clé"):
        set_setting("openai_api_key", "")
        st.rerun()

    st.info("La clé est stockée dans ta base Neon privée, jamais dans le code ni sur GitHub. "
            "En cas de doute, tu peux la révoquer sur platform.openai.com et en saisir une nouvelle ici.")


def page_utilisateurs():
    st.header("👤 Utilisateurs")
    st.caption("Crée des comptes pour accéder à l'app. Les mots de passe sont chiffrés "
               "en base. Tes comptes d'origine (secrets) restent valables en secours.")

    users = list_users()
    if users:
        st.dataframe(
            pd.DataFrame(users, columns=["Identifiant", "Nom affiché"]),
            hide_index=True, use_container_width=True,
        )
    else:
        st.info("Aucun utilisateur créé en base pour l'instant.")

    st.subheader("Créer un utilisateur")
    nu = st.text_input("Identifiant (sans espace, en minuscules)", key="nu_user")
    nd = st.text_input("Nom affiché (ex. Mathieu)", key="nu_disp")
    npw = st.text_input("Mot de passe", type="password", key="nu_pw")
    if st.button("Créer l'utilisateur"):
        ident = nu.strip().lower()
        if not ident or not npw:
            st.error("Identifiant et mot de passe obligatoires.")
        elif create_user(ident, nd.strip(), npw):
            for k in ["nu_user", "nu_disp", "nu_pw"]:
                st.session_state.pop(k, None)
            st.success(f"Utilisateur « {ident} » créé.")
            st.rerun()
        else:
            st.error("Cet identifiant existe déjà.")

    if users:
        st.subheader("Supprimer un utilisateur")
        du = st.selectbox("Utilisateur à supprimer", [u[0] for u in users], key="del_user_sel")
        if st.button("Supprimer", type="primary"):
            delete_user(du)
            st.rerun()


def main():
    user = login_gate()
    if not user:
        return

    with st.sidebar:
        st.markdown("### 🛡️ KingLand Gestion")
        st.caption(f"Connecté : **{user}**")
        if st.button("Se déconnecter"):
            st.session_state.pop("user", None)
            st.rerun()
        st.caption(f"Base : {backend_label()}")

    t_dash, t_fact, t_budg, t_recr, t_users, t_param = st.tabs(
        ["📊 Tableau de bord", "🧾 Factures", "🎯 Budgets",
         "👥 Recrutement", "👤 Utilisateurs", "⚙️ Paramètres"])
    with t_dash:
        page_dashboard()
    with t_fact:
        page_factures(user)
    with t_budg:
        page_budgets()
    with t_recr:
        page_recrutement(user)
    with t_users:
        page_utilisateurs()
    with t_param:
        page_parametres()


if __name__ == "__main__":
    main()
