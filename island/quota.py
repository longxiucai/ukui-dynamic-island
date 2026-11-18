"""AI quotas from local logs, optional official online APIs, and one JSON URL.

Codex writes the server's own ``rate_limits`` snapshot into its session
records, so the official windows can be read without sending the sign-in
anywhere. Claude keeps token usage in its project records and, on desktop,
periodic five-hour / weekly samples in ``plan-usage-history.json``. When no
official window is available, the configured daily budget is used as a
fallback. Asking the providers' own endpoints with the local sign-in is
opt-in per provider (``codex_online`` / ``claude_online``) and never logged.
Copilot reuses the token its editor or CLI already stored. The remote JSON
source stays opt-in as well.
"""
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from PySide2.QtCore import QThread, Signal

from island.config import config_dir


PLANS = {
    "free": "Free",
    "plus": "Plus",
    "pro": "Pro",
    "prolite": "Pro Lite",
    "pro_lite": "Pro Lite",
    "team": "Team",
    "business": "Business",
    "enterprise": "Enterprise",
}
CLAUDE_PLANS = {
    "free": "Free",
    "pro": "Pro",
    "max": "Max",
    "team": "Team",
}
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TRAE_USAGE_URL = "https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage"
TRAE_ORIGIN = "https://api.trae.cn"
TRAE_LOGIN_URL = "https://www.trae.cn/authorization"
TRAE_CLIENT_ID = "ono9krqynydwx5"
TRAE_PLUGIN_VERSION = "2.3.24254"
TRAE_IDE_VERSION = "3.3.65"
WORKBUDDY_ORIGIN = "https://www.workbuddy.cn"
COPILOT_USER_URL = "https://api.github.com/copilot_internal/user"
COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
COPILOT_DEVICE_URL = "https://github.com/login/device/code"
COPILOT_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_HEADERS = {
    "Editor-Version": "vscode/1.140.0",
    "Editor-Plugin-Version": "copilot-chat/0.68.0",
    "Copilot-Integration-Id": "vscode-chat",
    "User-Agent": "GitHubCopilotChat/0.68.0",
}
TRAE_PLANS = {
    0: "Free", 1: "Pro", 2: "加量包", 4: "Pro+", 5: "Pro+ 加量",
    6: "Ultra", 7: "PayGo", 8: "Lite",
}


def _modified_today(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).date() == date.today()
    except OSError:
        return False


def _fresh(path, size=32_000_000):
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > size:
            return False
        return _modified_today(path)
    except OSError:
        return False


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _timestamp(value):
    number = _number(value)
    if number is not None:
        return number / 1000.0 if number > 10_000_000_000 else number
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.isdigit():
        number = float(text)
        return number / 1000.0 if number > 10_000_000_000 else number
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _window_label(minutes):
    if not isinstance(minutes, (int, float)) or minutes <= 0:
        return "额度"
    minutes = int(minutes)
    if minutes == 300:
        return "5 小时"
    if minutes == 10080:
        return "本周"
    if minutes == 1440:
        return "今日"
    if minutes == 43200:
        return "30 天"
    if minutes % 1440 == 0:
        return f"{minutes // 1440} 天"
    if minutes % 60 == 0:
        return f"{minutes // 60} 小时"
    return f"{minutes} 分钟"


def _reset_text(reset, now=None):
    if not reset:
        return ""
    try:
        at = datetime.fromtimestamp(float(reset))
    except (OSError, OverflowError, TypeError, ValueError):
        return ""
    now = datetime.fromtimestamp(now or time.time())
    if at <= now:
        return "等待刷新"
    if at.date() == now.date():
        return at.strftime("今天 %H:%M 重置")
    if at.year == now.year:
        return f"{at.month}月{at.day}日 {at:%H:%M} 重置"
    return at.strftime("%Y/%m/%d %H:%M 重置")


def _metric(label, used, reset=None, kind="percent", text=None, window=None,
            note="", now=None):
    used = max(0.0, min(1.0, float(used)))
    remaining = 1.0 - used
    return {
        "id": label,
        "label": label,
        "kind": kind,
        "used": used,
        "remaining": remaining,
        "text": text or f"{remaining * 100:.0f}%",
        "reset": reset,
        "reset_text": _reset_text(reset, now) if reset else note,
        "window": window,
    }


def _read_tail(path, limit=1_500_000):
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - limit))
        return handle.read().decode("utf-8", "ignore")


def _codex_total(path, tail=2_000_000):
    """Only the last token_count record matters; avoid reading whole rollouts."""
    data = _read_tail(path, tail)
    last = 0
    for line in data.splitlines():
        if '"total_token_usage"' not in line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                usage = node.get("total_token_usage")
                if isinstance(usage, dict) and "total_tokens" in usage:
                    last = int(usage["total_tokens"])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return last


def codex_usage(home=None):
    root = Path(home or Path.home()) / ".codex" / "sessions"
    total = 0
    sessions = 0

    def mtime(item):
        try:
            return item.stat().st_mtime
        except OSError:
            return 0.0

    for path in sorted(root.glob("*/*/*/*.jsonl"),
                       key=mtime,
                       reverse=True)[:20]:
        if not _modified_today(path):
            continue
        try:
            last = _codex_total(path)
        except (OSError, ValueError, TypeError):
            continue
        if last:
            total += last
            sessions += 1
    return {"total": total, "sessions": sessions}


def _codex_window(limits, key):
    window = limits.get(key)
    if not isinstance(window, dict):
        window = limits.get(key + "_window")
    return window if isinstance(window, dict) else None


def _has_live_window(limits, now):
    for key in ("primary", "secondary"):
        window = _codex_window(limits, key)
        if not window or _number(window.get("used_percent")) is None:
            continue
        reset = _timestamp(window.get("resets_at") or window.get("reset_at"))
        if reset is None or reset > now - 60:
            return True
    return False


