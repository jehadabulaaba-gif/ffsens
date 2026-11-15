#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FF Sens Lab - محلل حساسية الهيدشوت لفري فاير (تحليل فيديو بعد اللعب فقط)

الاستخدام:
  python ffsens.py analyze v1.mp4 v2.mp4 --sens 59 --scope general
  python ffsens.py report --sens 59 --scope general
  python ffsens.py reset

الفكرة:
  1) نقدّر حركة الكاميرا في كل إطار (Phase Correlation).
  2) نكشف العدو من شريط الصحة الأحمر ونقدّر موضع الرأس.
  3) نكشف "السحبات" (flicks) ونقيس: هل تجاوزت الهدف أم قصّرت عنه؟
  4) نجمع كل الفيديوهات ونحسب حساسية مقترحة + هل البيانات كافية أم لا.
"""
import argparse
import datetime
import json
import math
import os
import sys

import cv2
import numpy as np

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "ffsens_data.json")

PROC_W = 480          # عرض المعالجة (تصغير للسرعة)
MAX_SENS = 100.0      # أقصى قيمة للسلايدر
FLICK_V = 0.9         # سرعة بداية السحبة (ارتفاع شاشة / ثانية)
HOLD_V = 0.35         # سرعة اعتبار الحركة هادئة
SETTLE_S = 0.35       # زمن الاستقرار بعد السحبة
MIN_SECONDS = 300     # أقل مدة لعب كافية (5 دقائق)
MIN_EVENTS = 40       # أقل عدد سحبات صالحة
MAX_CI_WIDTH = 0.25   # أقصى عرض لمجال الثقة


# ---------------------------------------------------------------- التخزين
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("sessions"), list):
                return d
        except (OSError, json.JSONDecodeError) as e:
            bak = DATA_FILE + ".corrupt"
            try:
                os.replace(DATA_FILE, bak)
            except OSError:
                pass
            print(f"تحذير: ملف البيانات تالف ({e}). نُقل إلى {bak}")
    return {"sessions": []}


def save_data(d):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)  # كتابة آمنة


# ---------------------------------------------------------------- كشف العدو
def detect_enemy(small, box, cx_s, cy_s, head_off):
    """يبحث عن شريط صحة أحمر أفقي ويرجع موضع الرأس التقريبي (بإحداثيات المعالجة)."""
    x0, y0, x1, y1 = box
    crop = small[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    m = cv2.bitwise_or(cv2.inRange(hsv, (0, 150, 120), (8, 255, 255)),
                       cv2.inRange(hsv, (172, 150, 120), (180, 255, 255)))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((1, 5), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, best_d = None, 1e9
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w < 6 or w > 140 or h < 2 or h > 16 or w / h < 3.5:
            continue
        if cv2.countNonZero(m[y:y + h, x:x + w]) / float(w * h) < 0.5:
            continue
        hx = x0 + x + w / 2.0
        hy = y0 + y + h + head_off * w
        d = math.hypot(hx - cx_s, hy - cy_s)
        if d < best_d:
            best, best_d = (hx, hy), d
    return best


# ---------------------------------------------------------------- قراءة الفيديو
def extract_tracks(path, args):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"تعذر فتح الفيديو: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps < 5 or fps > 240:
        fps = 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if W <= 0 or H <= 0:
        raise RuntimeError("أبعاد الفيديو غير صالحة")
    if H > W:
        print("  تنبيه: الفيديو عمودي. سجّل اللعبة بالوضع الأفقي.")
    s = W / float(PROC_W)
    ph = int(round(H / s))
    cx_s, cy_s = PROC_W * args.cx, ph * args.cy

    mbox = (int(PROC_W * 0.2), int(ph * 0.08), int(PROC_W * 0.8), int(ph * 0.65))
    ebox = (int(PROC_W * 0.1), int(ph * 0.05), int(PROC_W * 0.9), int(ph * 0.80))
    rw, rh = mbox[2] - mbox[0], mbox[3] - mbox[1]
    win = cv2.createHanningWindow((rw, rh), cv2.CV_32F)

    cam_x, cam_y, ex, ey = [], [], [], []
    prev = None
    limit = int(args.max_minutes * 60 * fps) if args.max_minutes else None
    n = 0
    while True:
        ok, fr = cap.read()
        if not ok or (limit and n >= limit):
            break
        n += 1
        small = cv2.resize(fr, (PROC_W, ph), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        roi = gray[mbox[1]:mbox[3], mbox[0]:mbox[2]].astype(np.float32)

        if prev is None:
            cam_x.append(np.nan); cam_y.append(np.nan)
        else:
            (dx, dy), resp = cv2.phaseCorrelate(prev, roi, win)
            if resp < 0.03 or abs(dx) > rw * 0.4 or abs(dy) > rh * 0.4:
                cam_x.append(np.nan); cam_y.append(np.nan)
            else:
                cam_x.append(-dx * s)   # حركة الكاميرا = عكس حركة المشهد
                cam_y.append(-dy * s)
        prev = roi

        t = detect_enemy(small, ebox, cx_s, cy_s, args.head_offset)
        if t is None:
            ex.append(np.nan); ey.append(np.nan)
        else:
            ex.append((t[0] - cx_s) * s)
            ey.append((t[1] - cy_s) * s)
    cap.release()
    return (np.array(cam_x), np.array(cam_y), np.array(ex), np.array(ey),
            fps, H, n / fps)


# ---------------------------------------------------------------- تحليل السحبات
def last_valid(arr, lo, hi):
    seg = arr[max(lo, 0):hi + 1]
    idx = np.where(~np.isnan(seg))[0]
    return None if len(idx) == 0 else float(seg[idx[-1]])


def analyze_events(cam_x, cam_y, ex, ey, fps, H):
    cxn, cyn = np.nan_to_num(cam_x), np.nan_to_num(cam_y)
    v = np.hypot(cxn, cyn) * fps / H
    n = len(v)
    gap = max(2, int(0.05 * fps))
    events, i = [], 0
    while i < n:
        if v[i] > FLICK_V:
            a, quiet, j = i, 0, i
            while j < n and quiet < gap:
                quiet = quiet + 1 if v[j] < HOLD_V else 0
                j += 1
            events.append((a, max(a, j - quiet - 1)))
            i = j
        else:
            i += 1

    rx, ry, finals, corrs = [], [], [], []
    valid = 0
    look = int(0.3 * fps)
    settle = int(SETTLE_S * fps)
    for a, b in events:
        if b - a < 1:
            continue
        s_end = min(n - 1, b + settle)
        tot_x = float(cxn[a:s_end + 1].sum())
        tot_y = float(cyn[a:s_end + 1].sum())
        if math.hypot(tot_x, tot_y) < 0.04 * H:
            continue
        e0x, e0y = last_valid(ex, a - look, a), last_valid(ey, a - look, a)
        got = False
        if e0x is not None and abs(e0x) > 0.05 * H:
            r = tot_x / e0x
            if -1 <= r <= 4:
                rx.append(r); got = True
        if e0y is not None and abs(e0y) > 0.04 * H:
            r = tot_y / e0y
            if -1 <= r <= 4:
                ry.append(r); got = True
        if not got:
            continue
        valid += 1
        fx, fy = last_valid(ex, b, s_end), last_valid(ey, b, s_end)
        if fx is not None and fy is not None:
            finals.append(math.hypot(fx, fy) / H)
        seg = cxn[b + 1:s_end + 1]
        big = seg[np.abs(seg) > 0.25 * H / fps]
        corrs.append(int(np.sum(np.diff(np.sign(big)) != 0)) if len(big) > 1 else 0)

    vis = ~np.isnan(ex)
    on_head = None
    if vis.sum() > 30:
        on_head = float(np.mean((np.abs(ex[vis]) < 0.035 * H) & (np.abs(ey[vis]) < 0.035 * H)))

    hold = (v < HOLD_V) & vis
    pair = hold[1:] & hold[:-1]
    d = np.diff(cxn)[pair]
    jitter = float(np.std(d) / H * 1000) if len(d) > 30 else None

    return {"rx": rx, "ry": ry, "finals": finals, "corrs": corrs,
            "valid": valid, "flicks": len(events),
            "on_head": on_head, "jitter": jitter}


# ---------------------------------------------------------------- التجميع والتوصية
def boot_ci(x):
    rng = np.random.default_rng(0)
    arr = np.array(x)
    meds = [np.median(rng.choice(arr, len(arr))) for _ in range(300)]
    lo, hi = np.percentile(meds, [5, 95])
    return float(lo), float(hi)


def build_report(sessions, scope, sens):
    rx, ry, fin, corr, jit, oh = [], [], [], [], [], []
    dur, valid = 0.0, 0
    for s in sessions:
        if s["scope"] != scope or s["sens"] <= 0:
            continue
        k = sens / s["sens"]  # تقريب خطي: الكسب يتناسب مع الحساسية
        rx += [r * k for r in s["rx"]]
        ry += [r * k for r in s["ry"]]
        fin += s["finals"]; corr += s["corrs"]
        if s["jitter"] is not None: jit.append(s["jitter"])
        if s["on_head"] is not None: oh.append(s["on_head"])
        dur += s["duration"]; valid += s["valid"]

    allr = rx + ry
    rep = {"duration": dur, "valid": valid, "sens": sens, "scope": scope}
    if len(allr) < 5:
        rep.update(enough=False, gain=None,
                   reason="عدد السحبات الصالحة قليل جداً (لم يُكتشف عدو كفاية أو لا توجد سحبات).")
        return rep

    g = float(np.median(allr))
    lo, hi = boot_ci(allr)
    rate = valid / (dur / 60.0) if dur > 0 else 0
    missing = []
    if dur < MIN_SECONDS:
        missing.append(f"مدة اللعب {dur / 60:.1f} د من {MIN_SECONDS // 60} د")
    if valid < MIN_EVENTS:
        need = MIN_EVENTS - valid
        extra = f" (~{need / rate:.1f} د إضافية)" if rate > 0 else ""
        missing.append(f"سحبات صالحة {valid} من {MIN_EVENTS}{extra}")
    if hi - lo > MAX_CI_WIDTH:
        missing.append(f"النتيجة غير مستقرة (مجال الثقة {lo:.2f}–{hi:.2f})")

    step = min(1.15, max(0.85, g ** -0.5))   # نصف خطوة تصحيح لتجنب التذبذب
    jv = float(np.mean(jit)) if jit else None
    if jv is not None and jv > 6.0 and g >= 0.95:
        step *= 0.97
    new = round(min(MAX_SENS, max(1.0, sens * step)), 1)

    rep.update(
        enough=not missing, missing=missing, gain=g, ci=(lo, hi),
        gain_x=float(np.median(rx)) if rx else None,
        gain_y=float(np.median(ry)) if ry else None,
        over=float(np.mean(np.array(allr) > 1.15)),
        under=float(np.mean(np.array(allr) < 0.85)),
        final_err=float(np.median(fin)) if fin else None,
        corrections=float(np.mean(corr)) if corr else None,
        jitter=jv, on_head=float(np.mean(oh)) if oh else None,
        suggested=new,
        keep=(0.9 <= g <= 1.1),
    )
    return rep


def print_report(rep):
    line = "=" * 46
    print(f"\n{line}\nالنتيجة - {rep['scope']} | الحساسية الحالية: {rep['sens']}\n{line}")
    print(f"مدة التحليل: {rep['duration'] / 60:.1f} د | سحبات صالحة: {rep['valid']}")
    if rep.get("gain") is None:
        print("✗ لا توجد بيانات كافية:", rep["reason"])
        return
    print(f"نسبة الوصول للهدف (1.0 = مثالي): {rep['gain']:.2f}  "
          f"[{rep['ci'][0]:.2f} – {rep['ci'][1]:.2f}]")
    if rep["gain_x"] is not None and rep["gain_y"] is not None:
        print(f"  أفقي: {rep['gain_x']:.2f} | رأسي: {rep['gain_y']:.2f}")
    print(f"تجاوز الهدف: {rep['over'] * 100:.0f}% | تقصير: {rep['under'] * 100:.0f}%")
    if rep["final_err"] is not None:
        print(f"متوسط الخطأ النهائي: {rep['final_err'] * 100:.1f}% من ارتفاع الشاشة")
    if rep["corrections"] is not None:
        print(f"تصحيحات صغيرة بعد السحبة: {rep['corrections']:.1f}")
    if rep["jitter"] is not None:
        print(f"اهتزاز اليد: {rep['jitter']:.1f}")
    if rep["on_head"] is not None:
        print(f"نسبة بقاء المؤشر على الرأس (تقريبية): {rep['on_head'] * 100:.0f}%")
    print("-" * 46)
    if rep["enough"]:
        print("✓ البيانات كافية.")
    else:
        print("✗ البيانات غير كافية بعد:")
        for m in rep["missing"]:
            print("   •", m)
    if rep["keep"]:
        print(f"التوصية: أبقِ الحساسية {rep['sens']} (قريبة من المثالي).")
    else:
        way = "خفّض" if rep["suggested"] < rep["sens"] else "ارفع"
        print(f"التوصية: {way} من {rep['sens']} إلى {rep['suggested']}")
        print("جرّبها ثم سجّل جلسة جديدة بالقيمة الجديدة وأعد التحليل.")
    if not rep["enough"]:
        print("(التوصية مبدئية فقط حتى تكتمل البيانات)")


# ---------------------------------------------------------------- معايرة الإصبع (إظهار اللمسات)
def _finger_candidates(small, x_min, rmin=None, rmax=None):
    """دوائر بيضاء/رمادية فاتحة (مؤشر اللمس) في النصف الأيمن."""
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (0, 0, 190), (180, 60, 255))
    m[:, :x_min] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ph = small.shape[0]
    lo = rmin if rmin else 0.015 * ph
    hi = rmax if rmax else 0.08 * ph
    out = []
    for c in cnts:
        A, P = cv2.contourArea(c), cv2.arcLength(c, True)
        if P == 0 or A == 0:
            continue
        r = math.sqrt(A / math.pi)
        if not (lo <= r <= hi):
            continue
        if 4 * math.pi * A / (P * P) < 0.7:
            continue
        M = cv2.moments(c)
        out.append((M["m10"] / M["m00"], M["m01"] / M["m00"]))
    return out


def extract_cam_and_finger(path, max_minutes=0, btn_pct=None):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"تعذر فتح الفيديو: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps < 5 or fps > 240:
        fps = 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    s = W / float(PROC_W)
    ph = int(round(H / s))
    mbox = (int(PROC_W * 0.2), int(ph * 0.08), int(PROC_W * 0.8), int(ph * 0.65))
    rw, rh = mbox[2] - mbox[0], mbox[3] - mbox[1]
    win = cv2.createHanningWindow((rw, rh), cv2.CV_32F)
    limit = int(max_minutes * 60 * fps) if max_minutes else None
    rmin = rmax = None
    if btn_pct:   # حجم زر النار (% من ارتفاع الشاشة) يضيّق البحث عن مؤشر اللمس
        r = btn_pct / 100.0 * ph / 2.0
        rmin, rmax = 0.4 * r, 1.8 * r

    cam_x, cam_y, cands = [], [], []
    prev, n = None, 0
    while True:
        ok, fr = cap.read()
        if not ok or (limit and n >= limit):
            break
        n += 1
        small = cv2.resize(fr, (PROC_W, ph), interpolation=cv2.INTER_AREA)
        roi = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)[mbox[1]:mbox[3], mbox[0]:mbox[2]].astype(np.float32)
        if prev is None:
            cam_x.append(np.nan); cam_y.append(np.nan)
        else:
            (dx, dy), resp = cv2.phaseCorrelate(prev, roi, win)
            if resp < 0.03 or abs(dx) > rw * 0.4 or abs(dy) > rh * 0.4:
                cam_x.append(np.nan); cam_y.append(np.nan)
            else:
                cam_x.append(-dx * s); cam_y.append(-dy * s)
        prev = roi
        cands.append(_finger_candidates(small, PROC_W // 2, rmin, rmax))
    cap.release()

    nfr = len(cands)
    cnt = {}
    for lst in cands:
        for x, y in lst:
            k = (int(x // 8), int(y // 8))
            cnt[k] = cnt.get(k, 0) + 1
    static = {k for k, v in cnt.items() if v > 0.4 * nfr}   # أزرار ثابتة في الواجهة
    fx, fy = np.full(nfr, np.nan), np.full(nfr, np.nan)
    last = None
    for i, lst in enumerate(cands):
        lst = [p for p in lst if (int(p[0] // 8), int(p[1] // 8)) not in static]
        if not lst:
            last = None
            continue
        p = lst[0] if last is None else min(lst, key=lambda q: math.hypot(q[0] - last[0], q[1] - last[1]))
        fx[i], fy[i] = p[0] * s, p[1] * s
        last = p
    return np.array(cam_x), np.array(cam_y), fx, fy, fps, H, n / fps


def compute_gain(cam_x, cam_y, fx, fy, fps, H):
    """نسبة حركة الكاميرا (بكسل) إلى حركة الإصبع (بكسل) على نوافذ 0.2 ثانية."""
    n = min(len(cam_x), len(fx))
    fdx, fdy = np.diff(fx[:n]), np.diff(fy[:n])
    jump = np.hypot(fdx, fdy) > 0.15 * H           # لمسة جديدة وليست سحبة
    fdx[jump] = np.nan; fdy[jump] = np.nan
    cx, cy = np.nan_to_num(cam_x[1:n]), np.nan_to_num(cam_y[1:n])
    w = max(2, int(0.2 * fps))
    FX, FY, CX, CY, spd = [], [], [], [], []
    for a in range(0, len(fdx) - w, w):
        seg = fdx[a:a + w]
        if np.isnan(seg).sum() > 0.2 * w:
            continue
        fxs, fys = float(np.nansum(fdx[a:a + w])), float(np.nansum(fdy[a:a + w]))
        if math.hypot(fxs, fys) < 0.03 * H:
            continue
        FX.append(fxs); FY.append(fys)
        CX.append(float(cx[a:a + w].sum())); CY.append(float(cy[a:a + w].sum()))
        spd.append(math.hypot(fxs, fys) / (w / fps))
    if len(FX) < 5:
        return None
    FX, FY, CX, CY = map(np.array, (FX, FY, CX, CY))
    kx = float(np.sum(CX * FX) / np.sum(FX * FX))
    ky = float(np.sum(CY * FY) / np.sum(FY * FY))
    return {"kx": kx, "ky": ky, "k": (abs(kx) + abs(ky)) / 2, "windows": len(FX),
            "flick_speed": float(np.percentile(spd, 80))}


def cmd_calibrate(args):
    try:
        prof = load_data().get("profile", {})
        btn = args.button_size or prof.get("button_pct")
        cx, cy, fx, fy, fps, H, dur = extract_cam_and_finger(args.video, args.max_minutes, btn)
    except RuntimeError as e:
        sys.exit(str(e))
    det = float(np.mean(~np.isnan(fx))) if len(fx) else 0.0
    print(f"ظهور مؤشر الإصبع في {det * 100:.1f}% من الإطارات")
    if det < 0.02:
        print("لم أجد مؤشر اللمس. فعّل 'إظهار اللمسات' من خيارات المطوّر وأعد التسجيل،")
        print("وإن كان مفعّلاً أرسل لي لقطة شاشة لشكل المؤشر عندك لأضبط الكاشف.")
        return
    res = compute_gain(cx, cy, fx, fy, fps, H)
    if res is None:
        print("بيانات السحب غير كافية. اسحب أكثر (حوالي 30 ثانية سحب متواصل).")
        return
    print(f"نوافذ سحب مستخدمة: {res['windows']}")
    print(f"بكسل حركة الكاميرا لكل بكسل حركة إصبع: {res['k']:.3f} "
          f"(أفقي {res['kx']:.3f} | رأسي {res['ky']:.3f})")
    print(f"سرعة سحبك المعتادة: {res['flick_speed']:.0f} بكسل/ثانية")
    if res["windows"] < 15:
        print("تحذير: النتيجة ضعيفة، سجّل مدة أطول.")
    data = load_data()
    data.setdefault("calib", []).append(
        dict(res, sens=args.sens, scope=args.scope,
             date=datetime.datetime.now().isoformat(timespec="seconds")))
    save_data(data)
    print("تم الحفظ. كرر بحساسية مختلفة ثم نفّذ: plan")


def cmd_setup(_args):
    """أسئلة أولية عن جهازك ولعبتك تُحفظ وتُستخدم في كل تحليل."""
    d = load_data()
    prof = d.get("profile", {})
    print("أجب عن الأسئلة (Enter لإبقاء القيمة السابقة):")
    def ask(q, key, cast=float):
        old = prof.get(key)
        try:
            raw = input(f"{q} [{old if old is not None else '-'}]: ").strip()
        except EOFError:
            raw = ""
        if raw:
            try:
                prof[key] = cast(raw)
            except ValueError:
                print("  قيمة غير صالحة، تم التجاهل.")
    ask("اسم الجهاز", "device", str)
    ask("حجم زر النار كنسبة من ارتفاع الشاشة % (مثال: 14)", "button_pct")
    ask("حساسيتك العامة الحالية (1-100)", "sens_general")
    ask("حساسية الريد دوت", "sens_reddot")
    ask("حساسية 2x", "sens_2x")
    ask("حساسية 4x", "sens_4x")
    ask("حساسية AWM", "sens_awm")
    ask("نمط اللعب (مثلاً: تحكم كامل)", "mode", str)
    d["profile"] = prof
    save_data(d)
    print("تم الحفظ.")


def cmd_plan(args):
    data = load_data()
    by = {}
    for c in data.get("calib", []):
        if c["scope"] == args.scope:
            by.setdefault(c["sens"], []).append(c)
    xs = sorted(by)
    if len(xs) < 2:
        print("أحتاج معايرتين على الأقل بحساسيتين مختلفتين (مثلاً 50 و 70) في نفس النمط.")
        return
    ys = [float(np.mean([c["k"] for c in by[x]])) for x in xs]
    a, b = np.polyfit(xs, ys, 1)
    if a <= 0:
        print("المعايرة غير منطقية (الحساسية الأعلى لم تعطِ كاميرا أسرع). أعد التسجيل.")
        return
    speed = float(np.mean([c["flick_speed"] for x in xs for c in by[x]]))
    k_cur = a * args.sens + b
    print(f"\nالنمط: {args.scope}")
    print(f"كل نقطة حساسية = {a:.4f} بكسل كاميرا لكل بكسل إصبع "
          f"(≈ {a / k_cur * 100:.1f}% من سرعتك الحالية)")
    print(f"بسرعة سحبك المعتادة: كل نقطة ≈ {a * speed:.0f} بكسل/ثانية إضافية")
    rep = build_report(data["sessions"], args.scope, args.sens)
    g = rep.get("gain")
    if g is None:
        print("\nلا توجد جلسات تحليل كافية لحساب التجاوز/التقصير. نفّذ analyze على فيديوهات قتال.")
        return
    k_target = min(1.25, max(0.75, 1.0 / g)) * k_cur
    new = round(min(MAX_SENS, max(1.0, (k_target - b) / a)), 1)
    print(f"\nنسبة وصولك للهدف الآن: {g:.2f} (1.0 = مثالي)")
    print(f"الحساسية الموصى بها: {new}  (الفرق {new - args.sens:+.1f} نقطة)")
    if not rep.get("enough"):
        print("تنبيه: بيانات التحليل غير كافية بعد:", "؛ ".join(rep.get("missing", [])))


# ---------------------------------------------------------------- الأوامر
def cmd_analyze(args):
    data = load_data()
    for path in args.videos:
        print(f"\nتحليل: {path}")
        try:
            cx, cy, ex, ey, fps, H, dur = extract_tracks(path, args)
        except RuntimeError as e:
            print("  خطأ:", e)
            continue
        res = analyze_events(cx, cy, ex, ey, fps, H)
        res.update(file=os.path.basename(path), sens=args.sens, scope=args.scope,
                   duration=dur, date=datetime.datetime.now().isoformat(timespec="seconds"))
        print(f"  {dur / 60:.1f} د | سحبات: {res['flicks']} | صالحة: {res['valid']}")
        data["sessions"].append(res)
    save_data(data)
    print_report(build_report(data["sessions"], args.scope, args.sens))


def cmd_report(args):
    print_report(build_report(load_data()["sessions"], args.scope, args.sens))


def cmd_reset(_args):
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    print("تم مسح كل الجلسات.")


def main():
    p = argparse.ArgumentParser(description="FF Sens Lab")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--sens", type=float, required=True, help="حساسيتك الحالية (1-100)")
        sp.add_argument("--scope", default="general",
                        help="general / reddot / 2x / 4x / awm")

    a = sub.add_parser("analyze")
    a.add_argument("videos", nargs="+")
    common(a)
    a.add_argument("--cx", type=float, default=0.5, help="موضع المؤشر أفقياً (0-1)")
    a.add_argument("--cy", type=float, default=0.5, help="موضع المؤشر رأسياً (0-1)")
    a.add_argument("--head-offset", type=float, default=0.7,
                   help="بُعد الرأس تحت شريط الصحة كنسبة من عرضه")
    a.add_argument("--max-minutes", type=float, default=0, help="حد أقصى لمدة التحليل")
    a.set_defaults(fn=cmd_analyze)

    r = sub.add_parser("report")
    common(r)
    r.set_defaults(fn=cmd_report)

    c = sub.add_parser("calibrate")
    c.add_argument("video")
    common(c)
    c.add_argument("--max-minutes", type=float, default=0)
    c.add_argument("--button-size", type=float, default=0,
                   help="قطر زر النار كنسبة % من ارتفاع الشاشة")
    c.set_defaults(fn=cmd_calibrate)

    st = sub.add_parser("setup")
    st.set_defaults(fn=cmd_setup)

    pl = sub.add_parser("plan")
    common(pl)
    pl.set_defaults(fn=cmd_plan)

    z = sub.add_parser("reset")
    z.set_defaults(fn=cmd_reset)

    args = p.parse_args()
    if hasattr(args, "sens") and not (0 < args.sens <= MAX_SENS):
        sys.exit(f"الحساسية يجب أن تكون بين 1 و {int(MAX_SENS)}")
    args.fn(args)


if __name__ == "__main__":
    main()
