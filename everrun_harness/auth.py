from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import uuid
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .providers import config_home, load_auth, save_auth


AUTH_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REDIRECT_URI = "http://127.0.0.1:1455/auth/callback"


def _post_form(data: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(data).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        details = ""
        if hasattr(exc, "read"):
            details = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"OpenAI sign-in token exchange failed: {details or exc}") from exc


def _verify_id_token(id_token: str, client_id: str, nonce: str) -> dict[str, Any]:
    try:
        import jwt
    except ImportError as exc:
        raise RuntimeError("OpenAI sign-in needs PyJWT with cryptography. Reinstall Everrun after updating it.") from exc
    key = jwt.PyJWKClient("https://auth.openai.com/.well-known/jwks.json").get_signing_key_from_jwt(id_token)
    claims = jwt.decode(id_token, key.key, algorithms=["RS256", "ES256"], audience=client_id,
                        issuer="https://auth.openai.com", options={"require": ["sub", "exp", "iat", "nonce"]})
    if claims.get("nonce") != nonce:
        raise RuntimeError("OpenAI sign-in nonce validation failed")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise RuntimeError("OpenAI sign-in returned no account subject")
    return claims


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_error(404)
            return
        type(self).result = {key: values[-1] for key, values in urllib.parse.parse_qs(parsed.query).items()}
        body = b"Everrun sign-in received. You can close this tab and return to the terminal."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def login_openai() -> None:
    auth = load_auth()
    entry = auth.get("openai", {})
    host_id = entry.get("ext_agent_host_id") or f"urn:uuid:{uuid.uuid4()}"
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    requested_client = entry.get("client_id")
    parameters = {
        "client_id": requested_client or "dynamic_agent_client",
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "ext_agent_host_id": host_id,
    }
    if requested_client:
        if entry.get("id_token"):
            parameters["id_token_hint"] = entry["id_token"]
        if entry.get("email"):
            parameters["login_hint"] = entry["email"]
    else:
        parameters["agent_name_hint"] = "Everrun"

    handler = type("CallbackHandler", (_CallbackHandler,), {"result": {}})
    try:
        server = HTTPServer(("127.0.0.1", 1455), handler)
    except OSError as exc:
        raise RuntimeError("Could not start OAuth callback on 127.0.0.1:1455; close the process using that port and retry") from exc
    server.timeout = 300
    url = AUTH_URL + "?" + urllib.parse.urlencode(parameters)
    print("Opening OpenAI sign-in in your browser...")
    opened = webbrowser.open(url)
    if not opened:
        # The ID token hint is optional; never print it into terminal history.
        safe_parameters = {key: value for key, value in parameters.items() if key != "id_token_hint"}
        print("Open this sign-in URL in your browser:")
        print(AUTH_URL + "?" + urllib.parse.urlencode(safe_parameters))
    try:
        deadline = time.monotonic() + 300
        while not handler.result and time.monotonic() < deadline:
            server.handle_request()
        result = handler.result
    finally:
        server.server_close()
    if not result:
        raise RuntimeError("OpenAI sign-in timed out")
    if result.get("state") != state:
        raise RuntimeError("OpenAI sign-in state validation failed")
    if result.get("error"):
        raise RuntimeError(f"OpenAI sign-in was not completed: {result.get('error_description') or result['error']}")
    code = result.get("code")
    client_id = result.get("client_id") or requested_client
    if requested_client and result.get("client_id") and result["client_id"] != requested_client:
        raise RuntimeError("OpenAI returned a different client ID than the selected account")
    if not code or not client_id:
        raise RuntimeError("OpenAI callback did not include the authorization code and issued client ID")

    token_data = _post_form({"grant_type": "authorization_code", "client_id": client_id,
                             "code": code, "code_verifier": verifier,
                             "redirect_uri": REDIRECT_URI, "resource": RESOURCE})
    granted = str(token_data.get("scope", "")).split()
    if "chatgpt.tokens.use.direct" not in granted:
        raise RuntimeError("ChatGPT plan inference was not authorized; Everrun did not save these credentials")
    id_token = token_data.get("id_token")
    if not id_token:
        raise RuntimeError("OpenAI did not return an ID token")
    claims = _verify_id_token(id_token, client_id, nonce)
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("OpenAI sign-in did not return a refresh token; verify offline_access was granted")
    auth["openai"] = {
        "auth_type": "oauth", "client_id": client_id, "ext_agent_host_id": host_id,
        "id_token": id_token, "access_token": token_data["access_token"],
        "refresh_token": refresh_token, "expires_at": time.time() + int(token_data.get("expires_in", 3600)),
        "scopes": granted, "subject": claims["sub"], "email": claims.get("email", ""),
    }
    save_auth(auth)
    print(f"Connected ChatGPT account{': ' + claims['email'] if claims.get('email') else ''}.")


def openai_access_token() -> str:
    auth = load_auth()
    entry = auth.get("openai", {})
    if entry.get("auth_type") != "oauth":
        return str(entry.get("api_key") or os.environ.get("OPENAI_API_KEY") or "")
    if float(entry.get("expires_at", 0)) > time.time() + 90:
        return str(entry["access_token"])

    lock_path = config_home() / "auth.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            import fcntl
            lock_path.chmod(0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except ImportError:
            fcntl = None
        try:
            auth = load_auth()
            entry = auth.get("openai", {})
            if entry.get("auth_type") != "oauth":
                return str(entry.get("api_key") or os.environ.get("OPENAI_API_KEY") or "")
            if float(entry.get("expires_at", 0)) > time.time() + 90:
                return str(entry["access_token"])
            refreshed = _post_form({"grant_type": "refresh_token", "client_id": entry["client_id"],
                                    "refresh_token": entry["refresh_token"], "resource": RESOURCE})
            entry.update({"access_token": refreshed["access_token"],
                          "refresh_token": refreshed["refresh_token"],
                          "expires_at": time.time() + int(refreshed.get("expires_in", 3600)),
                          "scopes": str(refreshed.get("scope", " ".join(entry.get("scopes", [])))).split()})
            auth["openai"] = entry
            save_auth(auth)
            return str(entry["access_token"])
        finally:
            if "fcntl" in locals() and fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
