"""Turns a time range into a vertical clip: 9:16 layout, bouncy word captions, hook title, cover."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config, roman
from .media import NO_WINDOW, run

W, H = config.OUT_W, config.OUT_H

# ASS colours are &HBBGGRR. `size` is the ASS font size (line height); _Font turns it into real pixels.
STYLES = {
    "bounce": {"label": "Bounce", "font": "Poppins ExtraBold", "size": 132, "base": "FFFFFF", "active": "00F0FF",
               "strong": "FFFFFF", "outline": 7, "pop": 112, "upper": True, "per": 3},
    "hype": {"label": "Hype", "font": "Anton", "size": 152, "base": "FFFFFF", "active": "3C3CFF",
             "strong": "00D7FF", "outline": 7, "pop": 114, "upper": True, "per": 2},
    "clean": {"label": "Clean", "font": "Poppins ExtraBold", "size": 100, "base": "FFFFFF", "active": "6BD7FF",
              "strong": "FFFFFF", "outline": 5, "pop": 106, "upper": False, "per": 4},
}
HOOK = {"font": "Poppins ExtraBold", "size": 96, "ink": "14100E", "box": "FFFFFF", "pad_x": 36, "pad_y": 22, "radius": 26,
        "max_w": 900}
FONT_FILES = {"Poppins ExtraBold": "Poppins-ExtraBold.ttf", "Anton": "Anton-Regular.ttf", "Archivo Black": "ArchivoBlack-Regular.ttf"}
CAP_MAX_W = 960   # captions never run wider than this, whatever is said

# Caption pacing: how long a line stays up after its last word is said (tail) and the least time it
# shows at all (hold), so a short phrase never flashes past. A line never lingers until the next one
# starts, so the words leave the screen with the speaker.
PACE = {"slow": {"label": "Slow", "tail": 0.9, "hold": 1.6},
        "normal": {"label": "Normal", "tail": 0.35, "hold": 1.0},
        "fast": {"label": "Fast", "tail": 0.15, "hold": 0.5}}

# Emojis that ride along with a caption word: one per line at most, matched on the word as spoken.
# They are painted over the words as true-colour pictures at the word's own place and time.
EMOJIS = {"car": "🏎️", "drift": "🏎️", "drive": "🚗", "driving": "🚗", "race": "🏁", "racing": "🏁",
          "win": "🏆", "wins": "🏆", "won": "🏆", "winner": "🏆", "trophy": "🏆",
          "lose": "😭", "loses": "😭", "lost": "😭", "loser": "😭",
          "die": "💀", "dies": "💀", "died": "💀", "dying": "💀", "dead": "💀", "death": "💀", "kill": "💀",
          "gun": "🔫", "shoot": "🔫", "shooting": "🔫", "shot": "🔫",
          "police": "🚓", "cop": "🚓", "cops": "🚓", "arrest": "🚔", "jail": "🚔", "prison": "🚔",
          "money": "💰", "cash": "💰", "rich": "💰", "dollars": "💰", "billion": "💰", "million": "💰",
          "explosion": "💥", "explode": "💥", "explodes": "💥", "bomb": "💥", "boom": "💥", "crash": "💥",
          "hit": "💥", "punch": "👊", "fight": "🥊", "fighting": "🥊", "war": "⚔️",
          "crazy": "🤯", "insane": "🤯", "wild": "🤯", "shocking": "😱", "omg": "😱", "scary": "😱",
          "funny": "😂", "lol": "😂", "laugh": "😂", "joke": "😂", "hilarious": "😂",
          "love": "❤️", "heart": "❤️", "kiss": "💋", "baby": "👶", "girl": "👧", "boy": "👦",
          "dog": "🐕", "cat": "🐱", "horse": "🐎", "shark": "🦈", "fish": "🐟", "bird": "🐦",
          "fire": "🔥", "burning": "🔥", "burn": "🔥", "hot": "🔥",
          "water": "💦", "ocean": "🌊", "sea": "🌊", "swim": "🏊", "rain": "🌧️", "snow": "❄️",
          "fast": "⚡", "speed": "⚡", "quick": "⚡", "power": "⚡", "electric": "⚡",
          "sleep": "😴", "sleeping": "😴", "tired": "😴", "night": "🌙", "sun": "☀️", "star": "⭐",
          "eat": "🍔", "food": "🍔", "pizza": "🍕", "coffee": "☕", "drink": "🥤",
          "phone": "📱", "computer": "💻", "game": "🎮", "gaming": "🎮", "gamer": "🎮", "controller": "🎮",
          "map": "🗺️", "secret": "🤫", "hidden": "🔍", "found": "🔍", "find": "🔍", "look": "👀",
          "king": "👑", "boss": "😈", "hero": "🦸", "friend": "🤝", "team": "🤝",
          "run": "🏃", "running": "🏃", "jump": "🤸", "flying": "✈️", "fly": "✈️", "helicopter": "🚁",
          "boat": "🚤", "ship": "🚢", "train": "🚂", "plane": "✈️", "bike": "🏍️", "house": "🏠",
          "mission": "🎯", "goal": "🎯", "level": "🎮", "new": "🆕", "first": "🥇", "best": "🥇",
          "party": "🎉", "dance": "💃", "music": "🎵", "wait": "⏳", "stop": "✋", "idea": "💡",
          "talk": "💬", "chat": "💬", "say": "💬", "watch": "📺", "stream": "📺", "video": "📺",
          "chase": "🚓", "chasing": "🚓", "wanted": "👮", "heist": "💰", "steal": "🦹", "stolen": "🦹",
          "criminal": "🦹", "rob": "🦹", "robbery": "🦹", "escape": "🏃", "flee": "🏃",
          "chopper": "🚁", "parachute": "🪂", "rooftop": "🏠", "crashed": "💥", "rocket": "🚀", "space": "🚀",
          "boost": "⚡", "nitro": "⚡", "turbo": "⚡", "broke": "😢", "champion": "🏆", "goat": "🐐",
          "noob": "🤡", "clown": "🤡", "grenade": "💣", "truck": "🚚", "vehicle": "🚗", "engine": "🚗",
          "fuel": "⛽", "gas": "⛽", "beach": "🏖️", "mountain": "⛰️", "swimming": "🏊", "pool": "🏊"}


def _is_emoji(ch):
    o = ord(ch)
    return o == 0xFE0F or o == 0x200D or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or 0x1F000 <= o <= 0x1FAFF


_emoji_font = None


def _emoji_img(ch, px):
    """The emoji as a transparent picture in full colour, drawn by the machine's emoji font. None when
    the machine has no colour emoji font: the words then simply carry no emoji rather than a broken one."""
    global _emoji_font
    try:
        from PIL import Image, ImageDraw, ImageFont
        if _emoji_font is None:
            ej = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "seguiemj.ttf"
            _emoji_font = ImageFont.truetype(str(ej), 256) if ej.is_file() else False
        if _emoji_font is False:
            return None
        img = Image.new("RGBA", (340, 340), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((42, 20), ch, font=_emoji_font, embedded_color=True)
        box = img.getbbox()
        if not box:
            return None
        img = img.crop(box)
        img.thumbnail((px, px))          # keeps its shape, never grows past the box saved for it
        return img
    except Exception:  # noqa: BLE001 - no emoji font or no picture library: captions still render
        return None


class _Font:
    """Measures text exactly as the renderer will draw it, so every word can be placed by hand: the highlighted
    word can grow without pushing its neighbours, and the heading box fits its text."""
    _cache: dict = {}

    def __init__(self, name):
        import struct
        path = Path(__file__).resolve().parent / "fonts" / FONT_FILES.get(name, FONT_FILES["Poppins ExtraBold"])
        d = path.read_bytes()
        tables = {}
        for i in range(struct.unpack(">H", d[4:6])[0]):
            tag, _, off, _ = struct.unpack(">4sIII", d[12 + 16 * i: 28 + 16 * i])
            tables[tag] = off
        self.upm = struct.unpack(">H", d[tables[b"head"] + 18: tables[b"head"] + 20])[0]
        o = tables[b"OS/2"]
        self.asc, self.desc = struct.unpack(">HH", d[o + 74: o + 78])      # what the renderer sizes the font by
        self.cap = struct.unpack(">h", d[o + 88: o + 90])[0] or int(self.upm * 0.7)
        self.path = str(path)
        self._pil = {}

    @classmethod
    def get(cls, name):
        if name not in cls._cache:
            cls._cache[name] = cls(name)
        return cls._cache[name]

    def em(self, size):
        return size * self.upm / (self.asc + self.desc)

    def width(self, text, size):
        """Pixels wide at this size. Words are measured with the caption font; any emoji in the text is
        measured with the machine's emoji font, so an emoji gets its fair space between the words."""
        try:
            from PIL import ImageFont
            if any(_is_emoji(c) for c in text):
                if "e" not in self._pil:
                    ej = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "seguiemj.ttf"
                    self._pil["e"] = ImageFont.truetype(str(ej), 200) if ej.is_file() else None
                ef = self._pil["e"]
                if ef is not None:
                    if "f" not in self._pil:
                        self._pil["f"] = ImageFont.truetype(self.path, 200)
                    w = 0
                    for part in re.split(r"([\u2600-\u27BF\u2B00-\u2BFF\U0001F000-\U0001FAFF][\uFE0F\u200D]*)", text):
                        if part:
                            w += ef.getlength(part) if _is_emoji(part[0]) else self._pil["f"].getlength(part)
                    return w * self.em(size) / 200
            if "f" not in self._pil:
                self._pil["f"] = ImageFont.truetype(self.path, 200)
            return self._pil["f"].getlength(text) * self.em(size) / 200
        except Exception:  # noqa: BLE001 - no measuring library: a fair estimate keeps clips rendering
            return len(text) * self.em(size) * 0.62

    def cap_shift(self, size):
        """How far below the anchor the middle of a capital letter sits when text is centred on a point."""
        return ((self.asc - self.desc) / 2 - self.cap / 2) * size / (self.asc + self.desc)


