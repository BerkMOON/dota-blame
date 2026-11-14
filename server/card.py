# -*- coding: utf-8 -*-
"""分享卡片渲染（Pillow）。输出 1080x1500 PNG 字节流。"""

import io
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

# 中文字体候选：macOS -> Linux(Noto/WQY) -> DejaVu
FONT_BOLD = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_REGULAR = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

_FONT_CACHE = {}


def get_font(size, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    env = os.environ.get("DOTA_BLAME_FONT")
    cands = ([env] if env else []) + (FONT_BOLD if bold else FONT_REGULAR)
    for path in cands:
        if path and os.path.exists(path):
            try:
                f = ImageFont.truetype(path, size)
                _FONT_CACHE[key] = f
                return f
            except Exception:  # noqa: BLE001
                continue
    f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def _tw(draw, text, font):
    try:
        return draw.textlength(text, font=font)
    except Exception:  # noqa: BLE001
        return len(text) * 20


def ellipsis(draw, text, font, max_w):
    if _tw(draw, text, font) <= max_w:
        return text
    out = text
    while out and _tw(draw, out + "…", font) > max_w:
        out = out[:-1]
    return out + "…"


BG_TOP = (15, 16, 32)
BG_BOTTOM = (26, 16, 40)
ACCENT = (255, 92, 51)
GOLD = (255, 209, 102)
WHITE = (245, 245, 250)
MUTED = (155, 155, 176)
DIM = (110, 110, 132)
BAR_BG = (38, 38, 58)

W, H = 1080, 1500
PAD = 64


def make_card(payload):
    """返回 PNG 字节流"""
    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)

    # 背景渐变
    for y in range(H):
        t = y / H
        c = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=c)

    # 顶部强调条
    draw.rectangle([0, 0, W, 10], fill=ACCENT)

    info = payload.get("info") or {}
    players = payload.get("players") or []

    draw.text((PAD, 56), "DOTA2 分锅判决书", font=get_font(62, True), fill=WHITE)
    draw.text((PAD, 148), "%s · %s" % (info.get("mode", ""), info.get("duration", "")),
              font=get_font(28), fill=MUTED)
    draw.text((PAD, 190), "对局 %s · %s" % (payload.get("match_id"), info.get("start", "")),
              font=get_font(26), fill=DIM)

    # 结果胶囊
    win = str(info.get("result", "")).endswith("获胜")
    color = (82, 196, 26) if win else (255, 77, 79)
    label = "%s · %s" % (info.get("score", ""), info.get("result", ""))
    f_label = get_font(30, True)
    fw = _tw(draw, label, f_label)
    draw.rounded_rectangle([PAD, 236, PAD + fw + 48, 236 + 58], radius=29, fill=color)
    draw.text((PAD + 24, 247), label, font=f_label, fill=(255, 255, 255))

    # 锅榜标题
    y = 330
    draw.text((PAD, y), "锅榜", font=get_font(40, True), fill=WHITE)
    draw.text((PAD + 118, y + 12), "背锅占比越高，越该被骂",
              font=get_font(24), fill=DIM)
    y += 78

    f_name = get_font(38, True)
    f_meta = get_font(26)
    f_tag = get_font(22)
    f_pct = get_font(40, True)

    for i, p in enumerate(players):
        row_y = y + i * 150
        rank = p.get("rank", i + 1)
        # 名次圆
        cx, cy = PAD + 34, row_y + 46
        rcol = ACCENT if rank == 1 else (58, 58, 80)
        draw.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill=rcol)
        draw.text((cx, cy), str(rank), font=get_font(32, True), fill=WHITE, anchor="mm")

        name = p.get("name", "")
        if p.get("is_me"):
            name += "（你）"
        draw.text((PAD + 90, row_y + 8), ellipsis(draw, name, f_name, 430),
                  font=f_name, fill=WHITE)

        meta = "%s · %s号位 · %s" % (p.get("hero_cn", ""), p.get("pos", "?"), p.get("kda", ""))
        draw.text((PAD + 90, row_y + 62), ellipsis(draw, meta, f_meta, 430),
                  font=f_meta, fill=MUTED)

        tags = "、".join((p.get("tags") or [])[:3])
        draw.text((PAD + 90, row_y + 98), ellipsis(draw, tags, f_tag, 430),
                  font=f_tag, fill=(255, 140, 90))

        # 占比条
        bx, by, bw, bh = PAD + 520, row_y + 52, 270, 18
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2, fill=BAR_BG)
        frac = min(1.0, float(p.get("share") or 0) / 30.0)
        fill_w = int(bw * frac)
        if fill_w > bh:
            draw.rounded_rectangle([bx, by, bx + fill_w, by + bh], radius=bh // 2, fill=ACCENT)
        draw.text((PAD + 940, row_y + 30), "%.1f%%" % float(p.get("share") or 0),
                  font=f_pct, fill=GOLD, anchor="ra")

    # 底部信息
    y = 1205
    draw.line([PAD, y, W - PAD, y], fill=(46, 46, 64), width=2)
    y += 28

    f_small = get_font(25)
    suspect = payload.get("suspect")
    if suspect:
        line = "野区嫌疑人：%s（%s）· 野怪 %d 只 · 参团率 %.0f%%" % (
            suspect.get("name", ""), suspect.get("hero_cn", ""),
            suspect.get("neutral_kills") or 0, suspect.get("part") or 0)
        draw.text((PAD, y), ellipsis(draw, line, f_small, W - 2 * PAD), font=f_small, fill=MUTED)
        y += 42

    crash = payload.get("crash")
    if crash and crash.get("marks"):
        marks = " → ".join("%d分%s" % (m["minute"], m["label"]) for m in crash["marks"])
        line = "崩盘：%s" % marks
        draw.text((PAD, y), ellipsis(draw, line, f_small, W - 2 * PAD), font=f_small, fill=MUTED)
        y += 42

    draw.text((PAD, H - 76), "数据来源 OpenDota · 分锅仅供娱乐，请文明互喷",
              font=f_small, fill=DIM)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    draw.text((W - PAD, H - 76), stamp, font=f_small, fill=DIM, anchor="ra")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
