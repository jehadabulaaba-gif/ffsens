# -*- coding: utf-8 -*-
"""FF Sens Lab — Free Fire sensitivity analysis from recorded gameplay."""
import contextlib
import io
import os
import shutil
import threading
import uuid
from argparse import Namespace

import cv2
from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import platform

import ffsens

BG = (0.035, 0.055, 0.09, 1)
PANEL = (0.075, 0.10, 0.15, 1)
PANEL_ALT = (0.095, 0.13, 0.19, 1)
TEXT = (0.93, 0.96, 1, 1)
MUTED = (0.62, 0.69, 0.79, 1)
CYAN = (0.10, 0.78, 0.88, 1)
GREEN = (0.28, 0.82, 0.57, 1)
RED = (1, 0.38, 0.38, 1)

AIM_MODES = {
    "افتراضي (Default)": "default",
    "دقيق عند المنظار (Precise on Scope)": "precise_on_scope",
    "تحكم كامل (Full Control)": "full_control",
}
AIM_MODE_HELP = {
    "default": "اختر Default إذا كان هذا هو Aim Precision المستخدم أثناء اللعب.",
    "precise_on_scope": "اختر Precise on Scope إذا كان هو الوضع المستخدم في التسجيل.",
    "full_control": "اختر Full Control إذا كان هو وضع التصويب المستخدم في التسجيل.",
}
SENSITIVITIES = (
    ("الحساسية العامة", "general", "sens_general"),
    ("ريد دوت", "reddot", "sens_reddot"),
    ("منظار 2x", "2x", "sens_2x"),
    ("منظار 4x", "4x", "sens_4x"),
    ("قناص / AWM", "awm", "sens_awm"),
)
FREE_LOOK_KEY = "sens_free_look"
SCOPES = {"العامة": "general", "ريد دوت": "reddot", "منظار 2x": "2x",
          "منظار 4x": "4x", "قناص / AWM": "awm"}


def detect_fire_button_candidates(image_path, size_pct=None):
    """Return plausible circular HUD-button centers; not a semantic classifier.

    HUDs are customizable and button art varies, so candidates are ranked and
    must be confirmed by the player against the displayed screenshot.
    Coordinates are normalized to the source image for device-independent storage.
    """
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError("تعذر فتح صورة تخطيط HUD.")
    height, width = image.shape[:2]
    if min(width, height) < 160:
        raise ValueError("الصورة صغيرة جدًا؛ اختر لقطة شاشة واضحة وكاملة لتخطيط HUD.")
    scale = min(1.0, 1000.0 / max(width, height))
    if scale < 1:
        image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    min_radius = max(7, int(h * 0.018))
    max_radius = max(min_radius + 1, int(h * 0.16))
    expected = float(size_pct) * h / 200.0 if size_pct else None
    if expected:
        min_radius = max(5, int(expected * 0.42))
        max_radius = max(min_radius + 1, int(expected * 2.0))

    found = []
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.25,
                               minDist=max(15, int(h * 0.035)), param1=100,
                               param2=29, minRadius=min_radius, maxRadius=max_radius)
    if circles is not None:
        for x, y, radius in circles[0]:
            found.append((float(x), float(y), float(radius), "دائرة"))

    # Supplement Hough detections with nearly round contours, since HUD buttons
    # are often rings and not solid circles.
    edges = cv2.Canny(gray, 70, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        area = cv2.contourArea(contour)
        if perimeter <= 0 or area <= 0:
            continue
        circularity = 4 * 3.14159265 * area / (perimeter * perimeter)
        (x, y), radius = cv2.minEnclosingCircle(contour)
        if circularity >= 0.72 and min_radius <= radius <= max_radius:
            found.append((float(x), float(y), float(radius), "محيط دائري"))

    # Deduplicate overlapping detections.
    unique = []
    for item in sorted(found, key=lambda x: -x[2]):
        x, y, radius, _kind = item
        if all(((x - ox) ** 2 + (y - oy) ** 2) ** 0.5 > max(10, radius * 0.55)
               for ox, oy, _or, _ok in unique):
            unique.append(item)
    if not unique:
        raise ValueError("لم أجد أزرارًا دائرية واضحة. اختر صورة HUD كاملة أو أعدها بجودة أفضل.")

    def rank(item):
        x, y, radius, _kind = item
        # Fire controls are often near a lower corner; do not assume right side,
        # because left-fire layouts are common. Size is a weak clue only.
        bottom = y / h
        edge = max(x / w, 1 - x / w)
        size_score = 0.5 if not expected else max(0, 1 - abs(radius - expected) / max(expected, 1))
        return 0.45 * bottom + 0.20 * edge + 0.35 * size_score

    unique.sort(key=rank, reverse=True)
    result = []
    for x, y, radius, kind in unique[:8]:
        size_estimate = round(200 * radius / h, 1)
        result.append({
            "x_pct": round(100 * x / w, 1),
            "y_pct": round(100 * y / h, 1),
            "detected_size_pct": size_estimate,
            "kind": kind,
            # This is a geometric ranking confidence, not certainty that the
            # circle is the fire button; explicit confirmation is always needed.
            "rank_score": round(rank((x, y, radius, kind)), 3),
        })
    return {"width": width, "height": height, "candidates": result}


class Panel(BoxLayout):
    def __init__(self, background=PANEL, radius=dp(16), **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*background)
            self._shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[radius])
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_):
        self._shape.pos = self.pos
        self._shape.size = self.size


