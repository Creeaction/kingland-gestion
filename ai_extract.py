"""
Lecture automatique de factures (PDF / image) via l'API OpenAI.
La clé se met dans les secrets Streamlit sous OPENAI_API_KEY (jamais dans le code).
Les imports lourds (openai, fitz) sont chargés à la demande.
"""

import base64
import json

from db import CATEGORIES, STATUTS_FACTURE, MOYENS_PAIEMENT

MODEL = "gpt-4o-mini"  # vision + bon marché ; modifiable si besoin

PROMPT = (
    "Tu lis des factures françaises. Analyse la ou les image(s) fournie(s) et "
    "extrais les informations. Réponds UNIQUEMENT par un objet JSON, sans texte "
    "autour, avec exactement ces clés :\n"
    '- "date_facture": date au format "AAAA-MM-JJ" (chaîne vide si absente)\n'
    '- "fournisseur": nom de l\'émetteur\n'
    '- "montant_ht": montant HORS TAXES (souvent libellé "Subtotal" ou '
    '"Total excluding tax"). Si seul le TTC figure avec un taux de TVA, calcule le HT.\n'
    '- "tva": taux de TVA en pourcentage réellement affiché sur la facture '
    "(ex : 19 pour l'Allemagne, 20 pour la France). Si plusieurs, prends le principal.\n"
    '- "montant_ttc": montant total à payer (souvent "Total" ou "Amount due")\n'
    '- "statut": "Payée" si la facture est indiquée réglée/acquittée, sinon "À payer"\n'
    f'- "moyen_paiement": un parmi {MOYENS_PAIEMENT} ou "" si inconnu\n'
    '- "reference": numéro / référence de la facture\n'
    f'- "categorie": la plus adaptée parmi : {", ".join(CATEGORIES)}\n'
    "Utilise des nombres purs (pas de symbole €, pas d'espace). "
    "Information absente = chaîne vide ou 0."
)


def _client(api_key: str | None = None):
    import os
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("OPENAI_API_KEY")
        except Exception:
            key = None
    if not key:
        raise RuntimeError(
            "Aucune clé API OpenAI. Saisis-la dans la page Paramètres de l'app."
        )
    from openai import OpenAI
    return OpenAI(api_key=key, max_retries=6, timeout=60)


def _file_to_data_uris(file_bytes: bytes, filename: str) -> list[str]:
    name = filename.lower()
    if name.endswith(".pdf"):
        import fitz  # PyMuPDF
        uris = []
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in list(doc)[:2]:  # 2 premières pages suffisent pour une facture
            pix = page.get_pixmap(dpi=150)
            b64 = base64.b64encode(pix.tobytes("png")).decode()
            uris.append(f"data:image/png;base64,{b64}")
        doc.close()
        return uris
    mime = "image/jpeg" if name.endswith((".jpg", ".jpeg")) else "image/png"
    b64 = base64.b64encode(file_bytes).decode()
    return [f"data:{mime};base64,{b64}"]


def extract_facture(file_bytes: bytes, filename: str, api_key: str | None = None) -> dict:
    """Renvoie un dict avec les champs de la facture."""
    client = _client(api_key)
    content = [{"type": "text", "text": PROMPT}]
    for uri in _file_to_data_uris(file_bytes, filename):
        content.append({"type": "image_url", "image_url": {"url": uri}})

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content)
