"""OpenAI Codex authentication.

Supports two flows:
- **Browser / PKCE** (default): opens a local callback server, launches a
  browser, exchanges the authorization code with a PKCE verifier.
- **Device** (headless): polls OpenAI's device-auth endpoint; user enters a
  code at ``https://auth.openai.com/codex/device``.

Tokens expire and are silently refreshed by :class:`CodexAuthProvider` before
each API call.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from typing import Any

import httpx

from .store import delete_token, load_token, save_token

_PROVIDER = "codex"
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_AUTH_BASE = "https://auth.openai.com"
_POLL_SAFETY_MARGIN = 3  # extra seconds on top of server-specified interval

# Codex API endpoint (all requests are rewritten here)
CODEX_API_URL = "https://chatgpt.com/backend-api/codex/responses"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge) for S256 PKCE."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode the payload section of a JWT without verifying the signature."""
    try:
        payload_b64 = token.split(".")[1]
        # Add padding if necessary
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


def _extract_account_id(id_token: str) -> str | None:
    claims = _decode_jwt_payload(id_token)
    account_id = claims.get("chatgpt_account_id") or (claims.get("https://api.openai.com/auth") or {}).get(
        "chatgpt_account_id"
    )
    if account_id:
        return str(account_id)
    orgs = claims.get("organizations")
    if orgs and isinstance(orgs, list) and orgs:
        return str(orgs[0].get("id", ""))
    return None


def _save(token_data: dict[str, Any]) -> None:
    save_token(_PROVIDER, token_data)


async def _exchange_code(
    client: httpx.AsyncClient,
    code: str,
    verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    resp = await client.post(
        f"{_AUTH_BASE}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": _CLIENT_ID,
            "code_verifier": verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.json()


async def _refresh(refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_AUTH_BASE}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": _CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


def _build_token_record(raw: dict[str, Any]) -> dict[str, Any]:
    expires = int(time.time()) + int(raw.get("expires_in", 3600))
    account_id = _extract_account_id(raw.get("id_token", ""))
    return {
        "access_token": raw["access_token"],
        "refresh_token": raw.get("refresh_token", ""),
        "id_token": raw.get("id_token", ""),
        "expires": expires,
        "account_id": account_id,
    }


# ---------------------------------------------------------------------------
# Login flows
# ---------------------------------------------------------------------------


async def login_browser(port: int = 1455) -> None:
    """PKCE + local callback server flow (opens a browser)."""
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://localhost:{port}/auth/callback"

    params = {
        "response_type": "code",
        "client_id": _CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email offline_access",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": "hey",
    }
    auth_url = f"{_AUTH_BASE}/oauth/authorize?" + urllib.parse.urlencode(params)

    received_code: list[str] = []
    received_state: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:  # silence access log
            pass

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            received_code.extend(qs.get("code", []))
            received_state.extend(qs.get("state", []))
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Authentication complete. You can close this window.</body></html>")

    server = HTTPServer(("localhost", port), _Handler)
    print(f"\nOpening browser for Codex authentication…\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Wait for callback (run in executor to avoid blocking event loop)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, server.handle_request)
    server.server_close()

    if not received_code:
        raise RuntimeError("No authorization code received.")
    if received_state and received_state[0] != state:
        raise RuntimeError("OAuth state mismatch — possible CSRF.")

    async with httpx.AsyncClient() as client:
        raw = await _exchange_code(client, received_code[0], verifier, redirect_uri)

    _save(_build_token_record(raw))
    print("Codex: authentication successful.")


async def login_device() -> None:
    """Device authorization flow (headless, no browser required)."""
    async with httpx.AsyncClient() as client:
        # Step 1 – request user code
        resp = await client.post(
            f"{_AUTH_BASE}/api/accounts/deviceauth/usercode",
            json={"client_id": _CLIENT_ID},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

        device_auth_id: str = data["device_auth_id"]
        user_code: str = data["user_code"]
        interval: int = int(data.get("interval", 5)) + _POLL_SAFETY_MARGIN

        print("\nOpen  https://auth.openai.com/codex/device")
        print(f"Enter code: {user_code}\n")

        # Step 2 – poll for authorization code
        while True:
            await asyncio.sleep(interval)
            poll_resp = await client.post(
                f"{_AUTH_BASE}/api/accounts/deviceauth/token",
                json={"device_auth_id": device_auth_id, "user_code": user_code},
                headers={"Accept": "application/json"},
            )
            if poll_resp.status_code in (403, 404):
                continue  # still pending
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()

            auth_code: str = poll_data["authorization_code"]
            code_verifier: str = poll_data["code_verifier"]

            # Step 3 – exchange for tokens
            raw = await _exchange_code(
                client,
                auth_code,
                code_verifier,
                f"{_AUTH_BASE}/deviceauth/callback",
            )
            _save(_build_token_record(raw))
            print("Codex: authentication successful.")
            return


def logout() -> None:
    """Remove stored Codex credentials."""
    delete_token(_PROVIDER)
    print("Codex: credentials removed.")


# ---------------------------------------------------------------------------
# AuthProvider implementation
# ---------------------------------------------------------------------------


class CodexAuthProvider:
    """Returns a valid Codex access token, running the login flow interactively
    on the first call if no token has been stored yet.

    Expired tokens are refreshed silently.  If the refresh token is also
    missing the browser-based login flow is re-run automatically.

    Also exposes :meth:`get_account_id` for the ``ChatGPT-Account-Id`` request
    header required by organisation subscriptions.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def _ensure_logged_in(self) -> None:
        """Run login_browser (or login_device as fallback) if no token stored."""
        import sys

        if sys.stdout.isatty():
            await login_browser()
        else:
            await login_device()

    async def get_token(self) -> str:
        async with self._lock:
            data = load_token(_PROVIDER)
            if not data or not data.get("access_token"):
                print("Codex: no credentials found — starting login flow.")
                await self._ensure_logged_in()
                data = load_token(_PROVIDER)

            # Refresh if expired (with a 30-second safety window)
            if data.get("expires", 0) - 30 < time.time():  # type: ignore[union-attr]
                refresh_tok = (data or {}).get("refresh_token", "")  # type: ignore[union-attr]
                if not refresh_tok:
                    print("Codex: token expired — starting login flow again.")
                    await self._ensure_logged_in()
                    data = load_token(_PROVIDER)
                else:
                    raw = await _refresh(refresh_tok)
                    data = _build_token_record(raw)
                    _save(data)

            return data["access_token"]  # type: ignore[index]

    async def get_account_id(self) -> str | None:
        """Return the ChatGPT account ID extracted from the stored id_token."""
        data = load_token(_PROVIDER)
        if not data:
            return None
        return data.get("account_id")
