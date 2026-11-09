"""
PayPal REST API Client Service (Sandbox Simulation Only).

Handles OAuth 2.0 client credentials token acquisition, Orders v2 API lifecycle
(creation and capture), and cryptographic webhook signature verification.
Strictly enforced to communicate with PayPal Sandbox endpoints only.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.core.currencies import get_currency_scale, validate_currency_code, validate_currency_scale
from app.models.export import Invoice

logger = logging.getLogger(__name__)


class PayPalServiceError(Exception):
    """Base exception for PayPal API errors."""

    def __init__(self, message: str, status_code: int = 502, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


class PayPalClient:
    """Client for interacting with PayPal Sandbox REST APIs."""

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        webhook_id: str | None = None,
    ):
        self.base_url = (base_url or settings.PAYPAL_BASE_URL).rstrip("/")
        self.client_id = client_id or settings.PAYPAL_CLIENT_ID
        self.client_secret = client_secret or settings.PAYPAL_CLIENT_SECRET
        self.webhook_id = webhook_id or settings.PAYPAL_WEBHOOK_ID

        # Token caching state
        self._cached_token: str | None = None
        self._token_expires_at: datetime | None = None

        # Strict validation
        if settings.PAYPAL_ENVIRONMENT.lower() != "sandbox":
            raise ValueError(
                "ProcureMind PayPal integration is strictly locked to Sandbox. "
                f"PAYPAL_ENVIRONMENT is set to '{settings.PAYPAL_ENVIRONMENT}'"
            )

    def _format_currency_amount(self, amount: Decimal, currency: str) -> str:
        """Formats Decimal to exact string representation according to currency scale."""
        clean_curr = validate_currency_code(currency)
        validate_currency_scale(amount, clean_curr)
        scale = get_currency_scale(clean_curr)
        if scale == 0:
            return f"{amount:.0f}"
        return f"{amount:.{scale}f}"

    def get_access_token(self) -> str:
        """
        Retrieves a valid OAuth2 bearer token from PayPal Sandbox.
        Caches token in-memory and refreshes 60 seconds before expiration.
        """
        now = datetime.now(UTC)
        if self._cached_token and self._token_expires_at and now < self._token_expires_at:
            return self._cached_token

        if not self.client_id or not self.client_secret:
            raise PayPalServiceError(
                "PayPal Sandbox credentials are unconfigured on server. "
                "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be set.",
                status_code=503,
            )

        token_url = f"{self.base_url}/v1/oauth2/token"
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    token_url,
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials"},
                    headers={"Accept": "application/json", "Accept-Language": "en_US"},
                )
        except Exception as exc:
            logger.error("Failed to connect to PayPal OAuth endpoint: %s", exc)
            raise PayPalServiceError(f"PayPal connection error: {exc}", status_code=502) from exc

        if res.status_code != 200:
            logger.error(
                "PayPal OAuth rejected credentials with status %d: %s", res.status_code, res.text
            )
            raise PayPalServiceError(
                "Failed to authenticate with PayPal Sandbox API.",
                status_code=res.status_code,
                details=res.text,
            )

        data = res.json()
        access_token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))
        if not access_token:
            raise PayPalServiceError("PayPal OAuth response missing access_token.", status_code=502)

        # Cache with 60-second safety margin
        from datetime import timedelta

        self._cached_token = access_token
        self._token_expires_at = now + timedelta(seconds=max(expires_in - 60, 60))
        return access_token

    def create_order(
        self,
        invoice: Invoice,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """
        Creates a PayPal checkout order with intent=CAPTURE for a specific commercial invoice.
        Passes deterministic PayPal-Request-Id to guarantee external idempotency.
        """
        token = self.get_access_token()
        formatted_amount = self._format_currency_amount(invoice.total_amount, invoice.currency)

        request_id = idempotency_key or f"PM-ORDER-{invoice.id}"
        orders_url = f"{self.base_url}/v2/checkout/orders"

        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": f"INV-{invoice.id}",
                    "invoice_id": invoice.invoice_number,
                    "custom_id": str(invoice.id),
                    "description": f"PayPal Sandbox / simulated export payment for Invoice {invoice.invoice_number}",
                    "amount": {
                        "currency_code": invoice.currency,
                        "value": formatted_amount,
                    },
                }
            ],
            "application_context": {
                "brand_name": "ProcureMind",
                "landing_page": "NO_PREFERENCE",
                "user_action": "PAY_NOW",
            },
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": request_id,
            "Prefer": "return=representation",
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                res = client.post(orders_url, json=payload, headers=headers)
        except Exception as exc:
            logger.error("Failed to connect to PayPal create order API: %s", exc)
            raise PayPalServiceError(f"PayPal connection error: {exc}", status_code=502) from exc

        if res.status_code not in (200, 201):
            logger.error("PayPal order creation failed (%d): %s", res.status_code, res.text)
            raise PayPalServiceError(
                f"Failed to create PayPal order: {res.text}",
                status_code=res.status_code,
                details=res.text,
            )

        return res.json()

    def capture_order(
        self,
        order_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """
        Captures an approved PayPal order.
        Passes deterministic PayPal-Request-Id to prevent duplicate charges.
        """
        token = self.get_access_token()
        request_id = idempotency_key or f"PM-CAPTURE-{order_id}"
        capture_url = f"{self.base_url}/v2/checkout/orders/{order_id}/capture"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": request_id,
            "Prefer": "return=representation",
        }

        try:
            with httpx.Client(timeout=25.0) as client:
                res = client.post(capture_url, headers=headers)
        except Exception as exc:
            logger.error("Failed to connect to PayPal capture order API: %s", exc)
            raise PayPalServiceError(f"PayPal connection error: {exc}", status_code=502) from exc

        if res.status_code not in (200, 201):
            logger.error("PayPal capture failed (%d): %s", res.status_code, res.text)
            raise PayPalServiceError(
                f"PayPal capture rejected: {res.text}",
                status_code=res.status_code,
                details=res.text,
            )

        return res.json()

    def verify_webhook_signature(
        self,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> bool:
        """
        Verifies incoming webhook signature with PayPal's cryptographic verification API.
        Returns True if verification_status == 'SUCCESS', False otherwise.
        """
        if not self.webhook_id:
            logger.warning(
                "PAYPAL_WEBHOOK_ID is unconfigured; webhook signature cannot be verified."
            )
            return False

        # Normalize header keys to lowercase
        norm_headers = {k.lower(): v for k, v in headers.items()}
        auth_algo = norm_headers.get("paypal-auth-algo")
        cert_url = norm_headers.get("paypal-cert-url")
        transmission_id = norm_headers.get("paypal-transmission-id")
        transmission_sig = norm_headers.get("paypal-transmission-sig")
        transmission_time = norm_headers.get("paypal-transmission-time")

        if not all([auth_algo, cert_url, transmission_id, transmission_sig, transmission_time]):
            logger.warning(
                "Webhook request missing required PayPal transmission signature headers."
            )
            return False

        token = self.get_access_token()
        verify_url = f"{self.base_url}/v1/notifications/verify-webhook-signature"

        verification_payload = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": transmission_time,
            "webhook_id": self.webhook_id,
            "webhook_event": body,
        }

        req_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(verify_url, json=verification_payload, headers=req_headers)
        except httpx.HTTPError as exc:
            logger.error("Failed to connect to PayPal webhook verification endpoint: %s", exc)
            return False

        if res.status_code != 200:
            logger.error(
                "PayPal webhook verification endpoint responded with %d: %s",
                res.status_code,
                res.text,
            )
            return False

        status = res.json().get("verification_status")
        return status == "SUCCESS"


# Default singleton instance
paypal_client = PayPalClient()
