"""Tests for CalculationEngine."""
from datetime import date
from decimal import Decimal
import itertools

import pytest

from app.models.balance import Balance
from app.models.config import SystemConfig
from app.services.calculation_engine import CalculationEngine

# BigInteger PKs need explicit IDs in SQLite
_id_seq = itertools.count(10000)


def _make_balance(**kwargs):
    kwargs.setdefault("id", next(_id_seq))
    return Balance(**kwargs)


class TestTotalOutstanding:
    def test_total_outstanding_single_balance(self, db, sample_balance):
        total = CalculationEngine.total_outstanding(db, date(2025, 3, 31))
        assert total == Decimal("45000000")

    def test_total_outstanding_multiple_balances(self, db, sample_disbursement):
        """Two balances on the same date sum correctly."""
        for amount in [Decimal("20000000"), Decimal("30000000")]:
            db.add(_make_balance(
                disbursement_id=sample_disbursement.id,
                period_date=date(2025, 3, 31),
                outstanding_original=amount,
                outstanding_usd=amount,
                is_active=True,
            ))
        db.commit()

        total = CalculationEngine.total_outstanding(db, date(2025, 3, 31))
        assert total == Decimal("50000000")

    def test_total_outstanding_no_data(self, db):
        total = CalculationEngine.total_outstanding(db, date(2020, 1, 1))
        assert total == Decimal("0")

    def test_total_outstanding_by_creditor_type(self, db, sample_balance):
        total_ifd = CalculationEngine.total_outstanding(db, date(2025, 3, 31), "IFD")
        assert total_ifd == Decimal("45000000")

        total_market = CalculationEngine.total_outstanding(db, date(2025, 3, 31), "MERCADO")
        assert total_market == Decimal("0")


class TestWeightedAverageSpread:
    def test_weighted_average_spread_single(self, db, sample_balance):
        spread = CalculationEngine.weighted_average_spread(db, date(2025, 3, 31))
        # With one balance, weighted average == that balance's spread
        assert spread is not None
        assert abs(float(spread) - 150.0) < 0.01

    def test_weighted_average_spread_multiple(self, db, sample_disbursement):
        """SUMPRODUCT formula: (100*200 + 200*100) / (100+200) = 133.33 bps."""
        db.add(_make_balance(
            disbursement_id=sample_disbursement.id,
            period_date=date(2025, 3, 31),
            outstanding_original=Decimal("100"),
            outstanding_usd=Decimal("100"),
            spread_bps=Decimal("200"),
            is_active=True,
        ))
        db.add(_make_balance(
            disbursement_id=sample_disbursement.id,
            period_date=date(2025, 3, 31),
            outstanding_original=Decimal("200"),
            outstanding_usd=Decimal("200"),
            spread_bps=Decimal("100"),
            is_active=True,
        ))
        db.commit()

        spread = CalculationEngine.weighted_average_spread(db, date(2025, 3, 31))
        assert spread is not None
        assert abs(float(spread) - 133.33) < 0.01

    def test_weighted_average_spread_no_data(self, db):
        result = CalculationEngine.weighted_average_spread(db, date(2020, 1, 1))
        assert result is None


class TestInterestCalculation:
    def test_basic_interest(self):
        """Interest = 1,000,000 * (0 + 150) / 10000 * 30 / 360 = 1,250."""
        interest = CalculationEngine.interest_calculation(
            outstanding_usd=Decimal("1000000"),
            spread_bps=Decimal("150"),
            base_rate_bps=Decimal("0"),
            days_in_period=30,
            day_count=360,
        )
        assert abs(float(interest) - 1250.0) < 0.01

    def test_interest_with_base_rate(self):
        """Interest = 1,000,000 * (500 + 150) / 10000 * 30 / 360 = 5,416.67."""
        interest = CalculationEngine.interest_calculation(
            outstanding_usd=Decimal("1000000"),
            spread_bps=Decimal("150"),
            base_rate_bps=Decimal("500"),
            days_in_period=30,
            day_count=360,
        )
        expected = 1000000 * 650 / 10000 * 30 / 360
        assert abs(float(interest) - expected) < 0.01

    def test_interest_zero_outstanding(self):
        interest = CalculationEngine.interest_calculation(
            outstanding_usd=Decimal("0"),
            spread_bps=Decimal("200"),
        )
        assert float(interest) == 0.0


class TestDebtCeilingCheck:
    def test_ceiling_green(self, db, sample_disbursement, sample_config):
        """Outstanding of 500 is within VERDE band (0-1500)."""
        db.add(_make_balance(
            disbursement_id=sample_disbursement.id,
            period_date=date(2025, 3, 31),
            outstanding_original=Decimal("500"),
            outstanding_usd=Decimal("500"),
            is_active=True,
        ))
        db.commit()

        result = CalculationEngine.debt_ceiling_check(db, date(2025, 3, 31))
        assert result["traffic_light"] == "VERDE"
        assert result["status"] == "DENTRO_LIMITE"
        assert result["total_outstanding_usd"] == 500.0

    def test_ceiling_rojo(self, db, sample_disbursement, sample_config):
        """Outstanding above the ROJO threshold (>= 2400)."""
        db.add(_make_balance(
            disbursement_id=sample_disbursement.id,
            period_date=date(2025, 3, 31),
            outstanding_original=Decimal("2500"),
            outstanding_usd=Decimal("2500"),
            is_active=True,
        ))
        db.commit()

        result = CalculationEngine.debt_ceiling_check(db, date(2025, 3, 31))
        assert result["traffic_light"] == "ROJO"

    def test_ceiling_with_scenario_addition(self, db, sample_balance, sample_config):
        result = CalculationEngine.debt_ceiling_check(
            db, date(2025, 3, 31), scenario_additions=Decimal("100000000")
        )
        assert result["total_outstanding_usd"] == 145000000.0
