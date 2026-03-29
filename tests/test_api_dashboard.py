"""Integration tests for Dashboard API endpoints."""
import pytest
from datetime import date


class TestGetSummary:
    def test_get_summary_returns_200(self, client, auth_header, sample_balance):
        response = client.get(
            "/api/v1/dashboard/summary",
            params={"period_date": "2025-03-31"},
            headers=auth_header,
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_outstanding_usd" in data
        assert "ifd_outstanding_usd" in data
        assert "market_outstanding_usd" in data

    def test_get_summary_no_data(self, client, auth_header):
        response = client.get(
            "/api/v1/dashboard/summary",
            params={"period_date": "2020-01-01"},
            headers=auth_header,
        )
        assert response.status_code in (200, 404)


class TestGetDebtCeiling:
    def test_get_debt_ceiling_structure(self, client, auth_header, sample_balance, sample_config):
        response = client.get(
            "/api/v1/dashboard/debt-ceiling",
            params={"period_date": "2025-03-31"},
            headers=auth_header,
        )
        assert response.status_code == 200
        data = response.json()
        assert "traffic_light" in data
        assert "utilization_pct" in data
        assert "ceiling_limit_usd" in data
        assert "total_outstanding_usd" in data
        assert "available_capacity_usd" in data

    def test_debt_ceiling_default_date(self, client, auth_header):
        response = client.get("/api/v1/dashboard/debt-ceiling", headers=auth_header)
        assert response.status_code in (200, 404)


class TestGetTimeSeries:
    @pytest.mark.skipif(True, reason="time-series uses PostgreSQL-specific bool_or; skipped on SQLite")
    def test_get_time_series_structure(self, client, sample_balance):
        response = client.get(
            "/api/v1/dashboard/time-series",
            params={
                "date_from": "2025-01-01",
                "date_to": "2025-12-31",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "series" in data or "data" in data or isinstance(data, dict)

    @pytest.mark.skipif(True, reason="time-series uses PostgreSQL-specific bool_or; skipped on SQLite")
    def test_time_series_empty_range(self, client):
        response = client.get(
            "/api/v1/dashboard/time-series",
            params={
                "date_from": "2010-01-01",
                "date_to": "2010-12-31",
            },
        )
        assert response.status_code in (200, 404)
