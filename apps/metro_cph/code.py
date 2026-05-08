# v12

from __main__ import *
import sys, time, gc
import json
import load_screen
from load_screen import *
from check_button import check_if_button_pressed

microcontroller.cpu.frequency = 160000000

DISP_W = settings["width"]
DISP_H = settings["height"]

OPS_URL = "http://metroapi.hextransit.com/operationsdata"
DEP_URL_BASE = "http://metroapi.hextransit.com/departures?station_id="
DEP_URL_SUFFIX = ""

SETTINGS_FILE = "metro_cphsettings.json"
DEFAULTS = {
    "station_id": "8603317",
    "station_name": "Vestamager",
    "refresh_s": 15,
    "scroll_speed": 1,
    "frame_delay": 0.03,
}

FONT = font_mini
FONT_H = FONT["fontheight"]
LINE_STEP = 6
TOP_Y = 1

COLOR = {
    "black": 0,
    "yellow": 1,
    "brightwhite": 2,
    "blue": 3,
    "red": 4,
    "white": 5,
    "light_blue": 6,
    "green": 7,
    "orange": 11,
}

LINE_COLORS = {
    "M1": "green",
    "M2": "yellow",
    "M3": "red",
    "M4": "blue",
}

MAIN_COLOR = "orange"
TIME_COLOR = "light_blue"
SEP_COLOR = "white"


def _load_stations():
    try:
        with open("stations.json") as f:
            data = json.load(f)
    except:
        data = []

    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        if not sid or not name:
            continue
        # Only store what we actually need to save RAM
        out.append({"id": sid, "name": name})

    return out


STATIONS = _load_stations()


def _station_name_from_id(station_id):
    sid = str(station_id or "").strip()
    for st in STATIONS:
        if st["id"] == sid:
            return st["name"]
    return ""


def _first_station_id():
    if STATIONS:
        return STATIONS[0]["id"]
    return DEFAULTS["station_id"]


def load_cfg():
    try:
        with open(SETTINGS_FILE) as f:
            cfg = json.loads(f.read())
    except:
        cfg = {}

    for k, v in DEFAULTS.items():
        if k not in cfg:
            cfg[k] = v

    try:
        cfg["refresh_s"] = max(10, int(cfg["refresh_s"]))
    except:
        cfg["refresh_s"] = DEFAULTS["refresh_s"]

    try:
        cfg["scroll_speed"] = max(1, int(cfg["scroll_speed"]))
    except:
        cfg["scroll_speed"] = DEFAULTS["scroll_speed"]

    try:
        cfg["frame_delay"] = float(cfg["frame_delay"])
        if cfg["frame_delay"] <= 0:
            cfg["frame_delay"] = DEFAULTS["frame_delay"]
    except:
        cfg["frame_delay"] = DEFAULTS["frame_delay"]

    cfg["station_id"] = str(cfg.get("station_id", "")).strip()
    if not cfg["station_id"]:
        cfg["station_id"] = _first_station_id()

    station_name = _station_name_from_id(cfg["station_id"])
    if station_name:
        cfg["station_name"] = station_name
    else:
        # If stations.json changed, fall back to first valid station entry.
        cfg["station_id"] = _first_station_id()
        station_name = _station_name_from_id(cfg["station_id"])
        cfg["station_name"] = station_name if station_name else DEFAULTS["station_name"]

    return cfg


def _save_cfg():
    # Only persist the station_id; station_name is derived from stations.json on load.
    to_save = {k: v for k, v in cfg.items() if k != "station_name"}
    try:
        with open(SETTINGS_FILE, "w") as f:
            f.write(json.dumps(to_save))
    except Exception as e:
        print("Save error:", e)


def _url_decode(s):
    s = s.replace("+", " ")
    out = ""
    i = 0
    while i < len(s):
        c = s[i]
        if c == "%" and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except:
                pass
        out += c
        i += 1
    return out


