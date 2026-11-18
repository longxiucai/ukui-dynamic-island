"""IMAP inbox polling and verification-code extraction (stdlib only)."""
import email
import html
import imaplib
import os
import re
import socket
import time
from email.header import decode_header, make_header

from PySide2.QtCore import QThread, Signal


CODE_RE = re.compile(
    r"(?:验证码|校验码|动态码|确认码|verification code|security code|code|otp)"
    r"[^0-9]{0,16}(\d{4,8})", re.IGNORECASE)
DIGITS_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
TAG_RE = re.compile(r"<[^>]+>")
BLOCK_RE = re.compile(r"</?(?:br|p|div|li|tr|h[1-6])[^>]*>", re.IGNORECASE)
BODY_BYTES = 128 * 1024
MAX_BODY_BYTES = 512 * 1024
TEXT_CHARS = 30000


class _TimeoutIMAP4(imaplib.IMAP4):
    """imaplib only grew a timeout argument in Python 3.9."""

    def __init__(self, host, port, timeout=5):
        self._timeout = timeout
        super().__init__(host, port)

    def _create_socket(self, timeout=None):
        host = None if not self.host else self.host
        return socket.create_connection((host, self.port), self._timeout)


class _TimeoutIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, host, port, timeout=5):
        self._timeout = timeout
        super().__init__(host, port)

    def _create_socket(self, timeout=None):
        host = None if not self.host else self.host
        sock = socket.create_connection((host, self.port), self._timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def decode_text(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def extract_code(*parts):
    text = " ".join(part for part in parts if part)
    match = CODE_RE.search(text)
    if match:
        return match.group(1)
    match = DIGITS_RE.search(text)
    return match.group(1) if match else ""


def parse_message(header_bytes, body_bytes=b""):
    msg = email.message_from_bytes(header_bytes)
    subject = decode_text(msg.get("Subject"))
    sender = decode_text(msg.get("From"))
    date = decode_text(msg.get("Date"))
    text = body_preview(header_bytes, body_bytes, TEXT_CHARS)
    return {
        "sender": sender,
        "subject": subject,
        "date": date,
        "code": extract_code(subject, text),
        "preview": text[:800],
        "body": text,
    }


def body_preview(header_bytes, body_bytes, limit=800):
    if not body_bytes:
        return ""
    text = ""
    try:
        msg = email.message_from_bytes(header_bytes + b"\r\n\r\n" + body_bytes)
        parts = msg.walk() if msg.is_multipart() else [msg]
        for part in parts:
            kind = part.get_content_type()
            if kind not in ("text/plain", "text/html"):
                continue
            raw = part.get_payload(decode=True)
            if not raw:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = raw.decode(charset, "ignore")
            except LookupError:
                text = raw.decode("utf-8", "ignore")
            if kind == "text/html":
                text = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", text)
                text = BLOCK_RE.sub("\n", text)
                text = html.unescape(TAG_RE.sub(" ", text))
            if text.strip():
                break
    except Exception:
        text = ""
    if not text.strip():
        text = body_bytes.decode("utf-8", "ignore")
        text = BLOCK_RE.sub("\n", text)
        text = html.unescape(TAG_RE.sub(" ", text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def _parts(data):
    for part in data or ():
        if isinstance(part, tuple):
            for piece in part:
                if isinstance(piece, bytes):
                    yield piece
        elif isinstance(part, bytes):
            yield part


def _header_part(data):
    for part in _parts(data):
        if re.search(rb"^(From|Subject|Date):", part, re.MULTILINE | re.IGNORECASE):
            return part
    return b""


def _flags_part(data):
    blob = b" ".join(_parts(data))
    match = re.search(rb"FLAGS \(([^)]*)\)", blob, re.IGNORECASE)
    return match.group(1) if match else b""


def _size_part(data):
    blob = b" ".join(_parts(data))
    match = re.search(rb"RFC822\.SIZE (\d+)", blob, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _body_part(box, uid):
    try:
        _, text = box.uid(
            "fetch", uid, f"(BODY.PEEK[TEXT]<0.0.{BODY_BYTES}>)")
        chunks = [part for part in _parts(text)
                  if not re.match(rb"^\d+ \(", part)]
        body = max(chunks, key=len) if chunks else b""
    except imaplib.IMAP4.error:
        body = b""
    if body:
        return body
    try:
        _, text = box.uid("fetch", uid, "(BODY.PEEK[TEXT])")
        chunks = [part for part in _parts(text)
                  if not re.match(rb"^\d+ \(", part)]
        return max(chunks, key=len) if chunks else b""
    except imaplib.IMAP4.error:
        return b""


def fetch_inbox(host, port, user, password, use_tls=True, limit=8):
    if not host or not user or not password:
        return {"status": "unconfigured", "error": "未配置邮箱", "items": [],
                "unread": 0}
    try:
        if use_tls:
            box = _TimeoutIMAP4SSL(host, int(port))
        else:
            box = _TimeoutIMAP4(host, int(port))
        box.login(user, password)
        box.select("INBOX", readonly=True)
        _, unseen = box.uid("search", None, "UNSEEN")
        unread = len(unseen[0].split()) if unseen and unseen[0] else 0
        _, data = box.uid("search", None, "ALL")
        ids = data[0].split()[-limit:] if data and data[0] else []
        items = []
        for uid in reversed(ids):
            _, head = box.uid(
                "fetch", uid, "(FLAGS RFC822.SIZE BODY.PEEK[HEADER])")
            flags = _flags_part(head)
            size = _size_part(head)
            header = _header_part(head)
            if not header:
                continue
            body = b"" if size > MAX_BODY_BYTES else _body_part(box, uid)
            item = parse_message(header, body)
            item["uid"] = uid.decode("ascii", "ignore")
            item["seen"] = b"\\Seen" in flags
            item["body_oversize"] = size > MAX_BODY_BYTES
            item["body_truncated"] = (not item["body_oversize"]
                                      and (len(body) >= BODY_BYTES
                                           or len(item["body"]) >= TEXT_CHARS))
            items.append(item)
        try:
            box.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
        return {"status": "ok", "error": "", "items": items, "unread": unread}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}",
                "items": [], "unread": 0}


def password_from(cfg):
    return os.environ.get("UKUI_ISLAND_MAIL_PASSWORD") or cfg.get("mail_password", "")


def _open_box(cfg):
    host = cfg.get("mail_host", "")
    port = cfg.get("mail_port", 993)
    user = cfg.get("mail_user", "")
    password = password_from(cfg)
    if not host or not user or not password:
        raise ValueError("未配置邮箱")
    if cfg.get("mail_tls", True):
        box = _TimeoutIMAP4SSL(host, int(port))
    else:
        box = _TimeoutIMAP4(host, int(port))
    box.login(user, password)
    return box


def _quoted(name):
    return '"' + str(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


def trash_folder(box):
    _, rows = box.list()
    for row in rows or ():
        text = row.decode("utf-8", "ignore") if isinstance(row, bytes) else str(row)
        names = re.findall(r'"([^"]*)"', text)
        if not names:
            continue
        name = names[-1]
        lowered = text.casefold()
        if ("\\trash" in lowered or any(
                word in name.casefold() for word in
                ("trash", "deleted", "已删除", "废纸篓", "垃圾箱", "回收站"))):
            return name
    return None


def mark_seen(cfg, uid=None, seen=True):
    box = None
    try:
        box = _open_box(cfg)
        box.select("INBOX", readonly=False)
        if uid is None:
            _, data = box.uid("search", None, "UNSEEN")
            ids = data[0].split() if data and data[0] else []
            if ids:
                box.uid("store", b",".join(ids), "+FLAGS", "(\\Seen)")
        else:
            box.uid("store", str(uid), "+FLAGS" if seen else "-FLAGS",
                    "(\\Seen)")
        return {"status": "ok",
                "message": "已同步已读状态" if seen else "已同步未读状态"}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if box is not None:
            try:
                box.logout()
            except (imaplib.IMAP4.error, OSError):
                pass


def move_to_trash(cfg, uid):
    box = None
    try:
        box = _open_box(cfg)
        box.select("INBOX", readonly=False)
        folder = trash_folder(box)
        if not folder:
            return {"status": "error", "error": "找不到邮箱回收站，未删除"}
        target = _quoted(folder)
        try:
            box.uid("move", str(uid), target)
        except imaplib.IMAP4.error:
            box.uid("copy", str(uid), target)
            box.uid("store", str(uid), "+FLAGS", "(\\Deleted)")
            try:
                box.uid("expunge", str(uid))
            except imaplib.IMAP4.error:
                return {"status": "ok",
                        "message": "已复制到回收站，原邮件已标记删除"}
        return {"status": "ok", "message": "已移到邮箱回收站"}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if box is not None:
            try:
                box.logout()
            except (imaplib.IMAP4.error, OSError):
                pass


class MailFetcher(QThread):
    updated = Signal(dict)

    def __init__(self, cfg, interval=300, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.interval = interval
        self._refreshing = False

    def refresh(self):
        self._refreshing = True

    def run(self):
        while not self.isInterruptionRequested():
            result = fetch_inbox(
                self.cfg.get("mail_host", ""), self.cfg.get("mail_port", 993),
                self.cfg.get("mail_user", ""), password_from(self.cfg),
                self.cfg.get("mail_tls", True))
            if self.isInterruptionRequested():
                break
            result["at"] = time.strftime("%H:%M")
            self.updated.emit(result)
            self._refreshing = False
            waited = 0.0
            while waited < self.interval and not self.isInterruptionRequested():
                if self._refreshing:
                    self._refreshing = False
                    break
                self.msleep(250)
                waited += 0.25


class MailAction(QThread):
    done = Signal(dict)

    def __init__(self, cfg, action, uid=None, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.action = action
        self.uid = uid

    def run(self):
        if self.action == "trash":
            result = move_to_trash(self.cfg, self.uid)
        elif self.action == "seen":
            result = mark_seen(self.cfg, self.uid, True)
        elif self.action == "unseen":
            result = mark_seen(self.cfg, self.uid, False)
        else:
            result = mark_seen(self.cfg, None, True)
        self.done.emit(result)
