"""Mac-only, send-scope-only Gmail transport. Never log raw OAuth/API errors."""

import base64
import contextlib
import hashlib
import http.client
import json
import os
import re
import ssl
import stat
import sys
import tempfile
import threading
import zlib
from email.message import EmailMessage
from email.utils import formatdate
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import urlsplit

from jobmitra.core.config import PROJECT_ENV_FILE

SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URI = "https://oauth2.googleapis.com/token"
TIMEOUT = 15
_lock = threading.RLock()
_reconnect_tokens = set()


class GmailError(Exception):
    def __init__(self, reason, *, unknown=False, reconnect=False):
        self.reason, self.unknown, self.reconnect = reason, unknown, reconnect
        super().__init__(reason)


def address(value):
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value):
        raise GmailError("A single valid email address is required.")
    if len(value) > 254:
        raise GmailError("Email address is too long.")
    return value.lower()


def validate_configuration(settings):
    if not settings.gmail_enabled:
        return
    if (
        sys.platform != "darwin"
        or not settings.unified_v12_local_direct_editing
        or settings.office_lan_enabled
        or not settings.unified_v12_enabled
        or settings.gmail_mode != "test"
    ):
        raise GmailError("Gmail Phase 1 requires explicit Mac loopback development in test mode.")
    address(settings.gmail_sender)
    if address(settings.gmail_test_recipient) != "pooja.jobmitra@gmail.com":
        raise GmailError("Phase 1 permits only the approved Pooja test recipient.")
    try:
        if any(int(x) <= 0 for x in settings.gmail_test_job_ids.split(",") if x.strip()):
            raise ValueError
    except ValueError:
        raise GmailError("Gmail test JD IDs must be positive canonical IDs.") from None


def _private_file(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
    ):
        raise GmailError("Gmail OAuth files must be private owner-only regular files (600).")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        if os.fstat(stream.fileno()) != info:
            raise GmailError("Gmail OAuth file changed during validation.")
        return json.load(stream)


def _paths(settings):
    credentials, token = settings.gmail_credentials_file, settings.gmail_token_file
    if not credentials or not token or not credentials.is_absolute() or not token.is_absolute():
        raise GmailError("Configure absolute external Gmail credentials and token paths.")
    if credentials == token or credentials.parent != token.parent:
        raise GmailError("Use separate OAuth files in the same private Gmail directory.")
    for path in (credentials, token):
        if path.resolve().is_relative_to(PROJECT_ENV_FILE.parent.resolve()):
            raise GmailError("Gmail OAuth files must be outside the repository.")
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise GmailError("Gmail OAuth paths must not contain symbolic links.")
    parent = token.parent.stat()
    if stat.S_IMODE(parent.st_mode) != 0o700 or parent.st_uid != os.geteuid():
        raise GmailError("The Gmail directory must be owned by this user with mode 700.")
    return credentials, token