def _parse_form(body):
    params = {}
    if not body:
        return params
    for pair in str(body).split("&"):
        if not pair:
            continue
        if "=" in pair:
            k, v = pair.split("=", 1)
        else:
            k, v = pair, ""
        params[_url_decode(k)] = _url_decode(v)
    return params


cfg = load_cfg()
# Persist any defaults / resolved station_id back to disk so the file always has the id.
_save_cfg()


def _departures_url():
    return DEP_URL_BASE + str(cfg["station_id"]) + DEP_URL_SUFFIX


last_error = ""

def _safe_json_get(url):
    global last_error
    resp = None
    try:
        gc.collect()
        resp = requests.get(url, headers={"User-Agent": "MatrixBox"})
        # On microcontrollers, loading the full JSON dynamically might still blow out RAM
        # Let's try buffering it in via `json.load()` if the request object supports file-like streaming
        try:
            import io
            out = json.load(io.StringIO(resp.text))
        except:
            out = resp.json()
        finally:
            resp.close()
        last_error = ""
        return out
    except Exception as e:
        last_error = "API error: " + str(e)
        try:
            if resp:
                resp.close()
        except:
            pass
        return None


def _safe_minute_text(v):
    text = str(v or "").strip()
    if text == "\xbd":
        return "NOW"
    return text if text else "-"


def _text_width(text):
    if FONT == font_mini:
        text = str(text).lower()
    return strlen(str(text), FONT)


def _draw_text(text, x, y, color_idx, clip_left=0, clip_right=None):
    if clip_right is None:
        clip_right = DISP_W - 1

    px = int(x)
    for ch in str(text):
        if FONT == font_mini:
            ch = ch.lower()
        if ch not in FONT:
            ch = "_"
        glyph = FONT[ch]
        gw = glyph[0]
        is_bitmap = isinstance(glyph[1], int)
        if is_bitmap:
            for w in range(gw):
                sx = px + w
                if sx < clip_left or sx > clip_right or sx < 0 or sx >= DISP_W:
                    continue
                inv_w = gw - w
                for h in range(FONT_H):
                    sy = y + h
                    if sy < 0 or sy >= DISP_H:
                        continue
                    bit = (glyph[h + 1] >> inv_w) & 1
                    if bit:
                        window[sx, sy] = color_idx
        px += gw


def _draw_dot(x, y, color_idx):
    for yy in range(y, y + 2):
        for xx in range(x, x + 2):
            if 0 <= xx < DISP_W and 0 <= yy < DISP_H:
                window[xx, yy] = color_idx


def _normalize_group(group_txt):
    raw = str(group_txt or "").rstrip().upper()
    parts = []
    for p in raw.split("/"):
        p = p.strip()
        if p:
            parts.append(p)
    return "/".join(parts)


def fetch_departures():
    data = _safe_json_get(_departures_url())
    if not isinstance(data, list) or not data:
        return []

    metro_block = None
    for blk in data:
        if str(blk.get("type", "")).upper() == "M":
            metro_block = blk
            break
    if metro_block is None:
        return []

    out = []
    dep_outer = metro_block.get("departures", [])
    for bucket in dep_outer:
        if not isinstance(bucket, list):
            continue
        for d in bucket:
            if not isinstance(d, dict):
                continue
            line = str(d.get("line", "")).strip().upper()
            if not line.startswith("M"):
                continue
            out.append({
                "line": line,
                "direction": str(d.get("direction", "")).strip(),
                "minutes": _safe_minute_text(d.get("formattedMinutes", "")),
                "timestamp": str(d.get("timestamp", "")),
            })

    return out


