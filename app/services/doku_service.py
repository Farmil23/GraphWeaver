"""
DOKU Payment Gateway Service — Sandbox Integration
Generates real DOKU checkout links via the DOKU Checkout v1 API.

DOKU API Signature scheme:
  Digest     = Base64(SHA-256(RequestBody))
  Component  = "Client-Id:{id}\\nRequest-Id:{rid}\\nRequest-Timestamp:{ts}\\nRequest-Body:{digest}"
  Signature  = "HMAC SHA256=" + Base64(HMAC-SHA256(Component, SecretKey))
"""

import hashlib
import hmac as _hmac
import base64
import uuid
import json
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Pricing ──────────────────────────────────────────────────────────────────
DEEP_INVESTIGATION_PRICE_IDR = 50_000   # Rp 50,000


class DokuService:
    def __init__(self):
        self.client_id  = settings.DOKU_CLIENT_ID
        self.secret_key = settings.DOKU_SECRET_KEY
        self.base_url   = settings.DOKU_BASE_URL.rstrip("/")

    # ── Signature generation ──────────────────────────────────────────────

    def _sign(self, request_id: str, timestamp: str, body_str: str,
              request_target: str = "/checkout/v1/payment") -> str:
        """
        DOKU HMAC-SHA256 signature — 5-component format (non-SNAP):
          Client-Id:{id}
          Request-Id:{rid}
          Request-Timestamp:{ts}
          Request-Target:{path}
          Digest:{base64(sha256(body))}
        """
        digest    = base64.b64encode(hashlib.sha256(body_str.encode()).digest()).decode()
        component = (
            f"Client-Id:{self.client_id}\n"
            f"Request-Id:{request_id}\n"
            f"Request-Timestamp:{timestamp}\n"
            f"Request-Target:{request_target}\n"
            f"Digest:{digest}"
        )
        raw_sig = _hmac.new(
            self.secret_key.encode(),
            component.encode(),
            hashlib.sha256,
        ).digest()
        return f"HMACSHA256={base64.b64encode(raw_sig).decode()}"

    # ── Payment link creation ─────────────────────────────────────────────

    def create_payment_link(
        self,
        session_id: str,
        entity_name: Optional[str] = "B2B Client",
    ) -> dict:
        """
        Create a real DOKU Checkout payment link for 'Deep Investigation'.

        Returns:
          {
            "success": bool,
            "url": str,               # DOKU checkout URL
            "invoice_number": str,    # For webhook matching
            "expired_date": str,
          }
        """
        invoice_number = f"KYC-{session_id[:12].upper()}"
        request_id     = str(uuid.uuid4())
        timestamp      = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        import os as _os
        # APP_BASE_URL = production URL (Railway/Render/etc.)
        # Falls back to localhost for local dev
        app_base_url = _os.getenv("APP_BASE_URL", "").rstrip("/")
        if not app_base_url:
            local_port   = _os.getenv("APP_PORT", "8000")
            app_base_url = f"http://localhost:{local_port}"

        ngrok_url = _os.getenv("NGROK_URL", "").rstrip("/")
        # Webhook URL: prefer APP_BASE_URL (deployed), then NGROK (local tunnel)
        webhook_base     = app_base_url if "localhost" not in app_base_url else (ngrok_url or app_base_url)
        notification_url = f"{webhook_base}/webhooks/doku-paid" if webhook_base else ""

        success_url = f"{app_base_url}/payment-success?session_id={session_id}"
        cancel_url  = f"{app_base_url}/payment-cancelled?session_id={session_id}"

        logger.info(f"🔔 DOKU callback={success_url} | notification={notification_url}")

        body_dict = {
            "order": {
                "invoice_number":      invoice_number,
                "amount":              DEEP_INVESTIGATION_PRICE_IDR,
                "currency":            "IDR",
                "callback_url":        success_url,
                "callback_url_cancel": cancel_url,
                "line_items": [
                    {
                        "name":     "FinAgent Deep Investigation",
                        "price":    DEEP_INVESTIGATION_PRICE_IDR,
                        "quantity": 1,
                    }
                ],
            },
            "payment": {
                "payment_due_date": 60,
            },
            "additional_info": {
                "session_id": session_id,
            },
        }

        # Inject notification_url only if we have a public URL
        if notification_url:
            body_dict["order"]["notification_url"] = notification_url

        body_str  = json.dumps(body_dict, separators=(",", ":"))
        signature = self._sign(request_id, timestamp, body_str)

        headers = {
            "Client-Id":         self.client_id,
            "Request-Id":        request_id,
            "Request-Timestamp": timestamp,
            "Signature":         signature,
            "Content-Type":      "application/json",
        }

        api_url = f"{self.base_url}/checkout/v1/payment"
        logger.info(f"💳 Calling DOKU API: POST {api_url} | invoice={invoice_number}")

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(api_url, content=body_str, headers=headers)

            logger.info(f"DOKU API → {resp.status_code}")

            if resp.status_code in (200, 201):
                data        = resp.json()
                # Response wrapped in "response" key per DOKU docs
                resp_data   = data.get("response", data)
                payment_url = (
                    resp_data.get("payment", {}).get("url")
                    or data.get("payment", {}).get("url")
                    or data.get("url")
                    or ""
                )
                expired     = resp_data.get("payment", {}).get("expired_date", "")

                if payment_url:
                    logger.info(f"✅ DOKU payment link: {payment_url}")
                    return {
                        "success":        True,
                        "url":            payment_url,
                        "invoice_number": invoice_number,
                        "expired_date":   expired,
                    }

                logger.warning(f"DOKU returned 200 but no payment URL. Body: {data}")

            else:
                logger.warning(f"DOKU API error {resp.status_code}: {resp.text[:300]}")

        except httpx.TimeoutException:
            logger.error("DOKU API timed out.")
        except Exception as exc:
            logger.error(f"DOKU API exception: {exc}")

        # ── Graceful fallback (sandbox mock) ─────────────────────────────
        fallback_url = f"https://checkout.doku.com/pay/kyc-{session_id[:8]}"
        logger.info(f"⚠️  Using fallback DOKU mock link: {fallback_url}")
        return {
            "success":        False,
            "url":            fallback_url,
            "invoice_number": invoice_number,
            "expired_date":   "",
        }

    # ── Invoice ↔ Session mapping helper ─────────────────────────────────

    @staticmethod
    def session_id_from_invoice(invoice_number: str) -> Optional[str]:
        """
        Reverse-maps a DOKU invoice number back to a session_id fragment.
        Invoice format: KYC-{session_id[:12].upper()}
        """
        if invoice_number.startswith("KYC-"):
            return invoice_number[4:].lower()
        return None


# Singleton instance
doku_service = DokuService()
