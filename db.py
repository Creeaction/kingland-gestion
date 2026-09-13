"""
Couche base de données pour KingLand Gestion.

Par défaut : SQLite (fichier local kingland.db) -> parfait pour tester
et pour un hébergement avec disque persistant (ta Dedibox).

Pour un hébergement sans disque persistant (Streamlit Community Cloud),
définis une variable DATABASE_URL vers un Postgres gratuit (Neon / Supabase) :
    postgresql+psycopg2://user:pass@host/dbname
"""

import os
from datetime import date, datetime

from sqlalchemy import (
    create_engine, Integer, String, Float, Boolean, Date, DateTime, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _database_url() -> str:
    # 1) variable d'environnement / secret Streamlit  2) SQLite local par défaut
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get("DATABASE_URL", None)
        except Exception:
            url = None
    return url or "sqlite:///kingland.db"


ENGINE = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False} if _database_url().startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=ENGINE, expire_on_commit=False)


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


def init_db() -> None:
    Base.metadata.create_all(ENGINE)


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

STATUTS_FACTURE = ["À payer", "Payée"]
TYPES_POSTE = ["Bénévole", "Rémunéré", "Part de revenus", "Stage"]
STATUTS_OFFRE = ["Ouverte", "Fermée", "Pourvue"]
STATUTS_CANDIDATURE = ["Reçue", "En cours", "Entretien", "Acceptée", "Refusée"]
MOYENS_PAIEMENT = ["Virement", "Carte", "PayPal", "Prélèvement", "Espèces", "Autre"]
