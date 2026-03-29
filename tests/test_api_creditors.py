"""Tests for Creditor API endpoints."""
import pytest


class TestListCreditors:
    def test_list_creditors_empty(self, client, auth_header):
        response = client.get("/api/v1/creditors/", headers=auth_header)
        assert response.status_code == 200
        assert response.json() == []

    def test_list_creditors_returns_data(self, client, auth_header, sample_creditor):
        response = client.get("/api/v1/creditors/", headers=auth_header)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["code"] == "BID"
        assert data[0]["creditor_type"] == "IFD"

    def test_list_creditors_filter_type(self, client, auth_header, sample_creditor):
        response = client.get("/api/v1/creditors/", headers=auth_header, params={"creditor_type": "MERCADO"})
        assert response.status_code == 200
        assert len(response.json()) == 0

        response = client.get("/api/v1/creditors/", headers=auth_header, params={"creditor_type": "IFD"})
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestCreateCreditor:
    def test_create_creditor(self, client, auth_header, sample_user):
        payload = {
            "code": "CAF",
            "name": "Corporacion Andina de Fomento",
            "short_name": "CAF",
            "creditor_type": "IFD",
            "subtype": "MULTILATERAL",
            "country": "VE",
        }
        response = client.post("/api/v1/creditors/", json=payload, headers=auth_header)
        assert response.status_code == 201
        data = response.json()
        assert data["code"] == "CAF"
        assert data["creditor_type"] == "IFD"
        assert data["is_active"] is True

    def test_create_creditor_duplicate_code(self, client, auth_header, sample_creditor):
        payload = {
            "code": "BID",
            "name": "Duplicate",
            "short_name": "DUP",
            "creditor_type": "IFD",
            "subtype": "MULTILATERAL",
        }
        response = client.post("/api/v1/creditors/", json=payload, headers=auth_header)
        assert response.status_code == 409


class TestGetCreditor:
    def test_get_creditor_by_id(self, client, auth_header, sample_creditor):
        response = client.get(f"/api/v1/creditors/{sample_creditor.id}", headers=auth_header)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "BID"
        assert data["name"] == "Banco Interamericano de Desarrollo"

    def test_get_creditor_not_found(self, client, auth_header):
        response = client.get("/api/v1/creditors/99999", headers=auth_header)
        assert response.status_code == 404
