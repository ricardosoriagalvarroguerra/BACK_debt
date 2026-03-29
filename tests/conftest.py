"""Shared fixtures for backend tests."""
import sys
import os
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, text, String, Text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Ensure the backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Patch PostgreSQL-specific column types so SQLite can render them
# ---------------------------------------------------------------------------
from sqlalchemy.dialects.postgresql import JSONB, INET, TIMESTAMP as PG_TIMESTAMP
from sqlalchemy import TypeDecorator

# Register compilation hooks BEFORE importing models
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"

@compiles(INET, "sqlite")
def _compile_inet_sqlite(type_, compiler, **kw):
    return "VARCHAR(50)"

from app.database import Base, get_db
from app.main import app
from app.models.user import User
from app.models.currency import Currency
from app.models.creditor import Creditor
from app.models.contract import Contract
from app.models.disbursement import Disbursement
from app.models.balance import Balance
from app.models.payment import PaymentSchedule
from app.models.covenant import Covenant, CovenantTracking
from app.models.config import SystemConfig
from app.security import get_password_hash, create_access_token

# ---------------------------------------------------------------------------
# SQLite in-memory engine
# ---------------------------------------------------------------------------

SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
)

# Enable WAL / foreign keys for SQLite
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup_db():
    """Create all tables before each test, drop after."""
    # Render PostgreSQL-specific types as generic for SQLite
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    """Provide a transactional database session for tests."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    """FastAPI TestClient with overridden DB dependency."""
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample-data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_user(db):
    """Create a test user with hashed password."""
    user = User(
        email="test@vpfinanzas.com",
        full_name="Test User",
        role="ADMIN",
        password_hash=get_password_hash("testpass123"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def auth_header(sample_user):
    """Return Authorization header dict with a valid JWT."""
    token = create_access_token(data={"sub": str(sample_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def sample_currency(db):
    """Create a USD currency row."""
    cur = Currency(id=1, code="USD", name="US Dollar", symbol="$", decimals=2, is_active=True)
    db.add(cur)
    db.commit()
    db.refresh(cur)
    return cur


@pytest.fixture()
def sample_creditor(db, sample_user):
    """Create a sample IFD creditor."""
    creditor = Creditor(
        code="BID",
        name="Banco Interamericano de Desarrollo",
        short_name="BID",
        creditor_type="IFD",
        subtype="MULTILATERAL",
        country="US",
        is_active=True,
        created_by=sample_user.id,
    )
    db.add(creditor)
    db.commit()
    db.refresh(creditor)
    return creditor


@pytest.fixture()
def sample_contract(db, sample_creditor, sample_currency, sample_user):
    """Create a sample contract."""
    contract = Contract(
        creditor_id=sample_creditor.id,
        contract_code="BID-001",
        contract_name="Contrato BID 001",
        status="VIGENTE",
        approved_amount=Decimal("100000000"),
        currency_id=sample_currency.id,
        approved_amount_usd=Decimal("100000000"),
        maturity_date=date(2030, 12, 31),
        amortization_type="BULLET",
        interest_rate_type="VARIABLE",
        spread_bps=Decimal("150.0000"),
        created_by=sample_user.id,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


@pytest.fixture()
def sample_disbursement(db, sample_contract, sample_user):
    """Create a sample disbursement."""
    disb = Disbursement(
        contract_id=sample_contract.id,
        disbursement_number=1,
        disbursement_code="BID-001-D1",
        disbursement_name="Desembolso 1 BID",
        amount_original=Decimal("50000000"),
        amount_usd=Decimal("50000000"),
        disbursement_date=date(2023, 1, 15),
        maturity_date=date(2030, 12, 31),
        status="DESEMBOLSADO",
        excel_sheet="IFD",
        created_by=sample_user.id,
    )
    db.add(disb)
    db.commit()
    db.refresh(disb)
    return disb


_balance_id_counter = 0

@pytest.fixture()
def sample_balance(db, sample_disbursement):
    """Create a sample balance record."""
    global _balance_id_counter
    _balance_id_counter += 1
    bal = Balance(
        id=_balance_id_counter,
        disbursement_id=sample_disbursement.id,
        period_date=date(2025, 3, 31),
        outstanding_original=Decimal("45000000"),
        outstanding_usd=Decimal("45000000"),
        exchange_rate_used=Decimal("1.0"),
        residual_term_years=Decimal("5.75"),
        spread_bps=Decimal("150.0000"),
        amortization_usd=Decimal("500000"),
        interest_usd=Decimal("200000"),
        debt_service_usd=Decimal("700000"),
        is_active=True,
    )
    db.add(bal)
    db.commit()
    db.refresh(bal)
    return bal


@pytest.fixture()
def sample_config(db):
    """Insert debt ceiling system config."""
    cfg = SystemConfig(key="debt_ceiling_usd_mm", value=2500, description="Tope de endeudamiento")
    db.add(cfg)
    db.commit()
    return cfg