@contextlib.contextmanager
def token_lock(settings):
    # flock protects independent Uvicorn workers as well as concurrent threads.
    import fcntl

    with _lock:
        credentials, token = _paths(settings)
        fd = os.open(str(token) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise GmailError("Unsafe Gmail token lock file.")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield credentials, token
        finally:
            os.close(fd)


def _persist(path, credentials):
    fd, name = tempfile.mkstemp(prefix=".gmail-refresh-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(credentials.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def credentials(settings):
    from google.auth.exceptions import RefreshError, TransportError
    from google.oauth2.credentials import Credentials
    from google_auth_httplib2 import Request
    from httplib2 import Http

    try:
        with token_lock(settings) as (client_path, token_path):
            client = _private_file(client_path).get("installed", {})
            token = _private_file(token_path)
            if (
                set(token.get("scopes", [])) != {SCOPE}
                or token.get("token_uri") != TOKEN_URI
                or not client.get("client_id")
                or token.get("client_id") != client.get("client_id")
                or token.get("client_secret") != client.get("client_secret")
                or not token.get("refresh_token")
            ):
                raise GmailError("Reconnect Gmail using only the gmail.send scope.", reconnect=True)
            value = Credentials.from_authorized_user_info(token, scopes=[SCOPE])
            if hashlib.sha256((value.token or "").encode()).hexdigest() in _reconnect_tokens:
                raise GmailError(
                    "Gmail rejected this authorization. Reconnect required.", reconnect=True
                )
            if not value.valid:
                value.refresh(Request(http=Http(timeout=TIMEOUT)))
                if value.granted_scopes and set(value.granted_scopes) != {SCOPE}:
                    raise GmailError(
                        "Reconnect Gmail with send-only authorization.", reconnect=True
                    )
                _persist(token_path, value)
            return value
    except GmailError:
        raise
    except RefreshError:
        raise GmailError(
            "Gmail authorization expired or was revoked. Reconnect required.", reconnect=True
        ) from None
    except TransportError:
        raise GmailError("Gmail authorization service is temporarily unavailable.") from None
    except (OSError, ValueError, KeyError, TypeError):
        raise GmailError(
            "Gmail OAuth files are missing, invalid or unsafe.", reconnect=True
        ) from None


def connection_status(settings):
    if not settings.gmail_enabled:
        return {"status": "Gmail Disabled", "enabled": False}
    try:
        validate_configuration(settings)
        credentials(settings)
        return {
            "status": "Gmail Connected",
            "enabled": True,
            "test_mode": True,
            "actual_recipient": settings.gmail_test_recipient,
            "sender": settings.gmail_sender,
        }
    except GmailError as error:
        return {
            "status": "Reconnect Required" if error.reconnect else "Gmail Unavailable",
            "enabled": False,
            "detail": error.reason,
        }


@lru_cache(maxsize=1)
def approved_logo():
    source = (
        PROJECT_ENV_FILE.parent / "Jobmitra_Unified_Workspace_V12_Companies_Integrated (1).html"
    ).read_text()
    document = json.loads(re.search(r'const EMAIL_STUDIO_DOCUMENT=("(?:\\.|[^"\\])*");', source)[1])
    return re.search(r"const LOGO_DATA_URL = '(data:image/jpeg;base64,[^']+)';", document)[1]


class _ReviewedHTML(HTMLParser):
    tags = frozenset(
        "table tbody thead tr td th div p span a img br b strong small h1 h2 h3 ul ol li".split()
    )

    def handle_starttag(self, tag, attrs):
        if tag not in self.tags:
            raise GmailError("Email contains unsupported HTML content.")
        for name, value in attrs:
            value = value or ""
            if name.startswith("on") or name not in {
                "style",
                "class",
                "id",
                "role",
                "aria-label",
                "width",
                "height",
                "align",
                "valign",
                "border",
                "cellpadding",
                "cellspacing",
                "bgcolor",
                "colspan",
                "rowspan",
                "alt",
                "title",
                "href",
                "src",
                "target",
                "rel",
            }:
                raise GmailError("Email contains unsupported HTML attributes.")
            if name == "src" and (tag != "img" or value != approved_logo()):
                raise GmailError("Only the approved inline Jobmitra logo is permitted.")
            if name == "href":
                url = urlsplit(value)
                if (
                    url.scheme not in {"https", "http", "mailto", "tel"}
                    or url.username
                    or url.password
                    or "\r" in value
                    or "\n" in value
                ):
                    raise GmailError("Email contains an unsafe link.")
            if name == "style" and re.search(r"url\s*\(|expression|@|javascript|\\", value, re.I):
                raise GmailError("Email contains unsafe inline styling.")

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag not in self.tags:
            raise GmailError("Email contains unsupported HTML content.")

    def handle_decl(self, decl):
        raise GmailError("Email declarations are unsupported.")


def message(settings, data, reference):
    _ReviewedHTML(convert_charrefs=True).feed(data.html)
    if not data.plain.strip() or not data.html.strip():
        raise GmailError("Review both the email preview and subject before sending.")
    result = EmailMessage()
    result["From"] = address(settings.gmail_sender)
    result["To"] = address(settings.gmail_test_recipient)
    result["Subject"] = data.subject
    result["Date"] = formatdate(localtime=False)
    result["Message-ID"] = f"<jobmitra-{reference}@{settings.gmail_sender.split('@')[1]}>"
    result.set_content(data.plain)
    logo = approved_logo()
    rendered = data.html.replace(logo, "cid:jobmitra-logo")
    result.add_alternative(rendered, subtype="html")
    if logo in data.html:
        result.get_payload()[1].add_related(
            base64.b64decode(logo.split(",", 1)[1]),
            maintype="image",
            subtype="jpeg",
            cid="<jobmitra-logo>",
            disposition="inline",
        )
    # No caller-controlled MIME headers, CC/BCC, file attachments or recipient lists.
    return base64.urlsafe_b64encode(result.as_bytes()).decode("ascii")


class _SingleRequestHTTP:
    """No transport-level reconnect/retry: a lost POST response is ambiguous.

    httplib2 itself retries some socket failures even when execute(num_retries=0).
    A one-shot stdlib HTTPS transport avoids that hidden resend path.
    """

    def __init__(self, token):
        self.token = token

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        from httplib2 import Response

        url = urlsplit(uri)
        if (
            (url.scheme, url.hostname, method, url.path)
            != ("https", "gmail.googleapis.com", "POST", "/gmail/v1/users/me/messages/send")
            or url.username
            or url.password
            or url.port not in {None, 443}
        ):
            raise GmailError("Unexpected Gmail transport destination.")
        connection = http.client.HTTPSConnection(
            url.hostname, timeout=TIMEOUT, context=ssl.create_default_context()
        )
        try:
            headers = {k.lower(): v for k, v in (headers or {}).items()}
            headers.update({"authorization": "Bearer " + self.token, "accept-encoding": "identity"})
            connection.request(
                method,
                url.path + ("?" + url.query if url.query else ""),
                body=body,
                headers=headers,
            )
            response = connection.getresponse()
            content = response.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise GmailError("Gmail response exceeded the safe limit.", unknown=True)
            metadata = {k.lower(): v for k, v in response.getheaders()}
            encoding = metadata.get("content-encoding", "identity").lower()
            if encoding in {"gzip", "deflate"}:
                decoder = zlib.decompressobj(
                    16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS
                )
                content = decoder.decompress(content, 1024 * 1024 + 1)
                if len(content) > 1024 * 1024 or not decoder.eof:
                    raise GmailError(
                        "Gmail compressed response was incomplete or oversized.", unknown=True
                    )
                metadata.pop("content-encoding", None)
                metadata["content-length"] = str(len(content))
            elif encoding != "identity":
                raise GmailError("Unsupported Gmail response encoding.", unknown=True)
            return Response({**metadata, "status": str(response.status)}), content
        finally:
            connection.close()


def send(settings, raw):
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    value = credentials(settings)  # OAuth/refresh errors are known pre-send failures.
    try:
        service = build(
            "gmail",
            "v1",
            http=_SingleRequestHTTP(value.token),
            cache_discovery=False,
            static_discovery=True,
        )
        result = (
            service.users().messages().send(userId="me", body={"raw": raw}).execute(num_retries=0)
        )
        if not result.get("id"):
            raise GmailError("Gmail response lacked an acceptance reference.", unknown=True)
        return {"message_id": result["id"], "thread_id": result.get("threadId")}
    except HttpError as error:
        status = error.resp.status
        if status == 401:
            _reconnect_tokens.add(hashlib.sha256(value.token.encode()).hexdigest())
        raise GmailError(
            f"Gmail returned HTTP {status}." + (" Reconnect required." if status == 401 else ""),
            unknown=status >= 500 or status == 408,
            reconnect=status == 401,
        ) from None
    except GmailError:
        raise
    except Exception:
        # Never expose request bodies, Authorization headers or Google's raw errors.
        raise GmailError(
            "Gmail send response was interrupted; do not automatically retry.", unknown=True
        ) from None


def fingerprint(data):
    body = data.model_dump(mode="json", exclude={"reference", "resend_of", "confirm_resend"})
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