def fetch_operations():
    data = _safe_json_get(OPS_URL)
    state = {
        "M1/M2": {"clear": True, "message": ""},
        "M3/M4": {"clear": True, "message": ""},
    }
    if not isinstance(data, dict):
        return state

    if not bool(data.get("activeWarning", False)):
        return state

    msgs = data.get("activeMessages", [])
    if not isinstance(msgs, list):
        return state

    for msg in msgs:
        if not isinstance(msg, dict):
            continue
        line_setup = msg.get("lineSetup", {})
        if not isinstance(line_setup, dict):
            continue
        group = _normalize_group(line_setup.get("lineGroup", ""))
        text = str(msg.get("name", "")).strip()
        if not text:
            continue
        if group in state:
            if text.lower() == "vi kører efter planen":
                state[group]["clear"] = True
                state[group]["message"] = text
            else:
                state[group]["clear"] = False
                state[group]["message"] = text

    return state


def build_rows(dep_list, ops_state):
    rows = {
        "ops12": ops_state.get("M1/M2", {"clear": True, "message": ""}),
        "ops34": ops_state.get("M3/M4", {"clear": True, "message": ""}),
        "deps": []
    }

    if dep_list:
        for d in dep_list[:3]:
            rows["deps"].append({
                "line": d.get("line", "M"),
                "direction": str(d.get("direction", "")).strip() or "Unknown",
                "minutes": str(d.get("minutes", "-"))
            })

    return rows


def _clip_to_width(text, max_px):
    text = str(text)
    if _text_width(text) <= max_px:
        return text
    while text and _text_width(text + "...") > max_px:
        text = text[:-1]
    return (text + "...") if text else ""


def _draw_row_right_aligned(line_no, left_text, right_text, left_color, right_color):
    y = TOP_Y + (line_no * LINE_STEP)
    right_w = _text_width(right_text)
    right_x = max(0, DISP_W - right_w)
    left_max = max(0, right_x - 1)
    left_txt = _clip_to_width(left_text, left_max)

    _draw_text(left_txt, 0, y, COLOR[left_color], clip_left=0, clip_right=left_max)
    _draw_text(right_text, right_x, y, COLOR[right_color], clip_left=right_x, clip_right=DISP_W - 1)


def _draw_line_group_label(x, y, line_a, line_b):
    """Draw e.g. 'M1/M2' with each line code in its own color. Returns end x."""
    _draw_text(line_a, x, y, COLOR[LINE_COLORS.get(line_a, "white")])
    x += _text_width(line_a)
    _draw_text("/", x, y, COLOR[SEP_COLOR])
    x += _text_width("/")
    _draw_text(line_b, x, y, COLOR[LINE_COLORS.get(line_b, "white")])
    x += _text_width(line_b)
    return x


def _draw_status_row(line_no, status_obj, line_a, line_b, scroll_px):
    y = TOP_Y + (line_no * LINE_STEP)
    label_text = line_a + "/" + line_b
    label_w = _text_width(label_text)
    _draw_line_group_label(0, y, line_a, line_b)

    msg_x_start = label_w + 2
    msg_clip_right = DISP_W - 1

    if status_obj.get("clear", True):
        _draw_dot(msg_x_start, y + 1, COLOR["green"])
        return

    msg = str(status_obj.get("message", "")).strip()
    if not msg:
        return

    marquee = msg + "    "
    marquee_w = max(1, _text_width(marquee))
    x = msg_x_start - scroll_px
    while x < msg_clip_right:
        _draw_text(marquee, x, y, COLOR[MAIN_COLOR],
                   clip_left=msg_x_start, clip_right=msg_clip_right)
        x += marquee_w


def _draw_dep_row(line_no, dep):
    y = TOP_Y + (line_no * LINE_STEP)
    if not dep:
        _draw_text("-", 0, y, COLOR[MAIN_COLOR])
        return

    line = dep["line"]
    direction = str(dep["direction"]).upper()
    minutes = dep["minutes"]

    line_w = _text_width(line) + 2
    right_w = _text_width(minutes)
    right_x = max(0, DISP_W - right_w)
    left_max = max(0, right_x - 1)

    _draw_text(line, 0, y, COLOR[LINE_COLORS.get(line, "white")])
    
    msg_x_start = line_w
    left_txt = _clip_to_width(direction, max(0, left_max - msg_x_start))

    _draw_text(left_txt, msg_x_start, y, COLOR[MAIN_COLOR], clip_left=msg_x_start, clip_right=left_max)
    _draw_text(minutes, right_x, y, COLOR[TIME_COLOR], clip_left=right_x, clip_right=DISP_W - 1)