def latest_codex_limits(home=None, now=None):
    """The newest live rate-limit snapshot written by Codex itself."""
    now = now or time.time()
    base = Path(home or Path.home()) / ".codex"
    files = []
    for name in ("sessions", "archived_sessions"):
        root = base / name
        if not root.is_dir():
            continue
        try:
            for item in root.rglob("*.jsonl"):
                try:
                    modified = item.stat().st_mtime
                except OSError:
                    continue
                if modified >= now - 30 * 86400:
                    files.append((modified, item))
        except OSError:
            continue
    files.sort(reverse=True)
    for modified, path in files[:24]:
        try:
            data = _read_tail(path)
        except OSError:
            continue
        for line in reversed(data.splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            node = payload.get("payload") if isinstance(payload, dict) else None
            if not isinstance(node, dict):
                continue
            limits = node.get("rate_limits")
            if not isinstance(limits, dict):
                info = node.get("info")
                limits = info.get("rate_limits") if isinstance(info, dict) else None
            if not isinstance(limits, dict) or not _has_live_window(limits, now):
                continue
            return limits, _timestamp(payload.get("timestamp")) or modified
    return {}, 0.0


def parse_codex_limits(limits, now=None):
    now = now or time.time()
    metrics = []
    for key in ("primary", "secondary"):
        window = _codex_window(limits, key)
        if not window:
            continue
        used = _number(window.get("used_percent"))
        if used is None:
            continue
        minutes = _number(window.get("window_minutes"))
        if minutes is None:
            seconds = _number(window.get("limit_window_seconds"))
            minutes = seconds / 60.0 if seconds is not None else None
        reset = _timestamp(window.get("resets_at") or window.get("reset_at"))
        if reset is None:
            after = _number(window.get("reset_after_seconds"))
            if after is not None and 0 <= after < 31_536_000:
                reset = now + after
        if reset is not None and reset <= now - 60:
            continue
        label = _window_label(minutes)
        metrics.append(_metric(label, used / 100.0, reset,
                               window=int(minutes) if minutes else None,
                               now=now))
    metrics.sort(key=lambda item: item["window"] or 1 << 30)
    return metrics


def parse_codex_online(raw):
    """The account endpoint's ``rate_limit`` windows use ``_window`` keys."""
    if not isinstance(raw, dict):
        return {}, ""
    limit = raw.get("rate_limit")
    if not isinstance(limit, dict):
        limit = raw
    windows = {key: limit[key]
               for key in ("primary_window", "secondary_window")
               if isinstance(limit.get(key), dict)}
    plan = PLANS.get(str(raw.get("plan_type") or "").lower(), "")
    return windows, plan


def claude_usage(home=None, days=1):
    root = Path(home or Path.home()) / ".claude" / "projects"
    total = 0
    sessions = 0
    seen = set()
    start = date.today() - timedelta(days=max(0, int(days) - 1))
    for path in root.glob("*/*.jsonl"):
        if not _fresh(path):
            continue
        counted = False
        try:
            with open(path, encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if '"usage"' not in line:
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("type") in ("user", "system"):
                        continue
                    message = payload.get("message")
                    usage = (message.get("usage")
                             if isinstance(message, dict) else None)
                    if not isinstance(usage, dict):
                        usage = payload.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    stamp = _timestamp(payload.get("timestamp"))
                    if stamp is None:
                        continue
                    if datetime.fromtimestamp(stamp).date() < start:
                        continue
                    key = (message.get("id") if isinstance(message, dict)
                           else None) or payload.get("uuid")
                    if key:
                        if key in seen:
                            continue
                        seen.add(key)
                    total += sum(int(_number(usage.get(name)) or 0) for name in
                                 ("input_tokens", "output_tokens",
                                  "cache_creation_input_tokens",
                                  "cache_read_input_tokens"))
                    counted = True
        except (OSError, ValueError, TypeError):
            continue
        if counted:
            sessions += 1
    return {"total": total, "sessions": sessions}


def claude_history(home=None, now=None):
    """Five-hour and weekly samples written by the Claude desktop app."""
    base = Path(home or Path.home())
    paths = [
        base / ".config" / "Claude" / "plan-usage-history.json",
        base / ".config" / "claude" / "plan-usage-history.json",
        base / ".local" / "share" / "Claude" / "plan-usage-history.json",
        base / ".claude" / "plan-usage-history.json",
    ]
    best = None
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        samples = raw.get("samples") if isinstance(raw, dict) else None
        for sample in samples or []:
            if not isinstance(sample, dict):
                continue
            stamp = _timestamp(sample.get("t"))
            usage = sample.get("u")
            if stamp is None or not isinstance(usage, dict):
                continue
            five = _number(usage.get("fh"))
            week = _number(usage.get("sd"))
            if five is None and week is None:
                continue
            if best is None or stamp > best[0]:
                best = (stamp, five, week)
    if best is None:
        return []
    _, five, week = best
    metrics = []
    if five is not None:
        metrics.append(_metric("5 小时", five / 100.0,
                               note="重置时间未知", now=now))
    if week is not None:
        metrics.append(_metric("本周", week / 100.0,
                               note="重置时间未知", now=now))
    return metrics


def _trace_head(path):
    """WorkBuddy's trace header sits before the (large) span list."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            head = handle.read(262_144)
    except OSError:
        return None
    at = head.find('"trace"')
    if at < 0:
        return None
    at = head.find("{", at)
    try:
        return json.JSONDecoder().raw_decode(head, at)[0]
    except ValueError:
        return None


def workbuddy_usage(home=None, days=1):
    """Tokens WorkBuddy's desktop/CLI recorded in its local traces."""
    root = Path(home or Path.home()) / ".workbuddy" / "traces"
    start = datetime.now() - timedelta(days=max(0, int(days) - 1))
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0
    sessions = set()
    try:
        files = list(root.glob("*/*.json"))
    except OSError:
        files = []
    for path in files:
        try:
            if path.stat().st_mtime < start.timestamp():
                continue
        except OSError:
            continue
        trace = _trace_head(path)
        if not isinstance(trace, dict):
            continue
        stamp = _timestamp(trace.get("startedAt"))
        if stamp is None or datetime.fromtimestamp(stamp) < start:
            continue
        total += int(_number(trace.get("totalTokens")) or 0)
        session = trace.get("sessionId")
        if session:
            sessions.add(str(session))
    return {"total": total, "sessions": len(sessions)}


def parse_claude_online(raw, now=None):
    if not isinstance(raw, dict):
        return []
    now = now or time.time()
    metrics = []

    def add(label, used, reset, window):
        if used is None or any(item["label"] == label for item in metrics):
            return
        metrics.append(_metric(label, float(used) / 100.0, reset,
                               window=window, now=now))

    for key, label, window in (("five_hour", "5 小时", 300),
                               ("seven_day", "本周", 10080)):
        node = raw.get(key)
        if isinstance(node, dict):
            add(label, _number(node.get("utilization")),
                _timestamp(node.get("resets_at")), window)
    limits = raw.get("limits")
    for item in limits if isinstance(limits, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
        name = str(model.get("display_name") or "")
        if kind == "session":
            label, window = "5 小时", 300
        elif kind == "weekly_all":
            label, window = "本周", 10080
        elif name:
            weekly = (item.get("group") == "weekly"
                      or kind == "weekly_scoped")
            label = name + (" 本周" if weekly else "")
            window = 10080 if weekly else None
        else:
            continue
        add(label, _number(item.get("percent")),
            _timestamp(item.get("resets_at")), window)
    metrics.sort(key=lambda item: item["window"] or 1 << 30)
    return metrics


def parse_url_payload(raw):
    if not isinstance(raw, dict):
        raise ValueError("响应不是 JSON 对象")
    nodes = [raw, raw.get("data"), raw.get("usage")]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for key in ("percent", "used_percent", "usage_percent", "percentage"):
            if isinstance(node.get(key), (int, float)):
                value = float(node[key])
                used = value / 100.0 if value > 1 else value
                return {"percent": used, "used": used,
                        "text": f"{value:.0f}%" if value > 1 else f"{value * 100:.0f}%"}
        used, total = node.get("used"), node.get("total")
        if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total:
            ratio = max(0.0, min(1.0, float(used) / float(total)))
            return {"percent": ratio, "used": ratio,
                    "text": f"{used:g}/{total:g}"}
        for key in ("balance", "remaining"):
            if isinstance(node.get(key), (int, float)):
                return {"percent": None, "used": None,
                        "text": f"{node[key]:g}"}
    raise ValueError("未找到 percent/used/total/balance 字段")


def http_quota(url, timeout=6, token=""):
    if not url:
        return {"status": "unconfigured", "error": "未配置地址"}
    try:
        headers = {"User-Agent": "ukui-dynamic-island/0.6"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            parsed = parse_url_payload(json.loads(
                response.read(1_000_000).decode("utf-8", "replace")))
        return {"status": "ok", "error": "", **parsed}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}",
                "percent": None, "text": "不可用"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would forward the Authorization header on a cross-host redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(newurl, code, "redirect not followed",
                                     headers, fp)


def _http_json(url, token=None, extra=None, timeout=12, data=None,
               method=None):
    headers = {"Accept": "application/json",
               "User-Agent": "ukui-dynamic-island/0.6"}
    if token:
        headers["Authorization"] = "Bearer " + token
    headers.update(extra or {})
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(
        url, data=body, headers=headers,
        method=method or ("POST" if body is not None else "GET"))
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read(1_000_000).decode("utf-8", "replace"))


def _online_error(exc):
    code = getattr(exc, "code", None)
    if code in (401, 403):
        return "登录已失效，请在原应用重新登录"
    if code == 429:
        return "请求过于频繁，稍后重试"
    if code:
        return f"在线额度读取失败（HTTP {code}）"
    return f"在线额度读取失败（{type(exc).__name__}）"


def _jwt_expiry(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        value = json.loads(base64.urlsafe_b64decode(payload))
        return float(value["exp"])
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def parse_trae_online(raw, now=None):
    if not isinstance(raw, dict):
        raise ValueError("Trae CN 返回了无效数据")
    if raw.get("code") not in (None, 0):
        raise ValueError(str(raw.get("message") or "Trae CN 额度接口报错"))
    now = now or time.time()
    total = used = 0.0
    unlimited = False
    expiry = None
    plan_type = 0
    basic_limit = basic_used = None
    rows = raw.get("user_entitlement_pack_list")
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            continue
        base = item.get("entitlement_base_info")
        base = base if isinstance(base, dict) else {}
        quota = base.get("quota")
        quota = quota if isinstance(quota, dict) else {}
        usage = item.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        product = base.get("product_type")
        if isinstance(product, int) and product > plan_type:
            plan_type = product
        limit = _number(quota.get("credits_limit"))
        amount = _number(usage.get("credits_amount")) or 0.0
        if limit == -1:
            unlimited = True
        elif limit and limit > 0:
            total += limit
            used += amount
        if product == 0:
            value = _number(quota.get("basic_usage_limit"))
            if value is not None and value >= 0:
                basic_limit = value
                basic_used = _number(usage.get("basic_usage_amount")) or 0.0
        stamp = _timestamp(item.get("expire_time") or base.get("end_time"))
        if stamp and (expiry is None or stamp > expiry):
            expiry = stamp
    plan = TRAE_PLANS.get(plan_type, "")
    if total > 0:
        remain = max(0.0, total - used)
        metrics = [_metric(
            "套餐积分", min(1.0, used / total), expiry,
            text=f"{remain:g}/{total:g}",
            note=f"{len(rows)} 个权益包", now=now)]
    elif unlimited:
        metrics = [_metric("套餐积分", 0.0, kind="balance",
                           text="不限", note="不限量套餐", now=now)]
    elif basic_limit:
        used = basic_used or 0.0
        metrics = [_metric(
            "基础额度", min(1.0, used / basic_limit), expiry,
            text=f"{max(0.0, basic_limit - used):g}/{basic_limit:g}",
            note="Free 基础额度", now=now)]
    else:
        metrics = []
    return metrics, plan


def _save_private_json(path, data):
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".island-",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _trae_session_path():
    return config_dir() / "trae.json"


def trae_session():
    try:
        raw = json.loads(_trae_session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("origin") != TRAE_ORIGIN:
        return None
    if not raw.get("refresh_token") and not raw.get("access_token"):
        return None
    return raw


def _trae_device_ids(home=None):
    """The IDE's telemetry ids; a random pair when Trae never wrote them."""
    device = machine = ""
    path = (Path(home or Path.home()) / ".config" / "Trae CN" / "User"
            / "globalStorage" / "storage.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        device = str(raw.get("telemetry.devDeviceId") or "")
        machine = str(raw.get("telemetry.machineId") or "")
    return device or str(uuid.uuid4()), machine or uuid.uuid4().hex


def parse_trae_callback(query):
    """The JWT and refresh token Trae's authorization page returns."""
    def one(key):
        value = query.get(key)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        return value or ""

    try:
        jwt = json.loads(one("userJwt") or "{}")
        info = json.loads(one("userInfo") or "{}")
    except ValueError as exc:
        raise ValueError("Trae CN 登录回调无效") from exc
    jwt = jwt if isinstance(jwt, dict) else {}
    info = info if isinstance(info, dict) else {}
    token = str(jwt.get("Token") or jwt.get("token") or "")
    refresh = str(jwt.get("RefreshToken") or jwt.get("refreshToken")
                  or one("refreshToken") or "")
    if not token or not refresh:
        raise ValueError("Trae CN 没有返回登录令牌，请重试")
    return {
        "origin": TRAE_ORIGIN,
        "access_token": token,
        "refresh_token": refresh,
        "expires": _timestamp(jwt.get("TokenExpireAt")
                              or jwt.get("tokenExpireAt")) or 0.0,
        "uid": str(info.get("UserID") or info.get("userId") or ""),
        "name": str(info.get("ScreenName") or info.get("screenName") or ""),
        "client_id": str(jwt.get("ClientID") or jwt.get("clientId")
                         or TRAE_CLIENT_ID),
    }


def trae_login_url(device_id, machine_id, callback):
    query = urlencode({
        "login_version": "1",
        "auth_from": "solo",
        "login_channel": "native_ide",
        "plugin_version": TRAE_PLUGIN_VERSION,
        "auth_type": "local",
        "client_id": TRAE_CLIENT_ID,
        "redirect": "0",
        "login_trace_id": str(uuid.uuid4()),
        "auth_callback_url": callback,
        "machine_id": machine_id,
        "device_id": device_id,
        "x_device_id": device_id,
        "x_machine_id": machine_id,
        "x_device_brand": "ASUS TUF Gaming A15 FA507RM_FA507RM",
        "x_device_type": "windows",
        "x_os_version": "Windows 10 Pro",
        "x_env": "",
        "x_app_version": TRAE_IDE_VERSION,
        "x_app_type": "stable",
        "hide_saas_login": "false",
    })
    return TRAE_LOGIN_URL + "?" + query


def _trae_refresh(session):
    raw = _http_json(
        TRAE_ORIGIN + "/cloudide/api/v3/trae/oauth/ExchangeToken", None,
        {"Content-Type": "application/json"},
        data={"ClientID": session.get("client_id") or TRAE_CLIENT_ID,
              "RefreshToken": session["refresh_token"],
              "ClientSecret": "-", "UserID": ""})
    result = raw.get("Result") if isinstance(raw, dict) else None
    result = result if isinstance(result, dict) else {}
    token = str(result.get("Token") or result.get("token") or "")
    if not token:
        raise ValueError("Trae CN 刷新登录失败，请重新连接")
    info = result.get("UserInfo")
    info = info if isinstance(info, dict) else {}
    session = dict(session)
    session.update({
        "access_token": token,
        "refresh_token": str(result.get("RefreshToken")
                             or result.get("refreshToken")
                             or session["refresh_token"]),
        "expires": _timestamp(result.get("TokenExpireAt")
                              or result.get("tokenExpireAt")) or 0.0,
        "uid": str(info.get("UserID") or info.get("userId")
                   or session.get("uid", "")),
        "name": str(info.get("ScreenName") or info.get("screenName")
                    or session.get("name", "")),
    })
    _save_private_json(_trae_session_path(), session)
    return session


def _trae_fetch(session, now):
    token = str(session.get("access_token") or "")
    headers = {"Authorization": "Cloud-IDE-JWT " + token,
               "Content-Type": "application/json"}
    try:
        raw = _http_json(TRAE_USAGE_URL, token, headers,
                         data={"require_usage": True, "req_source": 0})
    except urllib.error.HTTPError as exc:
        if exc.code not in (401, 403) or not session.get("refresh_token"):
            raise
        session = _trae_refresh(session)
        token = str(session.get("access_token") or "")
        headers["Authorization"] = "Cloud-IDE-JWT " + token
        raw = _http_json(TRAE_USAGE_URL, token, headers,
                         data={"require_usage": True, "req_source": 0})
    return parse_trae_online(raw, now)


def trae_online(home=None, now=None):
    """Opt-in: asks Trae CN's quota endpoint with its own sign-in."""
    now = now or time.time()
    session = trae_session()
    if session:
        if not session.get("access_token") or (
                (session.get("expires") or 0) <= now):
            try:
                session = _trae_refresh(session)
            except Exception as exc:
                if isinstance(exc, ValueError):
                    return [], "", str(exc)
                return [], "", _online_error(exc)
        try:
            metrics, plan = _trae_fetch(session, now)
        except Exception as exc:
            if isinstance(exc, ValueError):
                return [], "", str(exc)
            return [], "", _online_error(exc)
        return metrics, plan, "" if metrics else "Trae CN 未返回积分额度"
    path = Path(home or Path.home()) / ".trae-cn" / "trae-jwt-token"
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return [], "", "未连接 Trae CN，请在设置里点“连接 Trae CN”"
    if token.count(".") != 2:
        return [], "", "Trae CN 登录信息无效"
    expiry = _jwt_expiry(token)
    if expiry and expiry <= now:
        return [], "", "Trae CN 登录已过期，请点“连接 Trae CN”重新授权"
    try:
        metrics, plan = _trae_fetch({"access_token": token}, now)
    except Exception as exc:
        if isinstance(exc, ValueError):
            return [], "", str(exc)
        return [], "", _online_error(exc)
    return metrics, plan, "" if metrics else "Trae CN 未返回积分额度"


def _workbuddy_session_path():
    return config_dir() / "workbuddy.json"


def workbuddy_session():
    try:
        raw = json.loads(_workbuddy_session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("origin") != WORKBUDDY_ORIGIN:
        return None
    if not isinstance(raw.get("access_token"), str) or not raw["access_token"]:
        return None
    return raw


def _save_workbuddy_session(session):
    _save_private_json(_workbuddy_session_path(), session)


def _workbuddy_headers(token=None, uid="", domain=""):
    headers = {"X-Client-Platform": "web",
               "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if uid:
        headers["X-User-Id"] = uid
    if domain:
        headers["X-Domain"] = domain
    return headers


def parse_workbuddy_online(raw, now=None):
    if not isinstance(raw, dict):
        raise ValueError("WorkBuddy 返回了无效数据")
    if raw.get("code") not in (None, 0):
        raise ValueError(str(raw.get("msg") or "WorkBuddy 积分接口报错"))
    now = now or time.time()
    data = raw.get("data")
    data = data if isinstance(data, dict) else {}
    plan = str(data.get("SubscriptionPackageName")
               or data.get("SubscriptionPackageCode") or "个人版")
    groups = data.get("CreditGroups")
    groups = groups if isinstance(groups, list) else []
    plan_total = plan_used = extra_total = extra_used = 0.0
    for item in groups:
        if not isinstance(item, dict):
            continue
        total = _number(item.get("CycleTotalCapacity"))
        if total is None:
            continue
        used = _number(item.get("CycleUsedCapacity")) or 0.0
        if item.get("Kind") == "plan_base":
            plan_total += total
            plan_used += used
        else:
            extra_total += total
            extra_used += used
    if plan_total > 0 or extra_total > 0:
        metrics = []
        for label, total, used in (("套餐积分", plan_total, plan_used),
                                   ("加购积分", extra_total, extra_used)):
            if total <= 0:
                continue
            remain = max(0.0, total - used)
            metrics.append(_metric(
                label, min(1.0, used / total), window=43200,
                text=f"{remain:g}/{total:g}", note="官方积分", now=now))
        return metrics, plan
    packages = data.get("Packages")
    packages = packages if isinstance(packages, list) else []
    total = remain = used = 0.0
    for item in packages:
        if not isinstance(item, dict):
            continue
        total += _number(item.get("CycleTotalCapacity")) or 0.0
        remain += _number(item.get("CycleRemainCapacity")) or 0.0
        used += _number(item.get("CycleUsedCapacity")) or 0.0
    if total > 0:
        if used <= 0:
            used = max(0.0, total - remain)
        metrics = [_metric(
            "套餐积分", min(1.0, used / total), text=f"{remain:g}/{total:g}",
            note=f"{len(packages)} 个资源包", now=now)]
    elif packages:
        metrics = [_metric("剩余积分", 0.0, kind="balance",
                           text=f"{remain:g}", note="官方积分", now=now)]
    else:
        metrics = []
    return metrics, plan


def _workbuddy_summary(session):
    return _http_json(
        session["origin"] + "/billing/meter/get-user-resource-summary",
        session["access_token"],
        _workbuddy_headers(session["access_token"],
                           session.get("uid", ""),
                           session.get("domain", "")),
        data={})


def _workbuddy_refresh(session):
    if not session.get("refresh_token"):
        raise ValueError("WorkBuddy 没有刷新令牌")
    raw = _http_json(
        session["origin"] + "/v2/plugin/auth/token/refresh", None,
        {"X-Refresh-Token": session["refresh_token"],
         "X-Auth-Refresh-Source": "plugin",
         "X-Domain": session.get("domain", ""),
         "Content-Type": "application/json"}, data={})
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict) or not data.get("accessToken"):
        raise ValueError("WorkBuddy 刷新登录失败")
    session = dict(session)
    session["access_token"] = str(data["accessToken"])
    if data.get("refreshToken"):
        session["refresh_token"] = str(data["refreshToken"])
    _save_workbuddy_session(session)
    return session


def workbuddy_online(now=None):
    """Opt-in: official WorkBuddy credits from the connected account."""
    now = now or time.time()
    session = workbuddy_session()
    if not session:
        return [], "", "未连接 WorkBuddy 账号"
    for attempt in range(2):
        try:
            raw = _workbuddy_summary(session)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) and attempt == 0:
                try:
                    session = _workbuddy_refresh(session)
                    continue
                except Exception:
                    return [], "", "WorkBuddy 登录已过期，请重新连接"
            return [], "", _online_error(exc)
        except Exception as exc:
            return [], "", _online_error(exc)
        try:
            metrics, plan = parse_workbuddy_online(raw, now)
        except ValueError as exc:
            return [], "", str(exc)
        return metrics, plan, "" if metrics else "WorkBuddy 未返回积分"
    return [], "", "WorkBuddy 登录已过期，请重新连接"


def _workbuddy_login_request(raw):
    if not isinstance(raw, dict) or raw.get("code") != 0:
        raise ValueError("WorkBuddy 暂时无法创建登录请求")
    data = raw.get("data")
    data = data if isinstance(data, dict) else {}
    state = data.get("state")
    link = data.get("authUrl")
    if not isinstance(state, str) or not state or not isinstance(link, str):
        raise ValueError("WorkBuddy 官网未返回登录地址")
    parsed = urlparse(link)
    if (parsed.scheme != "https" or parsed.netloc != "www.workbuddy.cn"
            or parsed.path != "/login"
            or parse_qs(parsed.query).get("state") != [state]):
        raise ValueError("WorkBuddy 登录地址与请求不匹配")
    return state, link


def workbuddy_login_start():
    raw = _http_json(
        WORKBUDDY_ORIGIN + "/v2/plugin/auth/state?platform=ukui-dynamic-island",
        None, {"X-No-Authorization": "true", "X-No-User-Id": "true",
               "Content-Type": "application/json"}, data={})
    return _workbuddy_login_request(raw)


def workbuddy_login_poll(state):
    """Returns None while the browser login is pending."""
    url = (WORKBUDDY_ORIGIN + "/v2/plugin/auth/token?"
           + urlencode({"state": state}))
    try:
        raw = _http_json(url, None, {"X-No-Authorization": "true",
                                     "X-No-User-Id": "true"})
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise
        try:
            raw = json.loads(exc.read(500_000).decode("utf-8", "replace"))
        except ValueError:
            raise ValueError("WorkBuddy 登录响应无效") from exc
    if not isinstance(raw, dict):
        raise ValueError("WorkBuddy 登录响应无效")
    if raw.get("code") == 11217:
        return None
    if raw.get("code") != 0:
        raise ValueError("WorkBuddy 登录请求已失效，请重新连接")
    data = raw.get("data")
    data = data if isinstance(data, dict) else {}
    token = data.get("accessToken")
    if not isinstance(token, str) or not token:
        raise ValueError("WorkBuddy 登录授权为空，请重新连接")
    domain = str(data.get("domain") or "www.workbuddy.cn")
    try:
        accounts = _http_json(
            WORKBUDDY_ORIGIN + "/v2/plugin/accounts", token,
            _workbuddy_headers(token, "", domain))
    except Exception as exc:
        raise ValueError("WorkBuddy 读取账号列表失败") from exc
    rows = accounts.get("data", {}).get("accounts") if isinstance(
        accounts, dict) else None
    personal = []
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("enterpriseId"):
            continue
        if item.get("isCurrentOneIdEnterprise") is True:
            continue
        if item.get("uid"):
            personal.append(item)
    if not personal:
        raise ValueError("请在 WorkBuddy 官网登录个人账号后重试")
    session = {
        "origin": WORKBUDDY_ORIGIN,
        "access_token": token,
        "refresh_token": str(data.get("refreshToken") or ""),
        "domain": domain,
        "uid": str(personal[0]["uid"]),
    }
    _save_workbuddy_session(session)
    metrics, plan, error = workbuddy_online()
    return {"plan": plan, "metrics": metrics, "error": error}


def _copilot_keyring(key):
    """Copilot CLI's token in the Secret Service, when secret-tool exists."""
    tool = shutil.which("secret-tool")
    if not tool:
        return ""
    for attribute in ("account", "username"):
        try:
            done = subprocess.run(
                [tool, "lookup", "service", "copilot-cli", attribute, key],
                capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        token = done.stdout.strip()
        if token:
            return token
    return ""


def _post_form(url, form, timeout=15):
    data = urlencode(form).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "ukui-dynamic-island/0.6"})
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read(1_000_000).decode("utf-8", "replace"))


def copilot_device_start():
    raw = _post_form(COPILOT_DEVICE_URL,
                     {"client_id": COPILOT_CLIENT_ID, "scope": "read:user"})
    if not isinstance(raw, dict) or not raw.get("device_code") \
            or not raw.get("user_code"):
        raise ValueError("GitHub 没有返回设备码")
    return raw


def copilot_device_poll(device_code, interval):
    """Returns (token, next_interval); token is None while pending."""
    raw = _post_form(COPILOT_TOKEN_URL, {
        "client_id": COPILOT_CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    if not isinstance(raw, dict):
        raise ValueError("GitHub 登录响应无效")
    error = str(raw.get("error") or "")
    if error == "authorization_pending":
        return None, interval
    if error == "slow_down":
        return None, interval + 5
    if error:
        raise ValueError(str(raw.get("error_description") or error))
    token = str(raw.get("access_token") or "")
    if not token:
        raise ValueError("GitHub 没有返回登录令牌")
    return token, interval


def _copilot_session_path():
    return config_dir() / "copilot.json"


def copilot_session():
    try:
        raw = json.loads(_copilot_session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(
            raw.get("access_token"), str) or not raw["access_token"]:
        return None
    return raw


def _save_copilot_session(token):
    _save_private_json(_copilot_session_path(), {"access_token": token})


def copilot_token(home=None):
    """The GitHub token Copilot's editors, CLI, or gh already signed in with."""
    session = copilot_session()
    if session:
        return session["access_token"], "copilot-login"
    base = Path(home or Path.home())
    for name in ("apps.json", "hosts.json"):
        path = base / ".config" / "github-copilot" / name
        try:
            apps = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(apps, dict):
            continue
        for key in sorted(apps):
            item = apps.get(key)
            if (key.startswith("github.com") and isinstance(item, dict)
                    and item.get("oauth_token")):
                return str(item["oauth_token"]), str(item.get("user") or "")
    path = base / ".copilot" / "config.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = None
    if not isinstance(cfg, dict):
        cfg = {}
    users = []
    if isinstance(cfg.get("lastLoggedInUser"), dict):
        users.append(cfg["lastLoggedInUser"])
    users += [item for item in cfg.get("loggedInUsers") or []
              if isinstance(item, dict)]
    tokens = cfg.get("copilotTokens")
    tokens = tokens if isinstance(tokens, dict) else {}
    for user in users:
        login = str(user.get("login") or "")
        host = str(user.get("host") or "")
        if not login or (host and "github.com" not in host):
            continue
        key = "https://github.com:" + login
        token = tokens.get(key) or _copilot_keyring(key)
        if token:
            return str(token), login
    if shutil.which("gh"):
        try:
            done = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                  text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            done = None
        if done is not None and done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip(), ""
    return None, ""


def parse_copilot_online(raw, now=None):
    if not isinstance(raw, dict):
        raise ValueError("Copilot 返回了无效数据")
    now = now or time.time()
    plan = str(raw.get("copilot_plan") or "")
    sku = str(raw.get("access_type_sku") or "")
    if sku == "free_limited_copilot":
        plan = "Free"
    elif sku == "free_educational_quota":
        plan = "Education"
    elif plan:
        plan = plan[:1].upper() + plan[1:]
    reset = _timestamp(raw.get("quota_reset_date_utc")
                       or raw.get("quota_reset_date"))
    snapshots = raw.get("quota_snapshots")
    snapshots = snapshots if isinstance(snapshots, dict) else {}
    metrics = []
    for key, label in (("chat", "Chat 请求"), ("completions", "补全"),
                       ("premium_interactions", "高级请求")):
        node = snapshots.get(key)
        if not isinstance(node, dict):
            continue
        if node.get("unlimited") is True:
            if key == "premium_interactions" and node.get("has_quota") is False:
                metrics.append(_metric(label, 1.0, reset, window=43200,
                                       text="已用完", now=now))
            else:
                metrics.append(_metric(label, 0.0, kind="balance",
                                       text="不限", window=43200, now=now))
            continue
        total = _number(node.get("entitlement"))
        left = _number(node.get("quota_remaining"))
        if total is not None and total <= 0:
            continue
        if total and left is not None:
            used = max(0.0, min(1.0, (total - left) / total))
            text = f"{max(0.0, left):g}/{total:g}"
        elif node.get("percent_remaining") is not None:
            used = 1.0 - float(node["percent_remaining"]) / 100.0
            text = f"{max(0.0, float(node['percent_remaining'])):.0f}%"
        else:
            continue
        metrics.append(_metric(label, used, reset, window=43200,
                               text=text, now=now))
    return metrics, plan


def copilot_online(home=None, now=None):
    """Opt-in: asks Copilot's account endpoint with the local sign-in."""
    now = now or time.time()
    token, _ = copilot_token(home)
    if not token:
        return [], "", "未找到 Copilot 登录信息，请先登录 VS Code 或 Copilot CLI"
    headers = dict(COPILOT_HEADERS)
    headers["Authorization"] = "token " + token
    try:
        raw = _http_json(COPILOT_USER_URL, None, headers)
    except Exception as exc:
        return [], "", _online_error(exc)
    metrics, plan = parse_copilot_online(raw, now)
    return metrics, plan, ("" if metrics else "Copilot 未返回额度")


def codex_online(home=None, now=None):
    """Opt-in: asks Codex's account endpoint with the local sign-in."""
    now = now or time.time()
    path = Path(home or Path.home()) / ".codex" / "auth.json"
    try:
        auth = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, 0.0, "", "未找到 Codex 登录信息"
    tokens = auth.get("tokens") if isinstance(auth, dict) else None
    tokens = tokens if isinstance(tokens, dict) else {}
    token = tokens.get("access_token")
    if not isinstance(token, str) or not token:
        return {}, 0.0, "", "未找到 Codex 登录信息"
    extra = {}
    if tokens.get("account_id"):
        extra["ChatGPT-Account-Id"] = str(tokens["account_id"])
    try:
        raw = _http_json(CODEX_USAGE_URL, token, extra)
    except Exception as exc:
        return {}, 0.0, "", _online_error(exc)
    windows, plan = parse_codex_online(raw)
    return windows, now, plan, ("" if windows else "在线额度没有可用周期")


def claude_online(home=None, now=None):
    """Opt-in: asks Claude's account endpoint with the local sign-in."""
    now = now or time.time()
    path = Path(home or Path.home()) / ".claude" / ".credentials.json"
    try:
        auth = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], "", "未找到 Claude 登录信息"
    oauth = auth.get("claudeAiOauth") if isinstance(auth, dict) else None
    oauth = oauth if isinstance(oauth, dict) else {}
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token:
        return [], "", "未找到 Claude 登录信息"
    plan = CLAUDE_PLANS.get(str(oauth.get("subscriptionType") or "").lower(), "")
    try:
        raw = _http_json(CLAUDE_USAGE_URL, token,
                         {"anthropic-beta": "oauth-2025-04-20"})
    except Exception as exc:
        return [], plan, _online_error(exc)
    metrics = parse_claude_online(raw, now)
    return metrics, plan, ("" if metrics else "在线额度没有可用周期")


def _codex_provider(cfg, home, now):
    usage = codex_usage(home)
    limits, stamp, plan, failure = {}, 0.0, "", ""
    if cfg.get("codex_online"):
        limits, stamp, plan, failure = codex_online(home, now)
        if not parse_codex_limits(limits, now):
            limits, stamp, plan = {}, 0.0, ""
    metrics = parse_codex_limits(limits, now) if limits else []
    if metrics:
        note = "Codex 官方在线额度"
        if not cfg.get("codex_online"):
            plan = PLANS.get(str(limits.get("plan_type") or "").lower(), "")
            note = "本机官方配额快照"
    else:
        local, local_stamp = latest_codex_limits(home, now)
        metrics = parse_codex_limits(local, now) if local else []
        if metrics:
            limits, stamp = local, local_stamp
            plan = PLANS.get(str(local.get("plan_type") or "").lower(), "")
            note = (failure + "，改用本机配额快照"
                    if failure else "本机官方配额快照")
        else:
            metrics = [_metric(
                "今日 Token", 0.0, kind="balance",
                text=f"{usage['total'] / 1e6:.2f}M",
                note="本机用量", now=now)]
            plan = ""
            note = (failure + "，本机用量如上" if failure
                    else "未找到官方额度快照")
    return {
        "id": "codex",
        "label": "Codex",
        "plan": plan,
        "status": "ok",
        "error": "",
        "updated": stamp or now,
        "metrics": metrics,
        "usage": {"today": usage["total"], "sessions": usage["sessions"]},
        "note": note,
    }


def _claude_provider(cfg, home, now):
    usage = claude_usage(home)
    metrics, plan, failure = [], "本地记录", ""
    if cfg.get("claude_online"):
        metrics, plan, failure = claude_online(home, now)
    if metrics:
        note = "Claude 官方在线额度"
    else:
        metrics = claude_history(home, now)
        if metrics:
            note = (failure + "，改用桌面版本地记录"
                    if failure else "桌面版本地记录")
        else:
            metrics = [_metric(
                "今日 Token", 0.0, kind="balance",
                text=f"{usage['total'] / 1e6:.2f}M",
                note="本机用量", now=now)]
            note = (failure + "，本机用量如上" if failure
                    else "未找到桌面版额度缓存")
            plan = "本地记录"
    return {
        "id": "claude",
        "label": "Claude",
        "plan": plan,
        "status": "ok",
        "error": "",
        "updated": now,
        "metrics": metrics,
        "usage": {"today": usage["total"], "sessions": usage["sessions"]},
        "note": note,
    }


def _workbuddy_provider(cfg, home, now):
    usage = workbuddy_usage(home)
    week = workbuddy_usage(home, days=7)
    failure = ""
    if cfg.get("workbuddy_online"):
        metrics, plan, failure = workbuddy_online(now)
        if metrics:
            return {
                "id": "workbuddy",
                "label": "WorkBuddy",
                "plan": plan or "个人版",
                "status": "ok",
                "error": "",
                "updated": now,
                "metrics": metrics,
                "usage": {"today": usage["total"],
                          "sessions": usage["sessions"]},
                "note": "WorkBuddy 官方积分",
            }
    metrics = [
        _metric("今日 Token", 0.0, kind="balance",
                text=f"{usage['total'] / 1e6:.2f}M",
                note="本机 trace 统计", now=now),
        _metric("近 7 天", 0.0, kind="balance",
                text=f"{week['total'] / 1e6:.2f}M",
                note=f"{week['sessions']} 个会话", now=now),
    ]
    return {
        "id": "workbuddy",
        "label": "WorkBuddy",
        "plan": "本机记录",
        "status": "ok",
        "error": "",
        "updated": now,
        "metrics": metrics,
        "usage": {"today": usage["total"], "sessions": usage["sessions"]},
        "note": ((failure + "，改用本机 trace") if failure
                 else "本机 trace 统计，不含网页版"),
    }


def _trae_provider(cfg, home, now):
    if not cfg.get("trae_online"):
        return None
    metrics, plan, failure = trae_online(home, now)
    if not metrics:
        return {
            "id": "trae", "label": "Trae CN", "plan": "",
            "status": "error", "error": failure, "updated": 0,
            "metrics": [], "usage": None, "note": "在线额度不可用",
        }
    return {
        "id": "trae", "label": "Trae CN", "plan": plan or "在线额度",
        "status": "ok", "error": "", "updated": now,
        "metrics": metrics, "usage": None, "note": "Trae CN 官方在线额度",
    }


def _copilot_provider(cfg, home, now):
    if not cfg.get("copilot_online"):
        return None
    metrics, plan, failure = copilot_online(home, now)
    if not metrics:
        return {
            "id": "copilot", "label": "Copilot", "plan": "",
            "status": "error", "error": failure, "updated": 0,
            "metrics": [], "usage": None, "note": "在线额度不可用",
        }
    return {
        "id": "copilot", "label": "Copilot", "plan": plan or "在线额度",
        "status": "ok", "error": "", "updated": now,
        "metrics": metrics, "usage": None, "note": "Copilot 官方在线额度",
    }


def _remote_provider(cfg, now):
    url = str(cfg.get("quota_url") or "").strip()
    if not url:
        return None
    remote = http_quota(url, token=str(cfg.get("quota_token") or ""))
    if remote.get("status") != "ok":
        return {
            "id": "remote", "label": "中转", "plan": "自定义 JSON",
            "status": "error", "error": remote.get("error", "读取失败"),
            "updated": 0, "metrics": [], "usage": None,
            "note": "中转/自定义额度不可用",
        }
    used = remote.get("percent")
    kind = "balance" if used is None else "percent"
    metrics = [_metric("额度", used or 0.0, kind=kind,
                       text=remote.get("text") or "—", now=now)]
    return {
        "id": "remote", "label": "中转", "plan": "自定义 JSON",
        "status": "ok", "error": "", "updated": now, "metrics": metrics,
        "usage": None, "note": "中转/自定义 JSON 源",
    }


def collect(cfg, home=None):
    now = time.time()
    providers = []
    for build in (_codex_provider, _claude_provider, _workbuddy_provider,
                  _trae_provider, _copilot_provider, _remote_provider):
        try:
            if build is _remote_provider:
                provider = build(cfg, now)
            else:
                provider = build(cfg, home, now)
            if provider:
                providers.append(provider)
        except Exception as exc:
            providers.append({
                "id": getattr(build, "__name__", "quota").replace("_provider", ""),
                "label": "额度", "plan": "", "status": "error",
                "error": f"{type(exc).__name__}: {exc}", "updated": 0,
                "metrics": [], "usage": None, "note": "读取失败",
            })
    return {"providers": providers, "at": time.strftime("%H:%M")}


class WorkBuddyLogin(QThread):
    opened = Signal(str)
    authorized = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            state, url = workbuddy_login_start()
        except Exception as exc:
            self.failed.emit(f"WorkBuddy 登录失败：{exc}")
            return
        self.opened.emit(url)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if self.isInterruptionRequested():
                return
            try:
                result = workbuddy_login_poll(state)
            except urllib.error.HTTPError as exc:
                self.failed.emit(f"WorkBuddy 登录失败（HTTP {exc.code}）")
                return
            except (urllib.error.URLError, TimeoutError, OSError):
                result = None
            except Exception as exc:
                self.failed.emit(str(exc))
                return
            if result:
                self.authorized.emit(result)
                return
            for _ in range(20):
                if self.isInterruptionRequested():
                    return
                self.msleep(100)
        self.failed.emit("WorkBuddy 登录等待超时，请重试")


class TraeLogin(QThread):
    """Trae's own browser authorization, back to a local callback."""

    opened = Signal(str)
    authorized = Signal(dict)
    failed = Signal(str)

    def run(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        got = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/authorize":
                    self.send_response(404)
                    self.end_headers()
                    return
                got.append(parse_qs(parsed.query))
                body = ("<html><meta charset='utf-8'><body>"
                        "Trae CN 已登录，可以关闭此页面。</body></html>"
                        ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        try:
            device, machine = _trae_device_ids()
            server = HTTPServer(("127.0.0.1", 0), Handler)
        except OSError as exc:
            self.failed.emit(f"Trae CN 登录失败：{exc}")
            return
        server.timeout = 1
        try:
            port = server.server_address[1]
            self.opened.emit(trae_login_url(
                device, machine,
                f"http://127.0.0.1:{port}/authorize"))
            deadline = time.monotonic() + 600
            while (time.monotonic() < deadline and not got
                   and not self.isInterruptionRequested()):
                server.handle_request()
        finally:
            server.server_close()
        if not got:
            if not self.isInterruptionRequested():
                self.failed.emit("Trae CN 登录等待超时，请重试")
            return
        try:
            session = parse_trae_callback(got[0])
            session["device_id"], session["machine_id"] = device, machine
            _save_private_json(_trae_session_path(), session)
            metrics, plan, error = trae_online(now=time.time())
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.authorized.emit({"plan": plan, "metrics": metrics,
                              "error": error})


class CopilotLogin(QThread):
    """GitHub's device flow under Copilot's own OAuth app."""

    opened = Signal(str, str)
    authorized = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            start = copilot_device_start()
        except Exception as exc:
            self.failed.emit(f"Copilot 登录失败：{exc}")
            return
        interval = max(1, int(start.get("interval") or 5))
        expires = max(60, int(start.get("expires_in") or 900))
        self.opened.emit(
            str(start.get("verification_uri") or "https://github.com/login/device"),
            str(start.get("user_code")))
        deadline = time.monotonic() + expires
        misses = 0
        while time.monotonic() < deadline:
            if self.isInterruptionRequested():
                return
            for _ in range(interval * 10):
                if self.isInterruptionRequested():
                    return
                self.msleep(100)
            try:
                token, interval = copilot_device_poll(
                    start["device_code"], interval)
                misses = 0
            except (urllib.error.URLError, TimeoutError, OSError):
                misses += 1
                if misses >= 5:
                    self.failed.emit("GitHub 登录请求连续失败，请重试")
                    return
                continue
            except Exception as exc:
                self.failed.emit(str(exc))
                return
            if not token:
                continue
            try:
                _save_copilot_session(token)
                metrics, plan, error = copilot_online(now=time.time())
            except Exception as exc:
                self.failed.emit(str(exc))
                return
            self.authorized.emit({"plan": plan, "metrics": metrics,
                                  "error": error})
            return
        self.failed.emit("Copilot 登录等待超时，请重试")


class Quota(QThread):
    updated = Signal(dict)

    def __init__(self, cfg, interval=180, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.interval = interval
        self._refreshing = False

    def refresh(self):
        self._refreshing = True

    def run(self):
        while not self.isInterruptionRequested():
            result = collect(self.cfg)
            if self.isInterruptionRequested():
                break
            self.updated.emit(result)
            waited = 0.0
            while waited < self.interval and not self.isInterruptionRequested():
                if self._refreshing:
                    self._refreshing = False
                    break
                self.msleep(250)
                waited += 0.25
