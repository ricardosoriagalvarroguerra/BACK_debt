"""Tests for authentication endpoints."""
import pytest


class TestLoginSuccess:
    def test_login_success(self, client, sample_user):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "test@vpfinanzas.com", "password": "testpass123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["email"] == "test@vpfinanzas.com"
        assert data["role"] == "ADMIN"
        assert "user_id" in data


class TestLoginInvalid:
    def test_login_wrong_password(self, client, sample_user):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "test@vpfinanzas.com", "password": "wrongpass"},
        )
        assert response.status_code == 401

    def test_login_nonexistent_user(self, client):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "nobody@example.com", "password": "anything"},
        )
        assert response.status_code == 401


class TestGetMe:
    def test_get_me_authenticated(self, client, auth_header):
        response = client.get("/api/v1/auth/me", headers=auth_header)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@vpfinanzas.com"
        assert data["role"] == "ADMIN"
        assert data["is_active"] is True

    def test_get_me_unauthenticated(self, client):
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_get_me_invalid_token(self, client):
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token-here"},
        )
        assert response.status_code == 401