class ValueCard(Panel):
    def __init__(self, title, value="", **kwargs):
        super().__init__(orientation="vertical", padding=[dp(10), dp(7)], spacing=dp(4),
                         size_hint_y=None, height=dp(78), **kwargs)
        self.add_widget(Label(text=title, color=MUTED, font_size="12sp",
                              halign="right", valign="middle", size_hint_y=None, height=dp(22)))
        self.input = TextInput(text=str(value), hint_text="القيمة الحالية",
                               multiline=False, input_filter="float", keyboard_type="number",
                               size_hint_y=None, height=dp(38), font_size="15sp",
                               foreground_color=TEXT, cursor_color=CYAN,
                               background_normal="", background_active="",
                               background_color=(0.045, 0.065, 0.10, 1), padding=[dp(8), dp(7)])
        self.add_widget(self.input)


class Root(BoxLayout):
    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", padding=[dp(13), dp(9)], spacing=dp(8), **kwargs)
        self.app = app
        self.video_path = ""
        self.video_display_name = ""
        self.screenshot_path = ""
        self.detected_fire = None
        self.candidate_popup = None
        self.busy = False
        self.value_inputs = {}
        with self.canvas.before:
            Color(*BG)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)
        self._build_header()
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(3), scroll_type=["bars", "content"])
        self.content = BoxLayout(orientation="vertical", spacing=dp(9), size_hint_y=None)
        self.content.bind(minimum_height=self.content.setter("height"))
        scroll.add_widget(self.content)
        self.add_widget(scroll)
        self._build_dashboard()

    def _update_bg(self, *_):
        self._bg_rect.pos, self._bg_rect.size = self.pos, self.size

    def _build_header(self):
        header = Panel(orientation="horizontal", size_hint_y=None, height=dp(56),
                       spacing=dp(9), padding=[dp(10), dp(5)], background=PANEL_ALT)
        logo = Label(text="FF", size_hint_x=None, width=dp(42), bold=True,
                     font_size="18sp", color=(0.02, 0.07, 0.09, 1))
        with logo.canvas.before:
            Color(*CYAN)
            logo._logo_bg = RoundedRectangle(pos=logo.pos, size=logo.size, radius=[dp(10)])
        logo.bind(pos=lambda w, *_: setattr(w._logo_bg, "pos", w.pos),
                  size=lambda w, *_: setattr(w._logo_bg, "size", w.size))
        header.add_widget(logo)
        brand = BoxLayout(orientation="vertical")
        brand.add_widget(Label(text="FF Sens Lab", color=TEXT, bold=True,
                               font_size="17sp", halign="right", valign="middle"))
        brand.add_widget(Label(text="محلل حساسية Free Fire", color=MUTED,
                               font_size="10sp", halign="right", valign="middle"))
        header.add_widget(brand)
        self.add_widget(header)

    def _build_dashboard(self):
        self._section("١ — وضع التصويب", "طابق هذا الخيار مع Aim Precision في فيديو المباراة؛ تُفصل النتائج حسب الوضع.")
        self.mode = Spinner(text="افتراضي (Default)", values=tuple(AIM_MODES),
                            size_hint_y=None, height=dp(42), font_size="12sp")
        self.mode.bind(text=self._on_mode_changed)
        self.content.add_widget(self.mode)
        self.mode_help = Label(text=AIM_MODE_HELP["default"], color=MUTED, font_size="10sp",
                               halign="right", valign="middle", size_hint_y=None, height=dp(27))
        self.mode_help.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        self.content.add_widget(self.mode_help)

        self._section("٢ — حساسياتك الحالية", "أدخل أرقامك كما تظهر في اللعبة؛ الاقتراح لا يستبدل اختبارك الشخصي.")
        saved = self._saved_values_for_mode()
        grid = GridLayout(cols=2, spacing=dp(6), size_hint_y=None, height=dp(6 * 78 + 5 * 6))
        for title, scope, _key in SENSITIVITIES:
            card = ValueCard(title, saved.get(scope, ""))
            self.value_inputs[scope] = card.input
            grid.add_widget(card)
        free_card = ValueCard("النظر الحر (Free Look)", saved.get("free_look", ""))
        self.value_inputs["free_look"] = free_card.input
        grid.add_widget(free_card)
        self.content.add_widget(grid)
        self.content.add_widget(self._button("حفظ القيم لهذا الوضع", self.save_values))

        self._section("٣ — تخطيط زر الإطلاق", "أدخل الحجم واختر صورة HUD. سيعرض التطبيق دوائر مرشحة لتؤكد أيها زر الإطلاق.")
        hud = Panel(orientation="vertical", padding=dp(10), spacing=dp(6),
                    size_hint_y=None, height=dp(132))
        row = GridLayout(cols=2, spacing=dp(6), size_hint_y=None, height=dp(40))
        self.fingers = Spinner(text="إصبعان", values=("إصبعان", "3 أصابع", "4 أصابع", "5 أصابع"),
                               size_hint_y=None, height=dp(38), font_size="11sp")
        row.add_widget(self.fingers)
        self.fire_size = self._number_input("حجم زر الإطلاق %")
        row.add_widget(self.fire_size)
        hud.add_widget(row)
        hud.add_widget(self._button("اختيار صورة تخطيط HUD", self.pick_screenshot))
        self.fire_location = Label(text="موقع زر الإطلاق: لم يُحدّد", color=MUTED, font_size="10sp",
                                   halign="right", valign="middle", size_hint_y=None, height=dp(24))
        self.fire_location.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        hud.add_widget(self.fire_location)
        self.content.add_widget(hud)
        self.content.add_widget(self._button("حفظ إعداداتي لهذا الوضع", self.save_values))

        self._section("٤ — فيديو المباراة", "اختر تسجيلًا من الهاتف. إظهار اللمسات في التسجيل يساعد في قياس مسار الإصبع.")
        video = Panel(orientation="vertical", padding=dp(10), spacing=dp(5),
                      size_hint_y=None, height=dp(74))
        video.add_widget(self._button("اختيار فيديو من الهاتف", self.pick_video, primary=True))
        self.video_label = Label(text="لم يتم اختيار فيديو", color=MUTED, font_size="10sp",
                                 halign="right", valign="middle", size_hint_y=None, height=dp(21))
        video.add_widget(self.video_label)
        self.content.add_widget(video)

        controls = Panel(orientation="vertical", padding=dp(9), spacing=dp(5),
                         size_hint_y=None, height=dp(88))
        self.scope = Spinner(text="العامة", values=tuple(SCOPES), size_hint_y=None,
                             height=dp(36), font_size="11sp")
        controls.add_widget(self.scope)
        actions = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        actions.add_widget(self._button("تحليل الفيديو", self.analyze, primary=True))
        actions.add_widget(self._button("معايرة اللمس", self.calibrate))
        controls.add_widget(actions)
        self.content.add_widget(controls)
        self.progress = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(4))
        self.content.add_widget(self.progress)
        self.status = Label(text="جاهز. ابدأ بإعداد الوضع وحساسياتك.", color=GREEN,
                            font_size="10sp", halign="right", valign="middle",
                            size_hint_y=None, height=dp(30))
        self.content.add_widget(self.status)
        self._section("اقتراح لكل منظار", "يعتمد على تسجيلات هذا الوضع فقط. تسجيل واحد قد لا يكفي لتغيير الحساسية.")
        self.profile_result = Label(text="حلّل فيديوهات منفصلة لكل منظار ووضع تصويب لبناء اقتراحات من تجربتك.",
                                    color=TEXT, font_size="10sp", halign="right", valign="top",
                                    size_hint_y=None, height=dp(85))
        self.profile_result.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
                                 texture_size=lambda w, size: setattr(w, "height", max(dp(82), size[1] + dp(5))))
        self.content.add_widget(self.profile_result)
        self._section("نتيجة التحليل", "مقاييس تقريبية؛ لا يمكن للفيديو وحده إثبات نسبة الهيدشوت أو عزل أثر Aim Assist تمامًا.")
        self.result = Label(text="لا توجد نتيجة بعد.", color=TEXT, font_size="10sp",
                            halign="right", valign="top", size_hint_y=None, height=dp(120))
        self.result.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
                         texture_size=lambda w, size: setattr(w, "height", max(dp(115), size[1] + dp(5))))
        self.content.add_widget(self.result)

    def _section(self, title, subtitle):
        box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(42), spacing=dp(1))
        box.add_widget(Label(text=title, color=TEXT, bold=True, font_size="13sp", halign="right", valign="middle"))
        box.add_widget(Label(text=subtitle, color=MUTED, font_size="9sp", halign="right", valign="middle"))
        self.content.add_widget(box)

    def _button(self, text, callback, primary=False):
        button = Button(text=text, size_hint_y=None, height=dp(39), font_size="10sp", bold=primary,
                        color=(0.02, 0.07, 0.09, 1) if primary else TEXT,
                        background_normal="", background_down="",
                        background_color=CYAN if primary else PANEL_ALT)
        button.bind(on_release=callback)
        return button

    @staticmethod
    def _number_input(hint):
        return TextInput(hint_text=hint, multiline=False, input_filter="float", keyboard_type="number",
                         size_hint_y=None, height=dp(38), font_size="10sp", foreground_color=TEXT,
                         cursor_color=CYAN, background_normal="", background_active="",
                         background_color=(0.045, 0.065, 0.10, 1), padding=[dp(6), dp(6)])

    def _mode_key(self):
        return AIM_MODES.get(self.mode.text, "default")

    def _saved_values_for_mode(self):
        profile = ffsens.load_data().get("profile", {})
        saved = profile.get("aim_profiles", {}).get(self._mode_key(), {})
        if not saved:
            saved = profile
        values = {scope: saved.get(scope, saved.get(key, "")) for _title, scope, key in SENSITIVITIES}
        values["free_look"] = saved.get("free_look", saved.get(FREE_LOOK_KEY, ""))
        if hasattr(self, "fingers"):
            self.fingers.text = {2: "إصبعان", 3: "3 أصابع", 4: "4 أصابع", 5: "5 أصابع"}.get(saved.get("finger_count"), "إصبعان")
            self.fire_size.text = str(saved.get("fire_button_size_pct") or "")
            self.detected_fire = saved.get("fire_button_location")
            self._refresh_fire_location()
        return values

    def _on_mode_changed(self, *_):
        self.mode_help.text = AIM_MODE_HELP[self._mode_key()]
        saved = self._saved_values_for_mode()
        for scope, field in self.value_inputs.items():
            field.text = str(saved.get(scope, ""))
        self._show_profile_recommendations()

    def _values(self, require_all=True):
        values, missing = {}, []
        for scope, field in self.value_inputs.items():
            raw = field.text.strip()
            if not raw:
                missing.append(scope)
                continue
            try:
                number = float(raw)
            except ValueError:
                self._set_status("اكتب قيم الحساسية كأرقام.", error=True)
                return None
            if not 0 < number <= ffsens.MAX_SENS:
                self._set_status(f"قيم الحساسية يجب أن تكون بين 1 و{ffsens.MAX_SENS:g}.", error=True)
                return None
            values[scope] = number
        if require_all and missing:
            labels = {"general": "العامة", "reddot": "ريد دوت", "2x": "2x", "4x": "4x", "awm": "AWM", "free_look": "النظر الحر"}
            self._set_status("أدخل القيم السابقة أولًا: " + "، ".join(labels[x] for x in missing), error=True)
            return None
        return values

    def _hud_values(self):
        raw = self.fire_size.text.strip()
        if not raw:
            self._set_status("أدخل حجم زر الإطلاق % واختر صورة HUD لتقدير موقعه.", error=True)
            return None
        try:
            size = float(raw)
        except ValueError:
            self._set_status("حجم زر الإطلاق يجب أن يكون رقمًا بين 1 و100%.", error=True)
            return None
        if not 0 < size <= 100:
            self._set_status("حجم زر الإطلاق يجب أن يكون أكبر من 0 وحتى 100%.", error=True)
            return None
        if not self.detected_fire:
            self._set_status("اختر صورة HUD وحدد أي دائرة مرشحة هي زر الإطلاق قبل المتابعة.", error=True)
            return None
        return {"finger_count": {"إصبعان": 2, "3 أصابع": 3, "4 أصابع": 4, "5 أصابع": 5}.get(self.fingers.text, 2),
                "fire_button_size_pct": size,
                "fire_button_location": self.detected_fire,
                "hud_screenshot": os.path.basename(self.screenshot_path)}

    def _set_status(self, text, error=False):
        self.status.text = text
        self.status.color = RED if error else GREEN

    def save_values(self, *_):
        values = self._values(require_all=True)
        hud = self._hud_values()
        if values is None or hud is None:
            return
        data = ffsens.load_data()
        profile = data.setdefault("profile", {})
        mode_profile = profile.setdefault("aim_profiles", {}).setdefault(self._mode_key(), {})
        mode_profile.update(values)
        mode_profile.update(hud)
        ffsens.save_data(data)
        self._set_status("حُفظت القيم وحجم وموقع زر الإطلاق لهذا الوضع.")

    def _scope_key(self):
        return SCOPES.get(self.scope.text, "general")

    def _current_sensitivity(self):
        values = self._values(require_all=False)
        return None if values is None else values.get(self._scope_key())

    def pick_video(self, *_):
        self._pick_file("video")

    def pick_screenshot(self, *_):
        self._pick_file("image")

    def _pick_file(self, kind):
        if platform == "android":
            try:
                from jnius import autoclass
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                Intent = autoclass("android.content.Intent")
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType("video/*" if kind == "video" else "image/*")
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                request = self.app.PICK_VIDEO_REQUEST if kind == "video" else self.app.PICK_IMAGE_REQUEST
                activity.startActivityForResult(intent, request)
            except Exception as error:
                self._set_status(f"تعذر فتح اختيار الملف: {error}", error=True)
            return
        filters = ["*.mp4", "*.mkv", "*.mov", "*.avi"] if kind == "video" else ["*.png", "*.jpg", "*.jpeg", "*.webp"]
        chooser = FileChooserListView(path=os.path.expanduser("~"), filters=filters)
        content = BoxLayout(orientation="vertical", spacing=dp(7), padding=dp(7))
        content.add_widget(chooser)
        popup = Popup(title="اختر فيديو" if kind == "video" else "اختر صورة تخطيط HUD",
                      content=content, size_hint=(0.95, 0.9))
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        content.add_widget(actions)
        actions.add_widget(self._button("إلغاء", popup.dismiss))
        def select(*_args):
            if chooser.selection:
                self._accept_file(chooser.selection[0], kind, os.path.basename(chooser.selection[0]))
                popup.dismiss()
        actions.add_widget(self._button("اختيار", select, primary=True))
        popup.open()

    def on_android_activity_result(self, request_code, result_code, data):
        if not data or data.getData() is None:
            return
        if request_code == self.app.PICK_VIDEO_REQUEST:
            kind = "video"
        elif request_code == self.app.PICK_IMAGE_REQUEST:
            kind = "image"
        else:
            return
        self._set_status("جارٍ استيراد الملف…")
        threading.Thread(target=self._copy_android_uri, args=(data.getData(), kind), daemon=True).start()

    def _copy_android_uri(self, uri, kind):
        try:
            from jnius import autoclass, jarray
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            resolver = activity.getContentResolver()
            name = self._display_name(resolver, uri)
            ext = os.path.splitext(name)[1].lower()
            allowed = (".mp4", ".mkv", ".mov", ".avi", ".3gp", ".webm") if kind == "video" else (".png", ".jpg", ".jpeg", ".webp")
            if ext not in allowed:
                ext = ".mp4" if kind == "video" else ".png"
            destination = os.path.join(self.app.user_data_dir, f"{kind}_{uuid.uuid4().hex}{ext}")
            source = resolver.openInputStream(uri)
            target = autoclass("java.io.FileOutputStream")(destination)
            buffer = jarray("b")([0] * 65536)
            try:
                while True:
                    count = source.read(buffer)
                    if count < 0:
                        break
                    if count:
                        target.write(buffer, 0, count)
            finally:
                source.close()
                target.close()
            Clock.schedule_once(lambda _dt: self._accept_file(destination, kind, name))
        except Exception as error:
            Clock.schedule_once(lambda _dt: self._set_status(f"تعذرت قراءة الملف: {error}", error=True))

    @staticmethod
    def _display_name(resolver, uri):
        try:
            from jnius import jarray
            cursor = resolver.query(uri, jarray("java.lang.String")(["_display_name"]), None, None, None)
            if cursor and cursor.moveToFirst():
                index = cursor.getColumnIndex("_display_name")
                name = str(cursor.getString(index)) if index >= 0 else "file"
                cursor.close()
                return name
        except Exception:
            pass
        return "file"

    def _accept_file(self, path, kind, display_name):
        if kind == "video":
            self.video_path = path
            self.video_label.text = "الفيديو: " + display_name
            self._set_status("تم اختيار الفيديو. تأكد أن وضع التصويب يطابقه.")
            return
        self.screenshot_path = path
        self._set_status("جارٍ العثور على دوائر مرشحة في صورة HUD…")
        try:
            size = float(self.fire_size.text) if self.fire_size.text.strip() else None
        except ValueError:
            size = None
        threading.Thread(target=self._detect_hud, args=(path, size, display_name), daemon=True).start()

    def _detect_hud(self, path, size, display_name):
        try:
            result = detect_fire_button_candidates(path, size)
            Clock.schedule_once(lambda _dt: self._choose_fire_candidate(result, display_name))
        except Exception as error:
            Clock.schedule_once(lambda _dt: self._detection_error(str(error)))

    def _choose_fire_candidate(self, result, display_name):
        popup_box = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(7))
        preview = Image(source=self.screenshot_path, allow_stretch=True, keep_ratio=True,
                        size_hint_y=None, height=dp(240))
        popup_box.add_widget(preview)
        popup_box.add_widget(Label(text="راجع صورة HUD واختر المرشح المطابق لزر الإطلاق. التقدير الهندسي وحده لا يعرف وظيفة الزر.",
                                   color=MUTED, font_size="10sp", halign="right", valign="middle",
                                   size_hint_y=None, height=dp(42)))
        scroll = ScrollView(do_scroll_x=False)
        candidates_box = BoxLayout(orientation="vertical", spacing=dp(5), size_hint_y=None)
        candidates_box.bind(minimum_height=candidates_box.setter("height"))
        scroll.add_widget(candidates_box)
        popup_box.add_widget(scroll)
        popup = Popup(title="تأكيد زر الإطلاق", content=popup_box, size_hint=(0.96, 0.88))
        for index, candidate in enumerate(result["candidates"], 1):
            label = (f"مرشح {index}: أفقي {candidate['x_pct']}%، عمودي {candidate['y_pct']}% "
                     f"— الحجم المكتشف {candidate['detected_size_pct']}%")
            button = self._button(label, lambda _btn, item=candidate: self._select_candidate(item, popup),
                                  primary=(index == 1))
            candidates_box.add_widget(button)
        cancel = self._button("لا يوجد زر إطلاق واضح؛ إلغاء", popup.dismiss)
        candidates_box.add_widget(cancel)
        self.candidate_popup = popup
        popup.open()
        self._set_status(f"تم العثور على {len(result['candidates'])} دوائر مرشحة في {display_name}; اختر زر الإطلاق يدويًا.")

    def _select_candidate(self, candidate, popup):
        self.detected_fire = dict(candidate)
        self.detected_fire["screenshot"] = os.path.basename(self.screenshot_path)
        self._refresh_fire_location()
        popup.dismiss()
        self._set_status("تم تأكيد المرشح. راجع موقعه على صورة HUD قبل الحفظ.")

    def _detection_error(self, message):
        self.detected_fire = None
        self.fire_location.text = "لم يُحدّد موقع زر الإطلاق"
        self._set_status(message, error=True)

    def _refresh_fire_location(self):
        candidate = self.detected_fire
        if not candidate:
            self.fire_location.text = "موقع زر الإطلاق: اختر صورة HUD ثم أكّد المرشح"
            return
        self.fire_location.text = (f"موقع الزر المؤكد: أفقي {candidate['x_pct']}%، "
                                   f"عمودي {candidate['y_pct']}% من الصورة")

    def _hud_values(self):
        raw = self.fire_size.text.strip()
        if not raw:
            self._set_status("أدخل حجم زر الإطلاق % واختر صورة HUD لتحديد موقعه.", error=True)
            return None
        try:
            size = float(raw)
        except ValueError:
            self._set_status("حجم زر الإطلاق يجب أن يكون رقمًا بين 1 و100%.", error=True)
            return None
        if not 0 < size <= 100:
            self._set_status("حجم زر الإطلاق يجب أن يكون أكبر من 0 وحتى 100%.", error=True)
            return None
        if not self.detected_fire:
            self._set_status("اختر صورة HUD وأكّد المرشح الذي يمثل زر الإطلاق.", error=True)
            return None
        return {"finger_count": {"إصبعان": 2, "3 أصابع": 3, "4 أصابع": 4, "5 أصابع": 5}.get(self.fingers.text, 2),
                "fire_button_size_pct": size,
                "fire_button_location": self.detected_fire,
                "hud_screenshot": os.path.basename(self.screenshot_path)}

    def save_values(self, *_):
        values = self._values(require_all=True)
        hud = self._hud_values()
        if values is None or hud is None:
            return
        data = ffsens.load_data()
        profile = data.setdefault("profile", {})
        mode_profile = profile.setdefault("aim_profiles", {}).setdefault(self._mode_key(), {})
        mode_profile.update(values)
        mode_profile.update(hud)
        ffsens.save_data(data)
        self._set_status("حُفظت الحساسيات وحجم وموقع زر الإطلاق المؤكد لهذا الوضع.")

    def _scope_key(self):
        return SCOPES.get(self.scope.text, "general")

    def _current_sensitivity(self):
        values = self._values(require_all=False)
        return None if values is None else values.get(self._scope_key())

    def analyze(self, *_):
        if self.busy:
            return
        sens = self._current_sensitivity()
        hud = self._hud_values()
        if sens is None:
            self._set_status("أدخل حساسية المنظار المختار بين 1 و100.", error=True)
            return
        if hud is None:
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو محفوظًا على الهاتف أولًا.", error=True)
            return
        args = Namespace(videos=[self.video_path], sens=sens, scope=self._scope_key(),
                         aim_mode=self._mode_key(), hud=hud, cx=0.5, cy=0.5,
                         head_offset=0.7, max_minutes=0)
        self._run(ffsens.cmd_analyze, args)

    def calibrate(self, *_):
        if self.busy:
            return
        sens = self._current_sensitivity()
        hud = self._hud_values()
        if sens is None:
            self._set_status("أدخل حساسية المنظار المختار بين 1 و100.", error=True)
            return
        if hud is None:
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو أولًا. للمعايرة فعّل إظهار اللمسات أثناء التسجيل.", error=True)
            return
        args = Namespace(video=self.video_path, sens=sens, scope=self._scope_key(),
                         aim_mode=self._mode_key(), hud=hud, max_minutes=0,
                         button_size=hud["fire_button_size_pct"])
        self._run(ffsens.cmd_calibrate, args)

    def _run(self, fn, args):
        if self.busy:
            return
        self.busy = True
        self.progress.value = 0.2
        self.result.text = "جارٍ التحليل؛ تعتمد النتيجة على جودة التسجيل وإظهار اللمسات."
        self._set_status("جارٍ تحليل التسجيل؛ اترك التطبيق مفتوحًا.")
        def work():
            output = io.StringIO()
            before_sessions = len(ffsens.load_data().get("sessions", []))
            before_calib = len(ffsens.load_data().get("calib", []))
            try:
                with contextlib.redirect_stdout(output):
                    fn(args)
                data = ffsens.load_data()
                if hasattr(args, "videos"):
                    for session in data.get("sessions", [])[before_sessions:]:
                        session["aim_mode"] = args.aim_mode
                        session["finger_count"] = args.hud["finger_count"]
                        session["fire_button_size_pct"] = args.hud["fire_button_size_pct"]
                        session["fire_button_location"] = args.hud.get("fire_button_location")
                        session["hud_screenshot"] = args.hud.get("hud_screenshot")
                else:
                    for item in data.get("calib", [])[before_calib:]:
                        item["aim_mode"] = args.aim_mode
                        item.update(args.hud)
                ffsens.save_data(data)
                text = output.getvalue().strip() or "اكتملت العملية."
            except SystemExit as error:
                text = str(error) or "تعذر إكمال العملية."
            except Exception as error:
                text = f"حدث خطأ أثناء التحليل:\n{error}"
            Clock.schedule_once(lambda _dt: self._finish(text))
        threading.Thread(target=work, daemon=True).start()

    def _finish(self, text):
        self.busy = False
        self.progress.value = 1
        self.result.text = text + "\n\nتحليل تقريبي؛ لا يضمن هيدشوتًا ولا يغيّر إعداد اللعبة."
        self._set_status("انتهى التحليل. راجع الاقتراحات أدناه.")
        self._show_profile_recommendations()

    def _sessions_for_mode(self):
        key = self._mode_key()
        return [s for s in ffsens.load_data().get("sessions", []) if s.get("aim_mode") == key]

    def _show_profile_recommendations(self):
        values = self._values(require_all=False)
        if values is None:
            return
        sessions = self._sessions_for_mode()
        lines = ["اقتراحات هذا الوضع فقط — " + self.mode.text]
        for title, scope, _key in SENSITIVITIES:
            current = values.get(scope)
            if current is None:
                lines.append(f"• {title}: أدخل قيمتك الحالية")
                continue
            report = ffsens.build_report(sessions, scope, current)
            if report.get("gain") is None:
                lines.append(f"• {title}: أبقِ {current:g}؛ لا توجد بيانات كافية لهذا المنظار")
            elif report.get("enough"):
                if report.get("keep"):
                    lines.append(f"• {title}: القياس قريب من الهدف؛ اختبر {current:g} كما هي")
                else:
                    lines.append(f"• {title}: جرّب {report['suggested']:g} بدل {current:g}؛ راقب الفرق في التدريب")
            else:
                lines.append(f"• {title}: اقتراح أولي {report.get('suggested', current):g}؛ بيانات غير كافية")
        lines.append("\nموقع زر الإطلاق تقدير هندسي أكّدتَ المرشح فيه؛ لا يثبت أن الدائرة المكتشفة هي الزر إلا بمراجعتك.")
        self.profile_result.text = "\n".join(lines)


class FFApp(App):
    title = "FF Sens Lab"
    PICK_VIDEO_REQUEST = 7314
    PICK_IMAGE_REQUEST = 7315

    def build(self):
        ffsens.DATA_FILE = os.path.join(self.user_data_dir, "ffsens_data.json")
        root = Root(self)
        if platform == "android":
            try:
                from jnius import autoclass
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                activity.bind(on_activity_result=root.on_android_activity_result)
            except Exception:
                pass
        return root


if __name__ == "__main__":
    FFApp().run()
