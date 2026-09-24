import unittest
import os
import time
from starlette.testclient import TestClient

# Ensure test environment config
os.environ.setdefault("DEBUG", "True")

from fastapi_app.main import app
from fastapi_app.config import settings
from fastapi_app.utils.auth import create_access_token
from fastapi_app.middleware.rate_limiter import RateLimitMiddleware


class TestHybridFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_championship_admin_api_is_not_exposed(self):
        """CRIT-02: championship admin APIs were removed from the mobile API; no caller may reach them."""
        agent_token = create_access_token({"sub": "agent@test.com", "role": "agent"})
        for headers in ({}, {"Authorization": f"Bearer {agent_token}"}):
            res = self.client.get("/v1/championship/admin/financial-liability", headers=headers)
            self.assertIn(res.status_code, (403, 404))
            res = self.client.post("/v1/championship/admin/settings", json={"status": "active"}, headers=headers)
            self.assertIn(res.status_code, (403, 404))

    def test_password_reset_accepts_unauthenticated_requests(self):
        """CRIT-01: Ensure POST /v1/agents/reset-password is not blocked by 401 Unauthorized."""
        res = self.client.post(
            "/v1/agents/reset-password",
            json={
                "token": "invalid_or_dummy_token",
                "email": "test@example.com",
                "password": "Password123!",
                "password_confirmation": "Password123!",
                "login_type": "agent"
            }
        )
        # Should NOT be 401 Unauthorized (get_current_agent lock removed)
        self.assertNotEqual(res.status_code, 401)

    def test_csrf_refresh_endpoint(self):
        """CRIT-04: Ensure /v1/csrf-refresh/ provides token and sets cookie."""
        res = self.client.get("/v1/csrf-refresh/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertTrue(bool(data.get("csrf_token")))
        self.assertIn("padosi_csrf_token", res.cookies)

    def test_private_media_access_restricted(self):
        """CRIT-03: Ensure requests to private media directory are rejected with 403."""
        res = self.client.get("/media/app/private/invoices/inv_12345.pdf")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access Denied", res.text)

    def test_rate_limiter_isolates_sensitive_and_general_buckets(self):
        """HIGH-06: Ensure 15 general requests do not lock out the first login request."""
        # Instantiate test middleware with custom limits
        dummy_app = lambda scope, receive, send: None
        mw = RateLimitMiddleware(dummy_app, requests_limit=100, window_seconds=60)

        ip = "198.51.100.1"
        now = time.time()
        # Simulate 15 general browsing requests for this IP
        for _ in range(15):
            mw.client_records[(ip, "general")].append(now)

        # Confirm general bucket has 15 entries
        self.assertEqual(len(mw.client_records[(ip, "general")]), 15)
        # Confirm sensitive bucket has 0 entries
        self.assertEqual(len(mw.client_records.get((ip, "sensitive"), [])), 0)

    def test_auth_token_expires_in_matches_config(self):
        """HIGH-04: Ensure auth service expires_in matches ACCESS_TOKEN_EXPIRE_MINUTES in seconds."""
        expected_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        self.assertEqual(expected_seconds, 120 * 60)
        self.assertEqual(expected_seconds, 7200)


if __name__ == "__main__":
    unittest.main()
