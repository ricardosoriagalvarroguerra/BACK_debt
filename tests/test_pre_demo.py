"""Pre-demo integration tests.

These tests validate the critical user flows that will be shown during the demo.
They run against a SQLite in-memory DB using the shared conftest fixtures.
"""
import pytest
from datetime import date
from decimal import Decimal


# ====================================================================
# 1. AUTH FLOW
# ====================================================================

class TestAuthFlow:
    def test_login_success(self, client, sample_user):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "test@vpfinanzas.com", "password": "testpass123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client, sample_user):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "test@vpfinanzas.com", "password": "wrong"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 401

    def test_protected_endpoint_without_token(self, client):
        response = client.get("/api/v1/creditors/")
        assert response.status_code == 401

    def test_protected_endpoint_with_token(self, client, auth_header):
        response = client.get("/api/v1/creditors/", headers=auth_header)
        assert response.status_code == 200

    def test_get_me(self, client, auth_header, sample_user):
        response = client.get("/api/v1/auth/me", headers=auth_header)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@vpfinanzas.com"
        assert data["role"] == "ADMIN"


# ====================================================================
# 2. INSTRUMENT CREATION FLOW (Contract + Disbursement + Schedule)
# ====================================================================

class TestInstrumentCreationFlow:
    def test_create_contract(self, client, auth_header, sample_creditor, sample_currency):
        payload = {
            "creditor_id": sample_creditor.id,
            "contract_code": "TEST-001",
            "contract_name": "Test Contract 001",
            "approved_amount": 50.0,
            "currency_id": sample_currency.id,
            "maturity_date": "2030-06-30",
            "amortization_type": "AMORTIZABLE",
            "interest_rate_type": "VARIABLE",
            "base_rate": "SOFR",
            "spread_bps": 150.0,
            "grace_period_months": 24,
            "amort_frequency": "SEMESTRAL",
            "interest_frequency": "SEMESTRAL",
        }
        response = client.post("/api/v1/contracts", json=payload, headers=auth_header)
        assert response.status_code == 201
        data = response.json()
        assert data["contract_code"] == "TEST-001"
        assert data["amortization_type"] == "AMORTIZABLE"
        assert data["grace_period_months"] == 24

    def test_create_bullet_contract(self, client, auth_header, sample_creditor, sample_currency):
        payload = {
            "creditor_id": sample_creditor.id,
            "contract_code": "BULLET-001",
            "contract_name": "Bullet Bond",
            "approved_amount": 100.0,
            "currency_id": sample_currency.id,
            "maturity_date": "2030-12-31",
            "amortization_type": "BULLET",
            "interest_rate_type": "VARIABLE",
            "base_rate": "SOFR",
            "spread_bps": 180.0,
            "interest_frequency": "SEMESTRAL",
        }
        response = client.post("/api/v1/contracts", json=payload, headers=auth_header)
        assert response.status_code == 201
        data = response.json()
        assert data["amortization_type"] == "BULLET"

    @pytest.mark.skipif(True, reason="Auto-generates payments which needs BIGSERIAL; skipped on SQLite")
    def test_add_disbursement_generates_schedule(self, client, auth_header, sample_contract):
        payload = {
            "amount_usd": 25.0,
            "disbursement_date": "2025-01-15",
            "maturity_date": "2030-12-31",
        }
        response = client.post(
            f"/api/v1/contracts/{sample_contract.id}/disbursements",
            json=payload,
            headers=auth_header,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["amount_usd"] == 25.0
        assert data["status"] == "DESEMBOLSADO"
        # Schedule should have been auto-generated
        gen = data.get("generation_result")
        if gen:
            assert gen["payments_created"] > 0


# ====================================================================
# 3. CONTRACTS & DISBURSEMENTS CRUD
# ====================================================================

class TestContractsCRUD:
    def test_list_contracts(self, client, auth_header, sample_contract):
        response = client.get("/api/v1/contracts", headers=auth_header)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_get_contract_detail(self, client, auth_header, sample_contract):
        response = client.get(f"/api/v1/contracts/{sample_contract.id}", headers=auth_header)
        assert response.status_code == 200
        data = response.json()
        assert data["contract_code"] == "BID-001"

    def test_update_contract(self, client, auth_header, sample_contract):
        response = client.put(
            f"/api/v1/contracts/{sample_contract.id}",
            json={"contract_name": "Updated Name"},
            headers=auth_header,
        )
        assert response.status_code == 200
        assert response.json()["contract_name"] == "Updated Name"

    def test_list_disbursements(self, client, auth_header, sample_disbursement):
        response = client.get("/api/v1/disbursements", headers=auth_header)
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_get_disbursement_detail(self, client, auth_header, sample_disbursement):
        response = client.get(
            f"/api/v1/disbursements/{sample_disbursement.id}", headers=auth_header
        )
        assert response.status_code == 200
        data = response.json()
        assert data["disbursement_code"] == "BID-001-D1"


# ====================================================================
# 4. DASHBOARD ENDPOINTS
# ====================================================================

class TestDashboard:
    def test_summary(self, client, auth_header, sample_balance):
        response = client.get(
            "/api/v1/dashboard/summary",
            params={"period_date": "2025-03-31"},
            headers=auth_header,
        )
        assert response.status_code == 200
        data = response.json()
        assert float(data["total_outstanding_usd"]) > 0
        assert "ifd_outstanding_usd" in data
        assert "weighted_avg_spread_bps" in data

    def test_debt_ceiling(self, client, auth_header, sample_balance, sample_config):
        response = client.get(
            "/api/v1/dashboard/debt-ceiling",
            params={"period_date": "2025-03-31"},
            headers=auth_header,
        )
        assert response.status_code == 200
        data = response.json()
        assert "traffic_light" in data
        assert "utilization_pct" in data
        assert float(data["ceiling_limit_usd"]) > 0


# ====================================================================
# 5. PAYMENT SCHEDULE
# ====================================================================

class TestPayments:
    def test_list_payments(self, client, auth_header, sample_disbursement):
        response = client.get("/api/v1/payments", headers=auth_header)
        assert response.status_code == 200

    def test_list_payments_by_disbursement(self, client, auth_header, sample_disbursement):
        response = client.get(
            "/api/v1/payments",
            params={"disbursement_id": sample_disbursement.id},
            headers=auth_header,
        )
        assert response.status_code == 200


# ====================================================================
# 6. REPORTS & EXPORTS
# ====================================================================

class TestReports:
    def test_portfolio_summary_report(self, client, auth_header, sample_balance):
        response = client.get(
            "/api/v1/reports/portfolio-summary",
            params={"period_date": "2025-03-31"},
            headers=auth_header,
        )
        assert response.status_code == 200
        assert "total_outstanding_usd" in response.json()

    def test_export_csv(self, client, auth_header, sample_balance):
        response = client.post(
            "/api/v1/reports/export",
            params={"report_type": "portfolio", "format": "csv", "period_date": "2025-03-31"},
            headers=auth_header,
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")


# ====================================================================
# 7. PROJECTIONS
# ====================================================================

class TestProjections:
    def test_portfolio_projection(self, client, auth_header, sample_balance):
        response = client.get(
            "/api/v1/projections/portfolio",
            params={"months_ahead": 6},
            headers=auth_header,
        )
        assert response.status_code == 200
        data = response.json()
        assert "projections" in data
        assert data["months"] == 6

    def test_projection_metrics(self, client, auth_header, sample_balance):
        response = client.get(
            "/api/v1/projections/metrics",
            params={"period_date": "2025-03-31"},
            headers=auth_header,
        )
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data
        assert "total_outstanding_usd" in data["metrics"]


# ====================================================================
# 8. PAYMENT GENERATOR LOGIC
# ====================================================================

@pytest.mark.skipif(True, reason="PaymentGenerator uses BIGSERIAL which requires PostgreSQL; skipped on SQLite")
class TestPaymentGeneratorLogic:
    def test_bullet_generates_single_principal(self, db, sample_contract, sample_user):
        """BULLET instrument should have exactly 1 principal payment at maturity."""
        from app.models.disbursement import Disbursement
        from app.services.payment_generator import PaymentGenerator
        from app.models.payment import PaymentSchedule

        disb = Disbursement(
            contract_id=sample_contract.id,
            disbursement_number=99,
            disbursement_code="BULLET-TEST",
            disbursement_name="Bullet Test",
            amount_original=Decimal("100"),
            amount_usd=Decimal("100"),
            disbursement_date=date(2026, 1, 1),
            maturity_date=date(2031, 1, 1),
            status="DESEMBOLSADO",
            created_by=sample_user.id,
        )
        db.add(disb)
        db.commit()
        db.refresh(disb)

        payments = PaymentGenerator.generate_schedule(db, disb.id)
        principal_payments = [p for p in payments if p.payment_type == "PRINCIPAL"]
        interest_payments = [p for p in payments if p.payment_type == "INTEREST"]

        assert len(principal_payments) == 1
        assert principal_payments[0].amount_usd == Decimal("100")
        assert principal_payments[0].payment_date == date(2031, 1, 1)
        assert len(interest_payments) > 0  # Should have multiple interest payments

    def test_amortizable_with_grace(self, db, sample_creditor, sample_currency, sample_user):
        """AMORTIZABLE with grace should start payments after grace period."""
        from app.models.contract import Contract
        from app.models.disbursement import Disbursement
        from app.services.payment_generator import PaymentGenerator

        contract = Contract(
            creditor_id=sample_creditor.id,
            contract_code="AMORT-TEST",
            contract_name="Amort Test",
            status="VIGENTE",
            approved_amount=Decimal("60"),
            currency_id=sample_currency.id,
            maturity_date=date(2032, 6, 30),
            amortization_type="AMORTIZABLE",
            interest_rate_type="VARIABLE",
            spread_bps=Decimal("120"),
            grace_period_months=24,
            amort_frequency="SEMESTRAL",
            interest_frequency="SEMESTRAL",
            created_by=sample_user.id,
        )
        db.add(contract)
        db.commit()
        db.refresh(contract)

        disb = Disbursement(
            contract_id=contract.id,
            disbursement_number=1,
            disbursement_code="AMORT-TEST-D1",
            disbursement_name="Amort Test D1",
            amount_original=Decimal("60"),
            amount_usd=Decimal("60"),
            disbursement_date=date(2026, 6, 1),
            maturity_date=date(2032, 6, 30),
            status="DESEMBOLSADO",
            grace_period_months=24,
            created_by=sample_user.id,
        )
        db.add(disb)
        db.commit()
        db.refresh(disb)

        payments = PaymentGenerator.generate_schedule(db, disb.id)
        principal_payments = [p for p in payments if p.payment_type == "PRINCIPAL"]
        interest_payments = [p for p in payments if p.payment_type == "INTEREST"]

        # First principal should be after grace period (24m from 2026-06-01 = 2028-06-30)
        first_principal = min(p.payment_date for p in principal_payments)
        assert first_principal == date(2028, 6, 30)

        # Interest should start during grace (6m from disbursement)
        first_interest = min(p.payment_date for p in interest_payments)
        assert first_interest == date(2026, 12, 31)

        # Total principal should equal disbursement amount
        total_principal = sum(p.amount_usd for p in principal_payments)
        assert abs(total_principal - Decimal("60")) < Decimal("0.01")

        # All interest payments should be declining or flat
        interest_amounts = [p.amount_usd for p in sorted(interest_payments, key=lambda x: x.payment_date)]
        # First few (during grace) should be highest, last should be smallest
        assert interest_amounts[0] >= interest_amounts[-1]


# ====================================================================
# 9. EDGE CASES
# ====================================================================

class TestEdgeCases:
    def test_contract_not_found(self, client, auth_header):
        response = client.get("/api/v1/contracts/99999", headers=auth_header)
        assert response.status_code == 404

    def test_disbursement_not_found(self, client, auth_header):
        response = client.get("/api/v1/disbursements/99999", headers=auth_header)
        assert response.status_code == 404

    def test_invalid_contract_payload(self, client, auth_header):
        response = client.post("/api/v1/contracts", json={}, headers=auth_header)
        assert response.status_code == 422
