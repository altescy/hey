"""GitHub Copilot authentication via GitHub's Device Authorization Grant (RFC 8628).

Usage
-----
1. Call :func:`login` once interactively to obtain and store a GitHub OAuth token.
2. Construct :class:`CopilotAuthProvider` and pass it to the Copilot engine.
   The provider simply reads the stored token; GitHub OAuth tokens are long-lived
   and do not require refresh.

GitHub Enterprise
-----------------
Set *github_domain* to your GHE hostname (e.g. ``"company.ghe.com"``) to use an
enterprise instance.  The Copilot API base URL will automatically become
``https://copilot-api.{github_domain}``.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from .store import delete_token, load_token, save_token

_PROVIDER = "github-copilot"
_CLIENT_ID = "Ov23li8tweQw6odWQebz"
_POLL_SAFETY_MARGIN = 3  # extra seconds on top of server-specified interval


# ---------------------------------------------------------------------------
# Login (interactive, run once)
# ---------------------------------------------------------------------------


async def login(github_domain: str = "github.com") -> None:
    """Run the Device Authorization Grant flow and persist the token.

    Prints the user-code and verification URL to stdout, then polls until the
    user has authorised the device or the flow times out.
    """
    device_url = f"https://{github_domain}/login/device/code"
    token_url = f"https://{github_domain}/login/oauth/access_token"

    async with httpx.AsyncClient() as client:
        # Step 1 – request device code
        resp = await client.post(
            device_url,
            json={"client_id": _CLIENT_ID, "scope": "read:user"},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

        user_code: str = data["user_code"]
        device_code: str = data["device_code"]
        verification_uri: str = data["verification_uri"]
        interval: int = int(data.get("interval", 5)) + _POLL_SAFETY_MARGIN
        expires_in: int = int(data.get("expires_in", 900))
        deadline = time.monotonic() + expires_in

        print(f"\nOpen  {verification_uri}")
        print(f"Enter code: {user_code}\n")

        # Step 2 – poll for access token
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            poll_resp = await client.post(
                token_url,
                json={
                    "client_id": _CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()

            error = poll_data.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                # RFC 8628 §3.5 – bump interval by ≥5 seconds
                interval += 5
                continue
            if error:
                raise RuntimeError(f"GitHub device flow error: {error}")

            access_token: str = poll_data["access_token"]
            save_token(
                _PROVIDER,
                {
                    "access_token": access_token,
                    # GitHub tokens are long-lived; store 0 to signal no expiry.
                    "expires": 0,
                    "github_domain": github_domain,
                },
            )
            print("GitHub Copilot: authentication successful.")
            return

    raise TimeoutError("Device authorization flow timed out.")


def logout() -> None:
    """Remove stored Copilot credentials."""
    delete_token(_PROVIDER)
    print("GitHub Copilot: credentials removed.")


# ---------------------------------------------------------------------------
# AuthProvider implementation
# ---------------------------------------------------------------------------


class CopilotAuthProvider:
    """Returns a valid GitHub OAuth token, running the Device Flow interactively
    on the first call if no token has been stored yet.

    GitHub tokens are long-lived and need no refresh once obtained.
    """

    def __init__(self, github_domain: str = "github.com") -> None:
        self._github_domain = github_domain

    @property
    def api_base_url(self) -> str:
        if self._github_domain == "github.com":
            return "https://api.githubcopilot.com"
        return f"https://copilot-api.{self._github_domain}"

    async def get_token(self) -> str:
        data = load_token(_PROVIDER)
        if not data or not data.get("access_token"):
            print("GitHub Copilot: no credentials found — starting login flow.")
            await login(github_domain=self._github_domain)
            data = load_token(_PROVIDER)
        return data["access_token"]  # type: ignore[index]
