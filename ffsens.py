#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FF Sens Lab: post-match Free Fire sensitivity analysis and recommendations."""
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

PROC_W = 480
MAX_SENS = 100.0
FLICK_V = 0.9
HOLD_V = 0.35
SETTLE_S = 0.35
MIN_SECONDS = 300
MIN_EVENTS = 40
MAX_CI_WIDTH = 0.25
SENSITIVITY_SCOPES = ("general", "reddot", "2x", "4x", "awm")


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("sessions"), list):
                return data
        except (OSError, json.JSONDecodeError) as error:
            backup = DATA_FILE + ".corrupt"
            try:
                os.replace(DATA_FILE, backup)
            except OSError:
                pass
            print(f"تحذير: ملف البيانات تالف ({error}). نُقل إلى {backup}")
    return {"sessions": [], "profile": {}}


def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def detect_enemy(small, box, cx_s, cy_s, head_off):
    """Approximate a target location from a red health bar in a video frame."""
    x0, y0, x1, y1 = box
    crop = small[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.bitwise_or(cv2.inRange(hsv, (0, 150, 120), (8, 255, 255)),
                          cv2.inRange(hsv, (172, 150, 120), (180, 255, 255)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((1, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, best_distance = None, 1e9
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 6 or w > 140 or h < 2 or h > 16 or w / h < 3.5:
            continue
        if cv2.countNonZero(mask[y:y + h, x:x + w]) / float(w * h) < 0.5:
            continue
        hx = x0 + x + w / 2.0
        hy = y0 + y + h + head_off * w
        distance = math.hypot(hx - cx_s, hy - cy_s)
        if distance < best_distance:
            best, best_distance = (hx, hy), distance
    return best


def extract_tracks(path, args):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"تعذر فتح الفيديو: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps < 5 or fps > 240:
        fps = 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError("أبعاد الفيديو غير صالحة")
    if height > width:
        print("تنبيه: الفيديو عمودي. يُفضّل تسجيل اللعب بالوضع الأفقي.")
    scale = width / float(PROC_W)
    processed_h = int(round(height / scale))
    cx_s, cy_s = PROC_W * args.cx, processed_h * args.cy
    motion_box = (int(PROC_W * 0.2), int(processed_h * 0.08),
                  int(PROC_W * 0.8), int(processed_h * 0.65))
    enemy_box = (int(PROC_W * 0.1), int(processed_h * 0.05),
                 int(PROC_W * 0.9), int(processed_h * 0.80))
    rw, rh = motion_box[2] - motion_box[0], motion_box[3] - motion_box[1]
    window = cv2.createHanningWindow((rw, rh), cv2.CV_32F)
    cam_x, cam_y, enemy_x, enemy_y = [], [], [], []
    previous = None
    limit = int(args.max_minutes * 60 * fps) if args.max_minutes else None
    count = 0
    while True:
        ok, frame = cap.read()
        if not ok or (limit and count >= limit):
            break
        count += 1
        small = cv2.resize(frame, (PROC_W, processed_h), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        roi = gray[motion_box[1]:motion_box[3], motion_box[0]:motion_box[2]].astype(np.float32)
        if previous is None:
            cam_x.append(np.nan)
            cam_y.append(np.nan)
        else:
            (dx, dy), response = cv2.phaseCorrelate(previous, roi, window)
            if response < 0.03 or abs(dx) > rw * 0.4 or abs(dy) > rh * 0.4:
                cam_x.append(np.nan)
                cam_y.append(np.nan)
            else:
                cam_x.append(-dx * scale)
                cam_y.append(-dy * scale)
        previous = roi
        target = detect_enemy(small, enemy_box, cx_s, cy_s, args.head_offset)
        if target is None:
            enemy_x.append(np.nan)
            enemy_y.append(np.nan)
        else:
            enemy_x.append((target[0] - cx_s) * scale)
            enemy_y.append((target[1] - cy_s) * scale)
    cap.release()
    return (np.array(cam_x), np.array(cam_y), np.array(enemy_x), np.array(enemy_y),
            fps, height, count / fps)


def last_valid(array, lo, hi):
    segment = array[max(lo, 0):hi + 1]
    indexes = np.where(~np.isnan(segment))[0]
    return None if len(indexes) == 0 else float(segment[indexes[-1]])


def analyze_events(cam_x, cam_y, ex, ey, fps, height):
    cxn, cyn = np.nan_to_num(cam_x), np.nan_to_num(cam_y)
    velocity = np.hypot(cxn, cyn) * fps / height
    n = len(velocity)
    gap = max(2, int(0.05 * fps))
    events, i = [], 0
    while i < n:
        if velocity[i] > FLICK_V:
            start, quiet, j = i, 0, i
            while j < n and quiet < gap:
                quiet = quiet + 1 if velocity[j] < HOLD_V else 0
                j += 1
            events.append((start, max(start, j - quiet - 1)))
            i = j
        else:
            i += 1

    rx, ry, finals, corrections = [], [], [], []
    valid = 0
    look = int(0.3 * fps)
    settle = int(SETTLE_S * fps)
    for start, end in events:
        if end - start < 1:
            continue
        settle_end = min(n - 1, end + settle)
        total_x = float(cxn[start:settle_end + 1].sum())
        total_y = float(cyn[start:settle_end + 1].sum())
        if math.hypot(total_x, total_y) < 0.04 * height:
            continue
        e0x = last_valid(ex, start - look, start)
        e0y = last_valid(ey, start - look, start)
        got = False
        if e0x is not None and abs(e0x) > 0.05 * height:
            ratio = total_x / e0x
            if -1 <= ratio <= 4:
                rx.append(ratio)
                got = True
        if e0y is not None and abs(e0y) > 0.04 * height:
            ratio = total_y / e0y
            if -1 <= ratio <= 4:
                ry.append(ratio)
                got = True
        if not got:
            continue
        valid += 1
        fx, fy = last_valid(ex, end, settle_end), last_valid(ey, end, settle_end)
        if fx is not None and fy is not None:
            finals.append(math.hypot(fx, fy) / height)
        segment = cxn[end + 1:settle_end + 1]
        significant = segment[np.abs(segment) > 0.25 * height / fps]
        corrections.append(int(np.sum(np.diff(np.sign(significant)) != 0))
                           if len(significant) > 1 else 0)

    visible = ~np.isnan(ex)
    on_head = None
    if visible.sum() > 30:
        on_head = float(np.mean((np.abs(ex[visible]) < 0.035 * height) &
                                (np.abs(ey[visible]) < 0.035 * height)))
    hold = (velocity < HOLD_V) & visible
    pairs = hold[1:] & hold[:-1]
    differences = np.diff(cxn)[pairs]
    jitter = float(np.std(differences) / height * 1000) if len(differences) > 30 else None
    return {"rx": rx, "ry": ry, "finals": finals, "corrs": corrections,
            "valid": valid, "flicks": len(events), "on_head": on_head, "jitter": jitter}


def boot_ci(values):
    rng = np.random.default_rng(0)
    array = np.array(values)
    medians = [np.median(rng.choice(array, len(array))) for _ in range(300)]
    low, high = np.percentile(medians, [5, 95])
    return float(low), float(high)


def build_report(sessions, scope, sens):
    rx, ry, final, corrections, jitters, on_heads = [], [], [], [], [], []
    duration, valid = 0.0, 0
    for session in sessions:
        if session.get("scope") != scope or session.get("sens", 0) <= 0:
            continue
        factor = sens / session["sens"]
        rx += [r * factor for r in session.get("rx", [])]
        ry += [r * factor for r in session.get("ry", [])]
        final += session.get("finals", [])
        corrections += session.get("corrs", [])
        if session.get("jitter") is not None:
            jitters.append(session["jitter"])
        if session.get("on_head") is not None:
            on_heads.append(session["on_head"])
        duration += session.get("duration", 0)
        valid += session.get("valid", 0)

    all_ratios = rx + ry
    report = {"duration": duration, "valid": valid, "sens": sens, "scope": scope}
    if len(all_ratios) < 5:
        report.update(enough=False, gain=None,
                      reason="لا توجد محاولات كافية لتحليل هذا النوع من الحساسية. سجّل اشتباكات أكثر.")
        return report

    gain = float(np.median(all_ratios))
    low, high = boot_ci(all_ratios)
    rate = valid / (duration / 60.0) if duration > 0 else 0
    missing = []
    if duration < MIN_SECONDS:
        missing.append(f"مدة اللعب {duration / 60:.1f} دقيقة من 5 دقائق على الأقل")
    if valid < MIN_EVENTS:
        need = MIN_EVENTS - valid
        extra = f" (نحو {need / rate:.1f} دقيقة إضافية)" if rate > 0 else ""
        missing.append(f"المحاولات المفيدة {valid} من {MIN_EVENTS}{extra}")
    if high - low > MAX_CI_WIDTH:
        missing.append(f"القياس متذبذب (مجال الثقة {low:.2f}–{high:.2f})")
    step = min(1.15, max(0.85, gain ** -0.5))
    jitter = float(np.mean(jitters)) if jitters else None
    if jitter is not None and jitter > 6.0 and gain >= 0.95:
        step *= 0.97
    suggested = round(min(MAX_SENS, max(1.0, sens * step)), 1)
    report.update(enough=not missing, missing=missing, gain=gain, ci=(low, high),
                  gain_x=float(np.median(rx)) if rx else None,
                  gain_y=float(np.median(ry)) if ry else None,
                  over=float(np.mean(np.array(all_ratios) > 1.15)),
                  under=float(np.mean(np.array(all_ratios) < 0.85)),
                  final_err=float(np.median(final)) if final else None,
                  corrections=float(np.mean(corrections)) if corrections else None,
                  jitter=jitter,
                  on_head=float(np.mean(on_heads)) if on_heads else None,
                  suggested=suggested, keep=(0.9 <= gain <= 1.1))
    return report


def build_sensitivity_profile(current, sessions, style="control"):
    """Create a cautious five-scope trial profile from user's values and observed video data.

    A missing scope report keeps the user's current value unchanged; the app never invents
    a device-independent sensitivity number. Headshot mode is only a slightly quicker
    target for testing, not a promise of headshots or a universal optimal preset.
    """
    if style not in ("control", "headshot"):
        raise ValueError("نوع الإعداد غير معروف")
    target_gain = 1.0 if style == "control" else 1.08
    output = {}
    for scope in SENSITIVITY_SCOPES:
        try:
            base = float(current[scope])
        except (KeyError, TypeError, ValueError):
            output[scope] = {"current": None, "suggested": None,
                             "status": "أدخل قيمة الحساسية الحالية"}
            continue
        if not 0 < base <= MAX_SENS:
            output[scope] = {"current": base, "suggested": None,
                             "status": "القيمة يجب أن تكون بين 1 و100"}
            continue
        report = build_report(sessions, scope, base)
        gain = report.get("gain")
        if gain is None:
            output[scope] = {"current": base, "suggested": base, "gain": None,
                             "enough": False,
                             "status": "لا توجد بيانات لهذا المنظار؛ أبقينا القيمة كما هي"}
            continue
        # Half-step update to limit sudden changes. Keep each recommendation within +/-10%.
        ratio = math.sqrt(target_gain / max(gain, 0.01))
        ratio = min(1.10, max(0.90, ratio))
        suggested = round(min(MAX_SENS, max(1.0, base * ratio)), 1)
        enough = bool(report.get("enough"))
        output[scope] = {
            "current": base,
            "suggested": suggested,
            "gain": gain,
            "enough": enough,
            "status": "مبني على بياناتك" if enough else "اقتراح مبدئي — سجّل أكثر",
        }
    return {"style": style, "target_gain": target_gain, "settings": output,
            "disclaimer": "إعدادات تجريبية شخصية وليست إعدادات رسمية أو مضمونة. لا توجد قيمة واحدة تناسب كل جهاز ولا يضمن هذا التحليل إصابات الرأس."}


def print_report(report):
    print(f"\nنتيجة التحليل — {report['scope']} | الحساسية الحالية: {report['sens']}")
    print(f"مدة الفيديو: {report['duration'] / 60:.1f} دقيقة | محاولات مفيدة: {report['valid']}")
    if report.get("gain") is None:
        print("لا أستطيع إعطاء اقتراح بعد:", report["reason"])
        return
    print(f"مؤشر توافق السحب مع الهدف (1.0 قريب من المثالي): {report['gain']:.2f} [{report['ci'][0]:.2f}–{report['ci'][1]:.2f}]")
    if report["gain_x"] is not None and report["gain_y"] is not None:
        print(f"أفقي: {report['gain_x']:.2f} | رأسي: {report['gain_y']:.2f}")
    print(f"تجاوز الهدف: {report['over'] * 100:.0f}% | عدم الوصول للهدف: {report['under'] * 100:.0f}%")
    if report["on_head"] is not None:
        print(f"بقاء المؤشر ضمن منطقة الرأس التقريبية: {report['on_head'] * 100:.0f}%")
    if report["enough"]:
        print("البيانات مناسبة لإعطاء اقتراح أفضل.")
    else:
        print("الاقتراح مبدئي؛ البيانات غير كافية:")
        for item in report["missing"]:
            print(" •", item)
    if report["keep"]:
        print(f"الاقتراح: أبقِ الحساسية عند {report['sens']} وجربها في تدريب.")
    else:
        direction = "خفّض" if report["suggested"] < report["sens"] else "ارفع"
        print(f"الاقتراح: {direction} تدريجيًا من {report['sens']} إلى {report['suggested']} ثم اختبرها.")
    print("تنبيه: التحليل التقريبي لا يضمن إصابة الرأس ولا يغيّر إعدادات اللعبة تلقائيًا.")


def cmd_calibrate(args):
    try:
        profile = load_data().get("profile", {})
        button_size = args.button_size or profile.get("button_pct")
        cx, cy, fx, fy, fps, height, duration = extract_cam_and_finger(
            args.video, args.max_minutes, button_size)
    except RuntimeError as error:
        sys.exit(str(error))
    detection = float(np.mean(~np.isnan(fx))) if len(fx) else 0.0
    print(f"ظهر مؤشر الإصبع في {detection * 100:.1f}% من الإطارات")
    if detection < 0.02:
        print("لم يظهر مؤشر اللمس. فعّل «إظهار اللمسات» في خيارات المطوّر ثم سجّل فيديو جديدًا.")
        return
    result = compute_gain(cx, cy, fx, fy, fps, height)
    if result is None:
        print("بيانات السحب غير كافية. سجّل حركة لمس أطول مع إظهار اللمسات.")
        return
    print(f"نوافذ السحب المستخدمة: {result['windows']}")
    print(f"مقياس حركة الكاميرا/الإصبع: {result['k']:.3f} (أفقي {result['kx']:.3f}، رأسي {result['ky']:.3f})")
    data = load_data()
    data.setdefault("calib", []).append(dict(result, sens=args.sens, scope=args.scope,
                                             date=datetime.datetime.now().isoformat(timespec="seconds")))
    save_data(data)
    print("تم حفظ المعايرة على هذا الهاتف.")


def _finger_candidates(small, x_min, rmin=None, rmax=None):
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 190), (180, 60, 255))
    mask[:, :x_min] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ph = small.shape[0]
    low = rmin if rmin else 0.015 * ph
    high = rmax if rmax else 0.08 * ph
    out = []
    for contour in contours:
        area, perimeter = cv2.contourArea(contour), cv2.arcLength(contour, True)
        if perimeter == 0 or area == 0:
            continue
        radius = math.sqrt(area / math.pi)
        if not low <= radius <= high or 4 * math.pi * area / (perimeter * perimeter) < 0.7:
            continue
        moments = cv2.moments(contour)
        out.append((moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]))
    return out


def extract_cam_and_finger(path, max_minutes=0, button_pct=None):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"تعذر فتح الفيديو: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps < 5 or fps > 240:
        fps = 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = width / float(PROC_W)
    processed_h = int(round(height / scale))
    motion_box = (int(PROC_W * 0.2), int(processed_h * 0.08),
                  int(PROC_W * 0.8), int(processed_h * 0.65))
    rw, rh = motion_box[2] - motion_box[0], motion_box[3] - motion_box[1]
    window = cv2.createHanningWindow((rw, rh), cv2.CV_32F)
    limit = int(max_minutes * 60 * fps) if max_minutes else None
    rmin = rmax = None
    if button_pct:
        radius = button_pct / 100.0 * processed_h / 2.0
        rmin, rmax = 0.4 * radius, 1.8 * radius
    cam_x, cam_y, candidates = [], [], []
    previous, count = None, 0
    while True:
        ok, frame = cap.read()
        if not ok or (limit and count >= limit):
            break
        count += 1
        small = cv2.resize(frame, (PROC_W, processed_h), interpolation=cv2.INTER_AREA)
        roi = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)[motion_box[1]:motion_box[3], motion_box[0]:motion_box[2]].astype(np.float32)
        if previous is None:
            cam_x.append(np.nan)
            cam_y.append(np.nan)
        else:
            (dx, dy), response = cv2.phaseCorrelate(previous, roi, window)
            if response < 0.03 or abs(dx) > rw * 0.4 or abs(dy) > rh * 0.4:
                cam_x.append(np.nan)
                cam_y.append(np.nan)
            else:
                cam_x.append(-dx * scale)
                cam_y.append(-dy * scale)
        previous = roi
        candidates.append(_finger_candidates(small, PROC_W // 2, rmin, rmax))
    cap.release()
    nframes = len(candidates)
    counts = {}
    for points in candidates:
        for x, y in points:
            key = (int(x // 8), int(y // 8))
            counts[key] = counts.get(key, 0) + 1
    static = {key for key, value in counts.items() if value > 0.4 * nframes}
    fx, fy = np.full(nframes, np.nan), np.full(nframes, np.nan)
    last = None
    for index, points in enumerate(candidates):
        points = [p for p in points if (int(p[0] // 8), int(p[1] // 8)) not in static]
        if not points:
            last = None
            continue
        point = points[0] if last is None else min(points, key=lambda q: math.hypot(q[0] - last[0], q[1] - last[1]))
        fx[index], fy[index] = point[0] * scale, point[1] * scale
        last = point
    return np.array(cam_x), np.array(cam_y), fx, fy, fps, height, count / fps


def compute_gain(cam_x, cam_y, fx, fy, fps, height):
    n = min(len(cam_x), len(fx))
    fdx, fdy = np.diff(fx[:n]), np.diff(fy[:n])
    jumps = np.hypot(fdx, fdy) > 0.15 * height
    fdx[jumps] = np.nan
    fdy[jumps] = np.nan
    cx, cy = np.nan_to_num(cam_x[1:n]), np.nan_to_num(cam_y[1:n])
    window = max(2, int(0.2 * fps))
    fx_sum, fy_sum, cx_sum, cy_sum, speeds = [], [], [], [], []
    for start in range(0, len(fdx) - window, window):
        segment = fdx[start:start + window]
        if np.isnan(segment).sum() > 0.2 * window:
            continue
        fxs = float(np.nansum(fdx[start:start + window]))
        fys = float(np.nansum(fdy[start:start + window]))
        if math.hypot(fxs, fys) < 0.03 * height:
            continue
        fx_sum.append(fxs)
        fy_sum.append(fys)
        cx_sum.append(float(cx[start:start + window].sum()))
        cy_sum.append(float(cy[start:start + window].sum()))
        speeds.append(math.hypot(fxs, fys) / (window / fps))
    if len(fx_sum) < 5:
        return None
    fx_sum, fy_sum, cx_sum, cy_sum = map(np.array, (fx_sum, fy_sum, cx_sum, cy_sum))
    kx = float(np.sum(cx_sum * fx_sum) / np.sum(fx_sum * fx_sum))
    ky = float(np.sum(cy_sum * fy_sum) / np.sum(fy_sum * fy_sum))
    return {"kx": kx, "ky": ky, "k": (abs(kx) + abs(ky)) / 2,
            "windows": len(fx_sum), "flick_speed": float(np.percentile(speeds, 80))}


def cmd_analyze(args):
    data = load_data()
    successes = 0
    for path in args.videos:
        print(f"\nتحليل الفيديو: {os.path.basename(path)}")
        try:
            cx, cy, ex, ey, fps, height, duration = extract_tracks(path, args)
        except RuntimeError as error:
            print("تعذر تحليل الفيديو:", error)
            continue
        result = analyze_events(cx, cy, ex, ey, fps, height)
        result.update(file=os.path.basename(path), sens=args.sens, scope=args.scope,
                      duration=duration, date=datetime.datetime.now().isoformat(timespec="seconds"))
        print(f"المدة {duration / 60:.1f} دقيقة | محاولات التصويب {result['flicks']} | الصالحة {result['valid']}")
        data.setdefault("sessions", []).append(result)
        successes += 1
    if successes:
        save_data(data)
    print_report(build_report(data.get("sessions", []), args.scope, args.sens))


def cmd_report(args):
    print_report(build_report(load_data().get("sessions", []), args.scope, args.sens))


def cmd_reset(_args):
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    print("تم مسح بيانات التحليل المحفوظة.")


def main():
    parser = argparse.ArgumentParser(description="FF Sens Lab")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(subparser):
        subparser.add_argument("--sens", type=float, required=True, help="current sensitivity (1-100)")
        subparser.add_argument("--scope", default="general")

    analyze = sub.add_parser("analyze")
    analyze.add_argument("videos", nargs="+")
    common(analyze)
    analyze.add_argument("--cx", type=float, default=0.5)
    analyze.add_argument("--cy", type=float, default=0.5)
    analyze.add_argument("--head-offset", type=float, default=0.7)
    analyze.add_argument("--max-minutes", type=float, default=0)
    analyze.set_defaults(fn=cmd_analyze)

    report = sub.add_parser("report")
    common(report)
    report.set_defaults(fn=cmd_report)

    calibrate = sub.add_parser("calibrate")
    calibrate.add_argument("video")
    common(calibrate)
    calibrate.add_argument("--max-minutes", type=float, default=0)
    calibrate.add_argument("--button-size", type=float, default=0)
    calibrate.set_defaults(fn=cmd_calibrate)

    reset = sub.add_parser("reset")
    reset.set_defaults(fn=cmd_reset)
    args = parser.parse_args()
    if hasattr(args, "sens") and not (0 < args.sens <= MAX_SENS):
        sys.exit(f"الحساسية يجب أن تكون بين 1 و {int(MAX_SENS)}")
    args.fn(args)


if __name__ == "__main__":
    main()
