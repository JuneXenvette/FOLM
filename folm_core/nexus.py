"""nexus - Nexus Mods "Mod Manager Download" (nxm://) links.

Clicking "Mod Manager Download" on Nexus opens a link like

    nxm://newvegas/mods/66537/files/1000123456?key=abc&expires=1763400000&user_id=42

The key/expires pair is a one-time download ticket from the website, so free accounts
work as well as Premium. FOLM asks the Nexus API for the real download address (using
the player's own personal API key, from https://www.nexusmods.com/settings/api-keys),
downloads the file into FOLM's library, and installs it with the right installer.

The API key is stored only on this PC (~/Games/FOLM/nexus.json, readable by you only)
and is sent only to api.nexusmods.com.
"""

import http.client
import json
import os
import re
import socket
import stat
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.nexusmods.com/v1"
APP_NAME, APP_VERSION = "FOLM", "1.1.0"   # sent to Nexus: keep it equal to the release
GAMES = {"newvegas": "courier", "fallout3": "wanderer", "ttw": "courier"}
NXM_RE = re.compile(r"^nxm://(?P<game>[a-z0-9]+)/mods/(?P<mod>\d+)/files/(?P<file>\d+)/?(?:\?(?P<query>.*))?$", re.I)


class NexusError(Exception):
    pass


def parse(url):
    """nxm:// link -> {"game", "edition", "mod_id", "file_id", "key", "expires", "user_id"}."""
    url = url.strip()
    if url.lower().startswith("nxm://") and "/collections/" in url.lower():
        raise NexusError("That's a Nexus Collection link. FOLM installs single mods for now; "
                         "use each mod's own Mod Manager Download button.")
    mm = NXM_RE.match(url)
    if not mm:
        raise NexusError(f"Not a Nexus mod download link: {url[:80]}")
    game = mm.group("game").lower()
    if game not in GAMES:
        raise NexusError(f"That link is for another game ({game}); FOLM manages Fallout: New Vegas and Fallout 3.")
    q = urllib.parse.parse_qs(mm.group("query") or "")
    return {"game": game, "edition": GAMES[game], "mod_id": int(mm.group("mod")), "file_id": int(mm.group("file")),
            "key": (q.get("key") or [None])[0], "expires": (q.get("expires") or [None])[0],
            "user_id": (q.get("user_id") or [None])[0]}


# ------------------------------------------------------------------ API key (stored locally, owner-only)

def _key_path(home):
    return os.path.join(home, "nexus.json")


def load_key(home):
    try:
        return json.load(open(_key_path(home))).get("apikey")
    except (OSError, ValueError):
        return None


def save_key(home, apikey, account=None):
    path = _key_path(home)
    os.makedirs(home, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"apikey": apikey.strip(), "account": account or {}}, fh)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def forget_key(home):
    try:
        os.remove(_key_path(home))
    except FileNotFoundError:
        pass


def account(home):
    try:
        return json.load(open(_key_path(home))).get("account") or {}
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ API calls