CAPTION_LEAD = 0.0  # measured: word stamps are within 0.15 s of the voice, so no shift is needed
def install_fonts():
    """Copy the bundled caption fonts next to the data, so captions look the same on every machine and server."""
    src = Path(__file__).resolve().parent / "fonts"
    for f in src.glob("*.ttf"):
        if not (config.FONTS_DIR / f.name).exists():
            shutil.copyfile(f, config.FONTS_DIR / f.name)


LAYOUTS = {"blur": "Full frame + blurred fill", "zoom": "Zoomed in + blurred fill", "crop": "Fill the screen (centre crop)",
           "gameplay": "Gameplay fills the screen, facecam in the corner"}


def _ts(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def _clean(text):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", re.sub(r"[{}\\]", "", str(text))).strip()


def _key(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _groups(words, per):
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= per or sum(len(x["w"]) for x in cur) + len(w["w"]) > 16
                    or w["s"] - cur[-1]["e"] > 0.45 or cur[-1]["w"][-1:] in ".?!"):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def geometry(src_w, src_h, layout):
    """Where the video sits in the 1080x1920 frame, and where hook and captions go."""
    if src_h >= src_w and layout != "crop":
        layout = "crop"  # already vertical or square: nothing to gain from a blurred fill
    if layout == "blur":
        fg_h = min(H, int(round(W * src_h / src_w / 2)) * 2)
    elif layout == "zoom":
        fg_h = 1000
    else:
        fg_h = H
    top = (H - fg_h) // 2
    if layout in ("crop", "gameplay"):
        return layout, fg_h, 300, 1380
    return layout, fg_h, max(230, top - 190), min(1640, top + fg_h + 180)


def _hook_events(hook, dur, y):
    """The heading: dark text in a white rounded box that fits it, on one line or two balanced ones."""
    f, size = _Font.get(HOOK["font"]), HOOK["size"]
    words = hook.split()
    if not words:
        return []
    lines = [" ".join(words)]
    if f.width(lines[0], size) > HOOK["max_w"] and len(words) > 1:      # two lines, split where they come out most even
        cut = min(range(1, len(words)), key=lambda i: max(f.width(" ".join(words[:i]), size), f.width(" ".join(words[i:]), size)))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    widest = max(f.width(l, size) for l in lines)
    if widest > HOOK["max_w"]:
        size = max(40, int(size * HOOK["max_w"] / widest))
        widest = max(f.width(l, size) for l in lines)
    line_h = f.em(size) * 1.16
    bw, bh = widest + 2 * HOOK["pad_x"], line_h * len(lines) + 2 * HOOK["pad_y"]
    x0, y0, r = (W - bw) / 2, y - bh / 2, min(HOOK["radius"], bh / 2)
    x1, y1 = x0 + bw, y0 + bh
    n = lambda v: f"{v:.0f}"                                                         # noqa: E731
    box = (f"m {n(x0 + r)} {n(y0)} l {n(x1 - r)} {n(y0)} b {n(x1)} {n(y0)} {n(x1)} {n(y0)} {n(x1)} {n(y0 + r)} "
           f"l {n(x1)} {n(y1 - r)} b {n(x1)} {n(y1)} {n(x1)} {n(y1)} {n(x1 - r)} {n(y1)} "
           f"l {n(x0 + r)} {n(y1)} b {n(x0)} {n(y1)} {n(x0)} {n(y1)} {n(x0)} {n(y1 - r)} "
           f"l {n(x0)} {n(y0 + r)} b {n(x0)} {n(y0)} {n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}")
    span = f"{_ts(0)},{_ts(dur)}"
    ev = [f"Dialogue: 3,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(160,0)\\c&H{HOOK['box']}&\\p1}}{box}{{\\p0}}"]
    for i, line in enumerate(lines):
        cy = y - line_h * (len(lines) - 1) / 2 + i * line_h - f.cap_shift(size)
        ev.append(f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an5\\pos({W // 2},{cy:.0f})\\fad(160,0)\\fs{size}}}{line}")
    return ev


def build_ass(words, start, end, hook, style_name, highlight, hook_y, cap_y, pace="normal", emoji=True):
    """The captions as a subtitle script, plus the emojis to paint over it: (script, overlays).
    An overlay is {"emoji", "cx", "cy", "w", "s", "e"} — a picture of that emoji, centred on (cx, cy)
    in the 1080x1920 frame, one caption em tall, on screen from second s to second e of the clip."""
    st = STYLES.get(style_name, STYLES["bounce"])
    pc = PACE.get(pace, PACE["normal"])
    words = [dict(w, s=w["s"] - CAPTION_LEAD, e=w["e"] - CAPTION_LEAD) for w in words]
    strong = {_key(h) for h in highlight if _key(h)}
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{st['size']},&H00{st['base']},&H00{st['base']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{st['outline']},0,5,0,0,0,1
Style: Hook,{HOOK['font']},{HOOK['size']},&H00{HOOK['ink']},&H00{HOOK['ink']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dur = end - start
    ev = _hook_events(_clean(hook), dur, hook_y)
    overlays = []
    f = _Font.get(st["font"])
    inside = [dict(w, w=_clean(w["w"])) for w in words if w["s"] >= start - 0.05 and w["s"] < end]
    inside = sorted((w for w in inside if w["w"]), key=lambda w: w["s"])
    for i, w in enumerate(inside[:-1]):
        w["e"] = max(w["s"], min(w["e"], inside[i + 1]["s"]))
    groups = _groups(inside, st["per"])
    for gi, g in enumerate(groups):
        g_start = max(0.0, g[0]["s"] - start)
        # the line leaves with the voice: a moment after its last word, held long enough to read,
        # never reaching into the next line and never past the end of the clip
        g_end = min(max(g[-1]["e"] + pc["tail"], g[0]["s"] + pc["hold"]),
                    groups[gi + 1][0]["s"] if gi + 1 < len(groups) else end) - start
        if g_end - g_start < 0.02:
            continue
        texts = []
        for x in g:
            t = re.sub(r"[.,;:]+$", "", x["w"])
            texts.append(t.upper() if st["upper"] else t)
        hits = []      # one related emoji above every word that means something, at most two a line
        if emoji:
            for i, x in enumerate(g):
                if _key(re.sub(r"[.,;:]+$", "", x["w"])) in EMOJIS and not any(_is_emoji(c) for c in texts[i]):
                    hits.append(i)
                    if len(hits) == 2:
                        break
        if not all(roman.drawable(t) for t in texts):
            # A script the caption font cannot draw (Japanese, Thai, Chinese...): its words cannot be measured, so
            # they are not placed one by one. The line is drawn whole and centred, in a font the system has for it.
            line = " ".join(texts)
            fs = max(44, min(int(st["size"] * 0.7), int(1500 / max(1, len(line)) * 1.6)))
            ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(g_end)},Cap,,60,60,0,,{{\\an5\\pos({W // 2},{cap_y:.0f})\\q0\\fs{fs}}}{line}")
            continue
        size = st["size"]
        gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * st["outline"] + 6) * size / st["size"]   # a space, plus room for both outlines
        total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        if total > CAP_MAX_W:                                  # a long phrase: shrink it to fit, never run off the frame
            size = max(36, int(size * CAP_MAX_W / total))
            gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * st["outline"] + 6) * size / st["size"]   # a space, plus room for both outlines
            total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        cy = cap_y - f.cap_shift(size)
        ew = f.em(size) if hits else 0                         # each emoji floats above its word, one caption em tall
        emoji_y = cy - f.em(size) * 0.40 - ew * 0.5            # centred on its word, sitting just on top of it
        x = (W - total) / 2
        p = st["pop"]
        placed = []
        for i, (w, t) in enumerate(zip(g, texts)):
            wd = f.width(t, size)
            if i in hits:      # the emoji hovers above its word, on while that word is said
                cx = x + wd / 2
                if not placed or cx - placed[-1] >= ew * 0.75:  # two emojis never sit on top of each other
                    overlays.append({"emoji": EMOJIS[_key(re.sub(r"[.,;:]+$", "", w["w"]))],
                                     "cx": cx, "cy": emoji_y, "w": ew,
                                     "s": max(g_start, w["s"] - start), "e": g_end})
                    placed.append(cx)
            p = max(104, min(st["pop"], 100 + int(2200 / max(wd, 1))))   # long words grow less, so they never touch their neighbours
            pos = f"\\an5\\pos({x + wd / 2:.0f},{cy:.0f})\\fs{size}"
            x += wd + gap
            a = max(g_start, w["s"] - start)
            b = (g[i + 1]["s"] - start) if i + 1 < len(g) else g_end
            base = st["strong"] if _key(w["w"]) in strong else st["base"]
            if a - g_start >= 0.02:                                                   # waiting to be said
                ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(a)},Cap,,0,0,0,,{{{pos}\\c&H{base}&}}{t}")
            if b - a >= 0.02:                                                         # being said: colour and a quick pop, in front
                ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{st['active']}&\\fscx94\\fscy94"
                          f"\\t(0,90,\\fscx{p}\\fscy{p})\\t(90,200,\\fscx{p - 5}\\fscy{p - 5})}}{t}")
            if g_end - b >= 0.02:                                                     # said
                ev.append(f"Dialogue: 1,{_ts(b)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}\\c&H{base}&\\fscx{p - 5}\\fscy{p - 5}"
                          f"\\t(0,90,\\fscx100\\fscy100)}}{t}")
    return head + "\n".join(ev) + "\n", overlays


PIP_W = 380            # how wide the facecam is in the 1080-wide frame
PIP_MARGIN = 26


def _filter(layout, fg_h, facecam=None):
    if layout == "gameplay" and facecam:
        # The game fills the screen, and the webcam sits in the top corner of it, so a viewer sees
        # the play and the face at the same time.
        fx, fy, fw, fh = (int(v) for v in facecam)
        if fw > 8 and fh > 8:
            pip_h = max(2, int(round(PIP_W * fh / fw)))
            return (f"[0:v]fps={config.OUT_FPS},split=2[base][fc];"
                    f"[base]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[b];"
                    f"[fc]crop={fw}:{fh}:{fx}:{fy},scale={PIP_W}:{pip_h},setsar=1[p];"
                    f"[b][p]overlay={W - PIP_W - PIP_MARGIN}:{PIP_MARGIN}[v0];")
    if layout == "crop" or (layout == "gameplay" and not facecam):
        return f"[0:v]fps={config.OUT_FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[v0];"
    return (f"[0:v]fps={config.OUT_FPS},split=2[a][b];"
            f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=6:2,"
            f"scale={W}:{H},eq=brightness=-0.14:saturation=1.15[bg];"
            f"[b]scale={W}:{fg_h}:force_original_aspect_ratio=increase,crop={W}:{fg_h}[fg];"
            f"[bg][fg]overlay=0:(H-h)/2,setsar=1[v0];")


def _hook_y(layout, hook_y, facecam=None):
    """Where the heading goes. In the gameplay layout the webcam sits in the top corner, so a heading
    across the top would run under it: it goes just below the picture instead."""
    if layout == "gameplay" and facecam and len(facecam) == 4 and facecam[2] > 8:
        return PIP_MARGIN + int(round(PIP_W * facecam[3] / facecam[2])) + 32
    return hook_y


_qsv_ok = None
RENDER_SECONDS = 600      # one clip's video encode; far beyond normal, so a frozen encoder is stopped, not waited on


def render_clip(src: Path, out_dir: Path, name: str, clip: dict, words: list, src_w: int, src_h: int) -> dict:
    """Writes <name>.mp4, <name>.jpg and <name>.ass into out_dir. Returns file names."""
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = clip["start"], clip["end"]
    layout, fg_h, hook_y, cap_y = geometry(src_w, src_h, clip.get("layout", "blur"))
    face = clip.get("facecam")
    if layout == "gameplay" and not (face and len(face) == 4):
        layout = "crop"     # no webcam found: the game fills the screen, which is still the right shape
    hook_y = _hook_y(layout, hook_y, face)
    ass, overlays = build_ass(words if clip.get("captions", True) else [], start, end, clip.get("hook", ""), clip.get("style", "bounce"),
                              clip.get("highlight_words", []), hook_y, cap_y, clip.get("pace", "normal"), clip.get("emoji", True))
    # The clip is made in a short work folder and moved into place afterwards. The caption step of ffmpeg cannot
    # open files whose full path is longer than 260 characters on Windows, which a data folder deep inside other
    # folders easily reaches. Inside the work folder every name is short and relative (a drive colon would also
    # break the filter syntax).
    work = Path(tempfile.mkdtemp(prefix="pk"))
    try:
        return _render_in(work, src, out_dir, name, start, end, layout, fg_h, ass, face=face, overlays=overlays)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _ass_at(ass: str, r: float) -> str:
    """Shifts every subtitle event back so the moment r seconds into the clip is now. A single frame
    of the clip (for a quick look while editing) then shows exactly what a viewer would see then."""
    def p(ts):
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    out = []
    for line in ass.splitlines():
        m = re.match(r"(Dialogue: \d+,)([^,]+),([^,]+)(,.*)", line)
        if m:
            a, b = p(m[2]) - r, p(m[3]) - r
            if b <= 0.02:
                continue
            line = f"{m[1]}{_ts(max(0.0, a))},{_ts(b)}{m[4]}"
        out.append(line)
    return "\n".join(out) + "\n"


def preview_frame(src: Path, clip: dict, words: list, src_w: int, src_h: int, at: float = None) -> bytes:
    """One frame of how the clip would look with these settings: a quick look while editing, not a render."""
    start, end = clip["start"], clip["end"]
    off = clip.get("src_offset", 0.0)
    local = dict(clip, start=start - off, end=end - off, hook=roman.to_roman(clip.get("hook") or ""))
    dur = max(0.1, end - start)
    if at is not None and start <= at < end:
        r = at - start
    else:
        # the moment that shows the most: a word being spoken a little way in, else the middle
        ws = [w for w in words if local["start"] <= w["s"] < local["end"]]
        pick = min(ws, key=lambda w: abs((w["s"] + w["e"]) / 2 - (local["start"] + dur * 0.4)), default=None)
        r = (pick["s"] + pick["e"]) / 2 - local["start"] if pick else dur / 2
    layout, fg_h, hook_y, cap_y = geometry(src_w, src_h, local.get("layout", "blur"))
    face = clip.get("facecam")
    if layout == "gameplay" and not (face and len(face) == 4):
        layout = "crop"     # same fallback the real render uses
    hook_y = _hook_y(layout, hook_y, face)
    ass, overlays = build_ass(words if clip.get("captions", True) else [], local["start"], local["end"], local["hook"],
                              local.get("style", "bounce"), local.get("highlight_words", []), hook_y, cap_y,
                              local.get("pace", "normal"), local.get("emoji", True))
    work = Path(tempfile.mkdtemp(prefix="pk"))
    try:
        (work / "p.ass").write_text(_ass_at(ass, r), encoding="utf-8")
        (work / "f").mkdir()
        for f in config.FONTS_DIR.glob("*.ttf"):
            shutil.copyfile(f, work / "f" / f.name)
        fc = _filter(layout, fg_h, face if layout == "gameplay" else None) + "[v0]ass=p.ass:fontsdir=f[v]"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{local['start'] + r:.2f}", "-i", str(src), "-map", "[v]",
             "-filter_complex", fc, "-frames:v", "1", "-q:v", "3", "p.jpg"], cwd=work)
        active = [o for o in overlays if o["s"] <= r < o["e"]]     # the emojis said at this very moment
        if active:
            from PIL import Image
            im = Image.open(work / "p.jpg").convert("RGBA")
            for o in active:
                t = r - o["s"]          # the same pop the video makes: small, overshoot, settled
                k = 0.7 if t < 0.09 else (1.32 if t < 0.20 else 1.0)
                img = _emoji_img(o["emoji"], max(1, int(o["w"] * k)))
                if img is not None:
                    im.alpha_composite(img, (int(o["cx"] - img.width / 2), int(o["cy"] - img.height / 2)))
            im.convert("RGB").save(work / "p.jpg", quality=90)
        return (work / "p.jpg").read_bytes()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _render_in(work: Path, src: Path, out_dir: Path, name: str, start, end, layout, fg_h, ass: str, face=None, overlays=()) -> dict:
    global _qsv_ok
    (work / f"{name}.ass").write_text(ass, encoding="utf-8")
    (work / "f").mkdir()
    for f in config.FONTS_DIR.glob("*.ttf"):
        shutil.copyfile(f, work / "f" / f.name)
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", str(src)]
    # Each emoji is painted at three sizes and the render holds them in turn: small, then too big, then settled —
    # the same pop the words make, so the picture springs in with the word it matches.
    painted = []      # (input number, window to show the picture for, where, its picture)
    i = 0
    for o in overlays:
        sizes = [("s", 0.7, o["s"], o["s"] + 0.09),          # springing up
                 ("b", 1.32, o["s"] + 0.08, o["s"] + 0.20),  # overshoot
                 ("f", 1.0, o["s"] + 0.19, o["e"])]          # settled, until the line goes
        for tag, k, a, b in sizes:
            if b <= a:
                continue
            img = _emoji_img(o["emoji"], max(1, int(o["w"] * k)))
            if img is None:
                break
            img.save(work / f"e{i}.png")
            cmd += ["-i", f"e{i}.png"]     # one frame each, held for the whole clip; enable shows it in its window
            painted.append((i, o, img, a, b))
            i += 1
    fc = _filter(layout, fg_h, face) + f"[v0]ass={name}.ass:fontsdir=f" + ("[va]" if painted else "[v]")
    prev = "va"
    for k, (i, o, img, a, b) in enumerate(painted):
        x, y = o["cx"] - img.width / 2, o["cy"] - img.height / 2
        out = "v" if k == len(painted) - 1 else f"vb{i}"
        fc += f";[{prev}][{i + 1}:v]overlay={x:.0f}:{y:.0f}:enable='between(t,{a:.2f},{b:.2f})'[{out}]"
        prev = out
    base = cmd + ["-filter_complex", fc, "-map", "[v]", "-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                  "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", "-pix_fmt"]
    encoders = []
    if _qsv_ok is not False:
        encoders.append(("qsv", ["nv12", "-c:v", "h264_qsv", "-global_quality", "23", "-preset", "fast"]))
    encoders.append(("x264", ["yuv420p", "-c:v", "libx264", "-crf", "21", "-preset", "veryfast"]))
    err = None
    for label, enc in encoders:
        p = subprocess.run(base + enc + [f"{name}.mp4"], cwd=work, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=RENDER_SECONDS)
        if p.returncode == 0:
            if label == "qsv":
                _qsv_ok = True
            break
        err = p.stderr[-1200:]
        if label == "qsv":
            _qsv_ok = False
    else:
        raise RuntimeError(f"Render failed: {err}")
    cover_t = min(1.2, (end - start) / 2)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{cover_t:.2f}", "-i", f"{name}.mp4", "-frames:v", "1",
         "-q:v", "3", f"{name}.jpg"], cwd=work)
    for ext in ("mp4", "jpg", "ass"):
        shutil.move(str(work / f"{name}.{ext}"), str(out_dir / f"{name}.{ext}"))
    return {"file": f"{name}.mp4", "cover": f"{name}.jpg", "layout": layout}
