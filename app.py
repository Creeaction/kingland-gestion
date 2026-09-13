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
        users = _users()
        if u in users and str(users[u]) == p:
            st.session_state["user"] = u
            st.rerun()
        else:
            st.error("Identifiant ou mot de passe incorrect.")
    return None


# ------------------------------------------------------------------ #
#  Helpers données
# ------------------------------------------------------------------ #
def factures_df() -> pd.DataFrame:
    with SessionLocal() as s:
        rows = s.query(Facture).order_by(Facture.date_facture.desc()).all()
        data = [{
            "id": f.id, "Date": f.date_facture, "Fournisseur": f.fournisseur,
            "Catégorie": f.categorie, "Description": f.description,
            "Montant HT": f.montant_ht, "TVA %": f.tva, "Montant TTC": f.montant_ttc,
            "Statut": f.statut, "Paiement": f.moyen_paiement,
            "Réf.": f.reference, "Lien": f.lien_fichier, "Par": f.cree_par,
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
    mois_courant = date.today().strftime("%Y-%m")
    ce_mois = df.loc[df["mois"] == mois_courant, "Montant TTC"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total dépensé (TTC)", eur(total_ttc))
    c2.metric("Ce mois-ci", eur(ce_mois))
    c3.metric("Reste à payer", eur(a_payer))
    c4.metric("Nombre de factures", len(df))

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
                try:
                    with st.spinner("Lecture de la facture en cours…"):
                        data = extract_facture(up.getvalue(), up.name)
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

        if st.button("💾 Enregistrer la facture"):
            with SessionLocal() as s:
                s.add(Facture(
                    date_facture=d, fournisseur=fournisseur, categorie=categorie,
                    description=description, montant_ht=ht, tva=tva, statut=statut,
                    moyen_paiement=paiement, reference=reference, lien_fichier=lien,
                    cree_par=user,
                ))
                s.commit()
            for k in FACT_KEYS + ["prefilled", "fact_upload"]:
                st.session_state.pop(k, None)
            st.success("Facture ajoutée.")
            st.rerun()

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
    st.dataframe(
        view.drop(columns=["id"]),
        use_container_width=True, hide_index=True,
        column_config={"Lien": st.column_config.LinkColumn("Lien")},
    )

    st.download_button(
        "⬇️ Exporter en CSV", view.drop(columns=["id"]).to_csv(index=False).encode("utf-8"),
        file_name="factures_kingland.csv", mime="text/csv",
    )

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
def main():
    user = login_gate()
    if not user:
        return

    with st.sidebar:
        st.markdown("### 🛡️ KingLand Gestion")
        st.caption(f"Connecté : **{user}**")
        page = st.radio("Navigation",
                        ["Tableau de bord", "Factures", "Budgets", "Recrutement"])
        st.divider()
        if st.button("Se déconnecter"):
            st.session_state.pop("user", None)
            st.rerun()

    if page == "Tableau de bord":
        page_dashboard()
    elif page == "Factures":
        page_factures(user)
    elif page == "Budgets":
        page_budgets()
    elif page == "Recrutement":
        page_recrutement(user)


if __name__ == "__main__":
    main()
