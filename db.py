"""
Couche base de données pour KingLand Gestion.

Par défaut : SQLite (fichier local kingland.db) -> parfait pour tester
et pour un hébergement avec disque persistant (ta Dedibox).

Pour un hébergement sans disque persistant (Streamlit Community Cloud),
définis une variable DATABASE_URL vers un Postgres gratuit (Neon / Supabase) :
    postgresql+psycopg2://user:pass@host/dbname
"""

import os
import hashlib
import secrets as _secrets
from datetime import date, datetime

from sqlalchemy import (
    create_engine, Integer, String, Float, Boolean, Date, DateTime, Text,
    LargeBinary, inspect, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, deferred


def _database_url() -> str:
    # 1) variable d'environnement
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # 2) secrets Streamlit — au niveau principal…
    try:
        import streamlit as st
        if "DATABASE_URL" in st.secrets:
            return str(st.secrets["DATABASE_URL"])
        # …ou rangée par erreur sous une section comme [auth]
        for section in list(st.secrets.keys()):
            val = st.secrets[section]
            if hasattr(val, "keys") and "DATABASE_URL" in val:
                return str(val["DATABASE_URL"])
    except Exception:
        pass
    # 3) SQLite local par défaut (dev uniquement)
    return "sqlite:///kingland.db"


DATABASE_URL = _database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

ENGINE = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=ENGINE, expire_on_commit=False)


def backend_label() -> str:
    """Libellé lisible de la base active, à afficher dans l'app."""
    if IS_SQLITE:
        return "⚠️ SQLite local (données NON persistantes)"
    return "Neon / PostgreSQL"


class Base(DeclarativeBase):
    pass


class Facture(Base):
    __tablename__ = "factures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date_facture: Mapped[date] = mapped_column(Date, default=date.today)
    fournisseur: Mapped[str] = mapped_column(String(200), default="")
    categorie: Mapped[str] = mapped_column(String(100), default="Divers")
    description: Mapped[str] = mapped_column(Text, default="")
    montant_ht: Mapped[float] = mapped_column(Float, default=0.0)
    tva: Mapped[float] = mapped_column(Float, default=20.0)  # en %
    statut: Mapped[str] = mapped_column(String(30), default="À payer")
    moyen_paiement: Mapped[str] = mapped_column(String(50), default="")
    reference: Mapped[str] = mapped_column(String(100), default="")
    lien_fichier: Mapped[str] = mapped_column(Text, default="")
    cree_par: Mapped[str] = mapped_column(String(50), default="")
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Fichier importé (PDF / image) conservé en base
    fichier: Mapped[bytes | None] = deferred(
        mapped_column(LargeBinary, nullable=True, default=None))
    fichier_nom: Mapped[str] = mapped_column(String(255), default="")
    fichier_type: Mapped[str] = mapped_column(String(100), default="")

    @property
    def montant_ttc(self) -> float:
        return round(self.montant_ht * (1 + self.tva / 100.0), 2)


class Offre(Base):
    __tablename__ = "offres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intitule: Mapped[str] = mapped_column(String(200), default="")
    type_poste: Mapped[str] = mapped_column(String(50), default="Bénévole")
    description: Mapped[str] = mapped_column(Text, default="")
    statut: Mapped[str] = mapped_column(String(30), default="Ouverte")
    date_creation: Mapped[date] = mapped_column(Date, default=date.today)
    cree_par: Mapped[str] = mapped_column(String(50), default="")


class Candidature(Base):
    __tablename__ = "candidatures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nom: Mapped[str] = mapped_column(String(200), default="")
    poste_vise: Mapped[str] = mapped_column(String(200), default="")
    contact: Mapped[str] = mapped_column(String(200), default="")
    lien: Mapped[str] = mapped_column(Text, default="")  # portfolio / CV
    statut: Mapped[str] = mapped_column(String(30), default="Reçue")
    evaluation: Mapped[int] = mapped_column(Integer, default=0)  # 0 à 5
    notes: Mapped[str] = mapped_column(Text, default="")
    date_reception: Mapped[date] = mapped_column(Date, default=date.today)
    cree_par: Mapped[str] = mapped_column(String(50), default="")


class AppSetting(Base):
    """Petits réglages de l'app stockés en base (ex. clé API OpenAI)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


def get_setting(key: str, default: str = "") -> str:
    with SessionLocal() as s:
        obj = s.get(AppSetting, key)
        return obj.value if obj and obj.value else default


def set_setting(key: str, value: str) -> None:
    with SessionLocal() as s:
        obj = s.get(AppSetting, key)
        if obj:
            obj.value = value
        else:
            s.add(AppSetting(key=key, value=value))
        s.commit()


class User(Base):
    """Comptes créés depuis l'app (mots de passe chiffrés)."""
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    password_hash: Mapped[str] = mapped_column(String(255), default="")


def hash_password(password: str) -> str:
    salt = _secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()
    return _secrets.compare_digest(calc, h)


def list_users() -> list[tuple[str, str]]:
    with SessionLocal() as s:
        return [(u.username, u.display_name or u.username) for u in s.query(User).all()]


def create_user(username: str, display_name: str, password: str) -> bool:
    with SessionLocal() as s:
        if s.get(User, username):
            return False
        s.add(User(username=username, display_name=display_name or username,
                   password_hash=hash_password(password)))
        s.commit()
        return True


def delete_user(username: str) -> None:
    with SessionLocal() as s:
        obj = s.get(User, username)
        if obj:
            s.delete(obj)
            s.commit()


def check_login(username: str, password: str) -> str | None:
    """Renvoie le nom d'affichage si les identifiants sont bons, sinon None."""
    with SessionLocal() as s:
        u = s.get(User, username)
        if u and verify_password(password, u.password_hash):
            return u.display_name or u.username
    return None


def _ensure_facture_columns() -> None:
    """Ajoute les colonnes de fichier si la table factures existe déjà sans elles."""
    insp = inspect(ENGINE)
    if "factures" not in insp.get_table_names():
        return  # sera créée complète par create_all
    existing = {c["name"] for c in insp.get_columns("factures")}
    blob_type = "BYTEA" if ENGINE.dialect.name == "postgresql" else "BLOB"
    ajouts = []
    if "fichier" not in existing:
        ajouts.append(f"ADD COLUMN fichier {blob_type}")
    if "fichier_nom" not in existing:
        ajouts.append("ADD COLUMN fichier_nom VARCHAR(255)")
    if "fichier_type" not in existing:
        ajouts.append("ADD COLUMN fichier_type VARCHAR(100)")
    for clause in ajouts:
        with ENGINE.begin() as conn:
            conn.execute(text(f"ALTER TABLE factures {clause}"))


def init_db() -> None:
    Base.metadata.create_all(ENGINE)
    _ensure_facture_columns()


# ---- Constantes métier (adaptées à KingLand / Arkhion Studio) ----

CATEGORIES = [
    "Assets & animations",
    "Cinématiques externes",
    "Doublage",
    "Logiciels & licences",
    "Matériel",
    "Freelances",
    "Marketing",
    "Hébergement & domaines",
    "Récompenses contributeurs",
    "Divers",
]

STATUTS_FACTURE = ["Payée", "À payer"]
TYPES_POSTE = ["Bénévole", "Rémunéré", "Part de revenus", "Stage"]
STATUTS_OFFRE = ["Ouverte", "Fermée", "Pourvue"]
STATUTS_CANDIDATURE = ["Reçue", "En cours", "Entretien", "Acceptée", "Refusée"]
MOYENS_PAIEMENT = ["Virement", "Carte", "PayPal", "Prélèvement", "Espèces", "Autre"]