def render(rows, scroll12, scroll34):
    window.fill(0)

    deps = rows.get("deps", [])
    for i in range(3):
        dep = deps[i] if i < len(deps) else None
        _draw_dep_row(i, dep)

    _draw_status_row(3, rows["ops12"], "M1", "M2", scroll12)
    _draw_status_row(4, rows["ops34"], "M3", "M4", scroll34)

    refresh()


@ampule.route("/", method="GET")
def metro_interface(request):
    gc.collect()
    options = []
    selected_id = str(cfg.get("station_id", ""))
    for st in STATIONS:
        sel = " selected" if st["id"] == selected_id else ""
        options.append("<option value=\"" + st["id"] + "\"" + sel + ">" + st["name"] + " (" + st["id"] + ")</option>")

    if not options:
        options = ["<option value=\"\">No stations found</option>"]

    html = (
        "<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head><body>"
        "<a href=\"/exit\">&#x274C;</a><br>"
        "<b>Copenhagen Metro board</b><br><br>"
        "<form method=\"post\" action=\"/\">"
        "<label for=\"station_id\">Station:</label>"
        "<select name=\"station_id\" id=\"station_id\">"
        + "".join(options)
        + "</select>"
        "<button type=\"submit\">Save</button>"
        "</form><br>"
        "<b>Debug Info:</b><br>"
        "URL: " + _departures_url() + "<br>"
        "Rows: <pre>" + json.dumps(rows) + "</pre><br>"
        "Last Error: " + str(last_error) + "<br>"
        "</body></html>"
    )
    gc.collect()
    return (200, {}, html)


@ampule.route("/", method="POST")
def metro_interface_post(request):
    global last_fetch, rows
    body = getattr(request, "body", "") or ""
    form = _parse_form(body)
    sid = str(form.get("station_id", "")).strip()
    if not sid and "station_id" in request.params:
        sid = str(request.params["station_id"]).strip()
        
    if sid and _station_name_from_id(sid):
        cfg["station_id"] = sid
        cfg["station_name"] = _station_name_from_id(sid)
        _save_cfg()
        last_fetch = -999
        rows["ops12"] = {"clear": True, "message": ""}
        rows["ops34"] = {"clear": True, "message": ""}
        rows["deps"] = []
    return (200, {}, """<meta http-equiv=\"refresh\" content=\"0; url=/\" />""")


@ampule.route("/exit", method="GET")
def exit_interface(request):
    load_settings.app_running = False
    return (200, {}, """<meta http-equiv=\"refresh\" content=\"0; url=../\" />""")


last_fetch = -999
rows = build_rows([], fetch_operations())
scroll12 = 0
scroll34 = 0

while load_settings.app_running:
    now = time.monotonic()
    if now - last_fetch >= cfg["refresh_s"]:
        deps = fetch_departures()
        ops = fetch_operations()
        rows = build_rows(deps, ops)
        last_fetch = now
        gc.collect()

    status12 = rows["ops12"]
    status34 = rows["ops34"]

    if status12.get("clear", True):
        scroll12 = 0
    else:
        w12 = max(1, _text_width(str(status12.get("message", "")).strip() + "    "))
        scroll12 = (scroll12 + cfg["scroll_speed"]) % w12

    if status34.get("clear", True):
        scroll34 = 0
    else:
        w34 = max(1, _text_width(str(status34.get("message", "")).strip() + "    "))
        scroll34 = (scroll34 + cfg["scroll_speed"]) % w34

    render(rows, scroll12, scroll34)
    ampule.listen(socket)

    b = check_if_button_pressed()
    if b:
        load_settings.app_running = False

    time.sleep(cfg["frame_delay"])

sys.exit()