def _get(path, apikey, params=None, opener=urllib.request.urlopen):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "apikey": apikey, "Accept": "application/json",
        "Application-Name": APP_NAME, "Application-Version": APP_VERSION,
        "User-Agent": f"{APP_NAME}/{APP_VERSION} (Linux)"})
    try:
        with opener(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("message", "")
        except Exception:
            msg = ""
        if e.code == 401:
            raise NexusError("Nexus didn't accept the API key. Paste your personal key again in FOLM's settings.")
        if e.code == 403 and "premium" in msg.lower():
            raise NexusError("Nexus only gives direct downloads to Premium members. Use the website's "
                             "'Mod Manager Download' button instead (it works with free accounts).")
        if e.code == 410 or "expired" in msg.lower():
            raise NexusError("That download link has expired. Click 'Mod Manager Download' on Nexus again.")
        if e.code == 429:
            raise NexusError("Nexus says too many requests for now. Try again in a little while.")
        raise NexusError(f"Nexus answered {e.code}{': ' + msg if msg else ''}")
    except (urllib.error.URLError, socket.timeout) as e:
        raise NexusError(f"Couldn't reach Nexus Mods ({getattr(e, 'reason', e)}). Check your internet connection.")


def validate(apikey, opener=urllib.request.urlopen):
    """Check a key; returns {"name", "premium"}."""
    r = _get("/users/validate.json", apikey, opener=opener)
    return {"name": r.get("name"), "premium": bool(r.get("is_premium"))}


def file_info(link, apikey, opener=urllib.request.urlopen):
    g, mod, f = link["game"], link["mod_id"], link["file_id"]
    info = _get(f"/games/{g}/mods/{mod}/files/{f}.json", apikey, opener=opener)
    try:
        mod_info = _get(f"/games/{g}/mods/{mod}.json", apikey, opener=opener)
    except NexusError:
        mod_info = {}
    return {"file_name": info.get("file_name"), "name": info.get("name"), "version": info.get("version")
            or mod_info.get("version"), "size": (info.get("size_in_bytes") or (info.get("size_kb") or 0) * 1024),
            "mod_name": mod_info.get("name") or info.get("name"), "category": info.get("category_name"),
            "md5": info.get("md5")}


def download_url(link, apikey, opener=urllib.request.urlopen):
    params = {k: link[k] for k in ("key", "expires") if link.get(k)}
    if not params:
        pass                                    # Premium accounts can download without a website ticket
    elif link.get("expires") and link["expires"].isdigit() and int(link["expires"]) < time.time():
        raise NexusError("That download link has expired. Click 'Mod Manager Download' on Nexus again.")
    r = _get(f"/games/{link['game']}/mods/{link['mod_id']}/files/{link['file_id']}/download_link.json",
             apikey, params, opener=opener)
    if not r:
        raise NexusError("Nexus didn't return a download server for that file.")
    return r[0]["URI"]


def safe_url(url):
    """Percent-encode characters a URL can't carry as-is (Nexus CDN paths contain the file name, spaces and all)."""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/@!$&'()*+,;=:~-._")
    query = urllib.parse.quote(parts.query, safe="=&%+/:@!$'()*,;~-._?")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def _safe_name(name):
    name = os.path.basename(name or "").strip()
    name = re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", name)
    return name or "download"


def download(url, dest_dir, file_name, size=None, log=lambda *a: None, opener=urllib.request.urlopen, md5=None):
    """Stream a file into dest_dir (via a .part file). Returns the final path."""
    import hashlib
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, _safe_name(file_name))
    part = final + ".part"
    url = safe_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION} (Linux)"})
    h = hashlib.md5()
    try:
        with opener(req, timeout=60) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or size or 0)
            got, last = 0, 0.0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if time.time() - last > 1.5:
                    last = time.time()
                    log(f"Downloading {os.path.basename(final)}: {got >> 20} MB"
                        + (f" of {total >> 20} MB ({got * 100 // total}%)" if total else ""))
    except (ValueError, http.client.HTTPException) as e:          # e.g. a malformed address
        raise NexusError(f"FOLM couldn't use the download address Nexus gave ({e}).")
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise NexusError(f"The download stopped ({getattr(e, 'reason', e)}). Click the Nexus button again to retry.")
    if total and got != total:
        raise NexusError(f"The download was incomplete ({got >> 20} of {total >> 20} MB). Try again.")
    if md5 and h.hexdigest().lower() != md5.lower():
        raise NexusError("The downloaded file doesn't match Nexus's checksum (damaged download). Try again.")
    os.replace(part, final)
    log(f"Downloaded {os.path.basename(final)} ({got >> 20} MB).")
    return final


# ------------------------------------------------------------------ handing links to a running FOLM

def socket_path(home):
    """A short path (sockets are limited to 108 characters): $XDG_RUNTIME_DIR/folm-<id>.sock."""
    import hashlib
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/folm-{os.getuid()}"
    os.makedirs(run, mode=0o700, exist_ok=True)
    return os.path.join(run, f"folm-{hashlib.sha1(os.path.abspath(home).encode()).hexdigest()[:10]}.sock")


def send_to_running_app(home, url):
    """True if a running FOLM app accepted the link."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(3)
        s.connect(socket_path(home))
        s.sendall(url.encode("utf-8") + b"\n")
        return True
    except OSError:
        return False
    finally:
        s.close()
