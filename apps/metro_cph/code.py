from __main__ import *
import sys, time, gc
from check_button import check_if_button_pressed

microcontroller.cpu.frequency = 160000000

DISP_W = settings["width"]
DISP_H = settings["height"]

OPS_URL = "https://m.dk/api/operationsdata/"
DEP_URL_BASE = "https://m.dk/api/departures/?ids="
DEP_URL_SUFFIX = "&useBus=false&useTrain=false"

SETTINGS_FILE = "metro_cphsettings.txt"
DEFAULTS = {
    "station_id": "8603317",
    "station_name": "Vestamager",
    "refresh_s": 30,
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
    "green": 7,
}

LINE_COLORS = {
    "M1": "green",
    "M2": "yellow",
    "M3": "red",
    "M4": "blue",
}


def _load_stations():
    try:
        with open("stations.json") as f:
            data = json.loads(f.read())
    except:
        data = []

    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        short_name = str(item.get("shortName", "")).strip()
        if not sid or not name:
            continue
        out.append({"id": sid, "name": name, "shortName": short_name})

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


cfg = load_cfg()


def _save_cfg():
    try:
        with open(SETTINGS_FILE, "w") as f:
            f.write(json.dumps(cfg))
    except Exception as e:
        print("Save error:", e)


def _departures_url():
    return DEP_URL_BASE + str(cfg["station_id"]) + DEP_URL_SUFFIX


def _safe_json_get(url):
    resp = None
    try:
        resp = requests.get(url, headers={"User-Agent": "MatrixBox"})
        out = json.loads(resp.text)
        resp.close()
        return out
    except Exception as e:
        print("API error:", e)
        try:
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
            state[group]["clear"] = False
            state[group]["message"] = text

    return state


def build_rows(dep_list, ops_state):
    rows = {
        "header_text": cfg["station_name"],
        "header_color": "white",
        "line2_left": "No departures",
        "line2_right": "-",
        "line3": "Next: -",
        "ops12": ops_state.get("M1/M2", {"clear": True, "message": ""}),
        "ops34": ops_state.get("M3/M4", {"clear": True, "message": ""}),
    }

    if not dep_list:
        return rows

    first = dep_list[0]
    line = first.get("line", "M")
    direction = first.get("direction", "").strip() or "Unknown"
    minutes = first.get("minutes", "-")

    rows["header_text"] = cfg["station_name"] + " " + line
    rows["header_color"] = LINE_COLORS.get(line, "white")
    rows["line2_left"] = direction
    rows["line2_right"] = minutes

    next_three = []
    for d in dep_list[1:]:
        if d.get("direction", "").strip() == direction:
            next_three.append(d.get("minutes", "-"))
        if len(next_three) == 3:
            break

    if next_three:
        rows["line3"] = "Next: " + " ".join(next_three)
    else:
        rows["line3"] = "Next: -"

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


def _draw_status_row(line_no, left_width, status_obj, label, scroll_px):
    y = TOP_Y + (line_no * LINE_STEP)
    label_w = _text_width(label)
    label_x = DISP_W - label_w

    _draw_text(label, label_x, y, COLOR["white"], clip_left=label_x, clip_right=DISP_W - 1)

    if status_obj.get("clear", True):
        _draw_dot(max(0, label_x - 4), y + 1, COLOR["green"])
        return

    msg = str(status_obj.get("message", "")).strip()
    if not msg:
        return

    # Repeat text with spacing for a seamless marquee.
    marquee = msg + "    "
    marquee_w = max(1, _text_width(marquee))
    x = -scroll_px
    while x < left_width:
        _draw_text(marquee, x, y, COLOR["yellow"], clip_left=0, clip_right=left_width - 1)
        x += marquee_w


def render(rows, scroll12, scroll34):
    window.fill(0)

    header = _clip_to_width(rows["header_text"], DISP_W)
    _draw_text(header, 0, TOP_Y + 0 * LINE_STEP, COLOR[rows["header_color"]])

    _draw_row_right_aligned(1, rows["line2_left"], rows["line2_right"], "white", "yellow")

    line3 = _clip_to_width(rows["line3"], DISP_W)
    _draw_text(line3, 0, TOP_Y + 2 * LINE_STEP, COLOR["white"])

    _draw_status_row(3, DISP_W - _text_width("M1/M2") - 1, rows["ops12"], "M1/M2", scroll12)
    _draw_status_row(4, DISP_W - _text_width("M3/M4") - 1, rows["ops34"], "M3/M4", scroll34)

    refresh()


@ampule.route("/", method="GET")
def metro_interface(request):
    options = []
    selected_id = str(cfg.get("station_id", ""))
    for st in STATIONS:
        sel = " selected" if st["id"] == selected_id else ""
        options.append("<option value=\"" + st["id"] + "\"" + sel + ">" + st["name"] + " (" + st["id"] + ")</option>")

    if not options:
        options = ["<option value=\"\">No stations found</option>"]

    html = (
        "<html><head><meta charset=\"utf-8\"></head><body>"
        "<a href=\"/exit\">&#x274C;</a><br>"
        "<b>Copenhagen Metro board</b><br><br>"
        "<form method=\"post\" action=\"/\">"
        "<label for=\"station_id\">Station:</label>"
        "<select name=\"station_id\" id=\"station_id\">"
        + "".join(options)
        + "</select>"
        "<button type=\"submit\">Save</button>"
        "</form><br>"
        "Current station: "
        + cfg["station_name"]
        + " ("
        + cfg["station_id"]
        + ")<br>"
        "</body></html>"
    )
    return (200, {}, html)


@ampule.route("/", method="POST")
def metro_interface_post(request):
    sid = str(request.params.get("station_id", "")).strip()
    if sid and _station_name_from_id(sid):
        cfg["station_id"] = sid
        cfg["station_name"] = _station_name_from_id(sid)
        _save_cfg()
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