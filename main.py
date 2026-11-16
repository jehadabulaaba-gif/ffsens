# -*- coding: utf-8 -*-
"""FF Sens Lab: guided Free Fire sensitivity analysis for recorded gameplay."""
import contextlib
import io
import os
import threading
import uuid
from argparse import Namespace

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import platform
from kivy.graphics import Color, RoundedRectangle

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
    "default": "اختره إذا كان Aim Precision في اللعبة على Default.",
    "precise_on_scope": "اختره إذا كان Aim Precision في اللعبة على Precise on Scope.",
    "full_control": "اختره إذا كان Aim Precision في اللعبة على Full Control.",
}
SENSITIVITIES = (
    ("الحساسية العامة", "general", "sens_general"),
    ("ريد دوت", "reddot", "sens_reddot"),
    ("منظار 2x", "2x", "sens_2x"),
    ("منظار 4x", "4x", "sens_4x"),
    ("قناص / AWM", "awm", "sens_awm"),
)
FREE_LOOK_KEY = "sens_free_look"
SCOPES = {
    "العامة": "general", "ريد دوت": "reddot", "منظار 2x": "2x",
    "منظار 4x": "4x", "قناص / AWM": "awm",
}


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
        self.input = TextInput(text=str(value), hint_text="القيمة الحالية 1–100",
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
        self.busy = False
        self.value_inputs = {}
        self._loading_mode = False
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
        self._section("١ — وضع التصويب في اللعبة", "يجب أن يطابق الوضع المختار هنا الوضع المستخدم أثناء تسجيل الفيديو.")
        self.mode = Spinner(text="افتراضي (Default)", values=tuple(AIM_MODES),
                            size_hint_y=None, height=dp(42), font_size="12sp")
        self.mode.bind(text=self._on_mode_changed)
        self.content.add_widget(self.mode)
        self.mode_help = Label(text=AIM_MODE_HELP["default"], color=MUTED, font_size="10sp",
                               halign="right", valign="middle", size_hint_y=None, height=dp(28))
        self.mode_help.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        self.content.add_widget(self.mode_help)

        self._section("٢ — إعداداتك الحالية", "أدخل أرقام اللعبة نفسها؛ لن أضع قيمًا جاهزة أو أدّعي أنها مثالية.")
        saved = self._saved_values_for_mode()
        grid = GridLayout(cols=2, spacing=dp(6), size_hint_y=None,
                          height=dp(6 * 78 + 5 * 6))
        for title, scope, _key in SENSITIVITIES:
            card = ValueCard(title, saved.get(scope, ""))
            self.value_inputs[scope] = card.input
            grid.add_widget(card)
        free_card = ValueCard("النظر الحر (Free Look)", saved.get("free_look", ""))
        self.value_inputs["free_look"] = free_card.input
        grid.add_widget(free_card)
        self.content.add_widget(grid)
        self.content.add_widget(self._button("حفظ القيم لهذا الوضع", self.save_values))

        self._section("٣ — تخطيط التحكم", "اكتب بيانات HUD يدويًا؛ التطبيق لا يستطيع استنتاج حجم الزر الحقيقي من الفيديو وحده.")
        hud = Panel(orientation="vertical", padding=dp(10), spacing=dp(6),
                    size_hint_y=None, height=dp(150))
        row = GridLayout(cols=2, spacing=dp(6), size_hint_y=None, height=dp(76))
        self.fingers = Spinner(text="إصبعان", values=("إصبعان", "3 أصابع", "4 أصابع", "5 أصابع"),
                               size_hint_y=None, height=dp(40), font_size="12sp")
        row.add_widget(self.fingers)
        self.fire_size = self._number_input("حجم زر الإطلاق %", "مثال 12")
        row.add_widget(self.fire_size)
        hud.add_widget(row)
        row2 = GridLayout(cols=2, spacing=dp(6), size_hint_y=None, height=dp(46))
        self.fire_x = self._number_input("مكان الزر أفقيًا %", "0 يسار - 100 يمين")
        self.fire_y = self._number_input("مكان الزر عموديًا %", "0 أعلى - 100 أسفل")
        row2.add_widget(self.fire_x)
        row2.add_widget(self.fire_y)
        hud.add_widget(row2)
        self.content.add_widget(hud)
        self.content.add_widget(self._button("حفظ تخطيط التحكم", self.save_values))

        self._section("٤ — اختر فيديو لعبك", "حدد فيديو من الهاتف؛ سجّل مع إظهار اللمسات إذا أردت تجربة المعايرة.")
        video = Panel(orientation="vertical", padding=dp(10), spacing=dp(5),
                      size_hint_y=None, height=dp(76))
        video.add_widget(self._button("اختيار فيديو من الهاتف", self.pick_video, primary=True))
        self.video_label = Label(text="لم يتم اختيار فيديو", color=MUTED, font_size="10sp",
                                 halign="right", valign="middle", size_hint_y=None, height=dp(22))
        video.add_widget(self.video_label)
        self.content.add_widget(video)

        controls = Panel(orientation="vertical", padding=dp(10), spacing=dp(6),
                         size_hint_y=None, height=dp(93))
        self.scope = Spinner(text="العامة", values=tuple(SCOPES), size_hint_y=None,
                             height=dp(38), font_size="12sp")
        controls.add_widget(self.scope)
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        actions.add_widget(self._button("تحليل", self.analyze, primary=True))
        actions.add_widget(self._button("معايرة اللمس", self.calibrate))
        controls.add_widget(actions)
        self.content.add_widget(controls)
        self.progress = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(4))
        self.content.add_widget(self.progress)
        self.status = Label(text="جاهز. ابدأ بإدخال إعداداتك السابقة.", color=GREEN,
                            font_size="11sp", halign="right", valign="middle",
                            size_hint_y=None, height=dp(32))
        self.content.add_widget(self.status)

        self._section("اقتراح لكل منظار", "لا يظهر اقتراح إلا من بيانات الوضع والمنظار نفسيهما؛ البيانات الناقصة تبقي قيمتك الحالية.")
        self.profile_result = Label(text="حلّل فيديوهات منفصلة لكل منظار ووضع تصويب لبناء اقتراحات من تجربتك.",
                                    color=TEXT, font_size="11sp", halign="right", valign="top",
                                    size_hint_y=None, height=dp(96))
        self.profile_result.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
                                 texture_size=lambda w, size: setattr(w, "height", max(dp(90), size[1] + dp(5))))
        self.content.add_widget(self.profile_result)
        self._section("نتيجة التحليل", "المقاييس تقريبية. التصويب المساعد، حركة الخصم، السلاح ومعدل الإطارات تحدّ من دقة الاستنتاج.")
        self.result = Label(text="لا توجد نتيجة بعد.", color=TEXT, font_size="11sp",
                            halign="right", valign="top", size_hint_y=None, height=dp(145))
        self.result.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
                         texture_size=lambda w, size: setattr(w, "height", max(dp(140), size[1] + dp(6))))
        self.content.add_widget(self.result)

    def _section(self, title, subtitle):
        box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(43), spacing=dp(1))
        box.add_widget(Label(text=title, color=TEXT, bold=True, font_size="14sp", halign="right", valign="middle"))
        box.add_widget(Label(text=subtitle, color=MUTED, font_size="9sp", halign="right", valign="middle"))
        self.content.add_widget(box)

    def _button(self, text, callback, primary=False):
        button = Button(text=text, size_hint_y=None, height=dp(40), font_size="11sp", bold=primary,
                        color=(0.02, 0.07, 0.09, 1) if primary else TEXT,
                        background_normal="", background_down="",
                        background_color=CYAN if primary else PANEL_ALT)
        button.bind(on_release=callback)
        return button

    @staticmethod
    def _number_input(hint, text):
        return TextInput(hint_text=hint, text="", multiline=False, input_filter="float",
                         keyboard_type="number", size_hint_y=None, height=dp(38),
                         font_size="11sp", foreground_color=TEXT, cursor_color=CYAN,
                         background_normal="", background_active="",
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
        return values

    def _on_mode_changed(self, *_):
        if not hasattr(self, "mode_help"):
            return
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
                self._set_status("قيم الحساسية يجب أن تكون بين 1 و100.", error=True)
                return None
            values[scope] = number
        if require_all and missing:
            labels = {"general": "العامة", "reddot": "ريد دوت", "2x": "2x", "4x": "4x", "awm": "AWM", "free_look": "النظر الحر"}
            self._set_status("أدخل القيم السابقة أولًا: " + "، ".join(labels[x] for x in missing), error=True)
            return None
        return values

    def _hud_values(self):
        result = {"finger_count": {"إصبعان": 2, "3 أصابع": 3, "4 أصابع": 4, "5 أصابع": 5}.get(self.fingers.text, 2)}
        for name, field in (("fire_button_size_pct", self.fire_size),
                            ("fire_button_x_pct", self.fire_x), ("fire_button_y_pct", self.fire_y)):
            raw = field.text.strip()
            if not raw:
                result[name] = None
                continue
            try:
                value = float(raw)
            except ValueError:
                self._set_status("حجم وموقع زر الإطلاق يجب أن تكون قيمًا رقمية بالنسبة المئوية.", error=True)
                return None
            if not 0 <= value <= 100:
                self._set_status("حجم وموقع زر الإطلاق يجب أن تكون بين 0 و100%.", error=True)
                return None
            result[name] = value
        return result

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
        self._set_status("حُفظت القيم وتخطيط التحكم لهذا الوضع فقط.")

    def _scope_key(self):
        return SCOPES.get(self.scope.text, "general")

    def _current_sensitivity(self):
        values = self._values(require_all=False)
        return None if values is None else values.get(self._scope_key())

    def _set_status(self, text, error=False):
        self.status.text = text
        self.status.color = RED if error else GREEN

    def pick_video(self, *_):
        if platform == "android":
            try:
                from jnius import autoclass
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                Intent = autoclass("android.content.Intent")
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType("video/*")
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                activity.startActivityForResult(intent, self.app.PICK_VIDEO_REQUEST)
            except Exception as error:
                self._set_status(f"تعذر فتح اختيار الفيديو: {error}", error=True)
            return
        chooser = FileChooserListView(path=os.path.expanduser("~"), filters=["*.mp4", "*.mkv", "*.mov", "*.avi"])
        content = BoxLayout(orientation="vertical", spacing=dp(7), padding=dp(7))
        content.add_widget(chooser)
        popup = Popup(title="اختر فيديو اللعب", content=content, size_hint=(0.95, 0.9))
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        content.add_widget(actions)
        actions.add_widget(self._button("إلغاء", popup.dismiss))
        def select(*_args):
            if chooser.selection:
                self._set_video(chooser.selection[0], os.path.basename(chooser.selection[0]))
                popup.dismiss()
        actions.add_widget(self._button("اختيار الفيديو", select, primary=True))
        popup.open()

    def on_android_activity_result(self, request_code, result_code, data):
        if request_code != self.app.PICK_VIDEO_REQUEST:
            return
        if not data or data.getData() is None:
            self._set_status("لم يتم اختيار فيديو.")
            return
        self._set_status("جارٍ استيراد الفيديو…")
        threading.Thread(target=self._copy_video_uri, args=(data.getData(),), daemon=True).start()

    def _copy_video_uri(self, uri):
        try:
            from jnius import autoclass, jarray
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            resolver = activity.getContentResolver()
            name = self._display_name(resolver, uri)
            ext = os.path.splitext(name)[1].lower()
            if ext not in (".mp4", ".mkv", ".mov", ".avi", ".3gp", ".webm"):
                ext = ".mp4"
            destination = os.path.join(self.app.user_data_dir, "recording_" + uuid.uuid4().hex + ext)
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
            Clock.schedule_once(lambda _dt: self._set_video(destination, name))
        except Exception as error:
            Clock.schedule_once(lambda _dt: self._set_status(f"تعذرت قراءة الفيديو: {error}", error=True))

    @staticmethod
    def _display_name(resolver, uri):
        try:
            from jnius import jarray
            cursor = resolver.query(uri, jarray("java.lang.String")(["_display_name"]), None, None, None)
            if cursor and cursor.moveToFirst():
                index = cursor.getColumnIndex("_display_name")
                name = str(cursor.getString(index)) if index >= 0 else "video.mp4"
                cursor.close()
                return name
        except Exception:
            pass
        return "video.mp4"

    def _set_video(self, path, name):
        self.video_path = path
        self.video_display_name = name
        self.video_label.text = "الفيديو: " + name
        self._set_status("تم اختيار الفيديو. تأكد أن الوضع يطابق إعداد Aim Precision المستخدم أثناء اللعب.")

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
                         button_size=hud.get("fire_button_size_pct") or 0)
        self._run(ffsens.cmd_calibrate, args)

    def _run(self, fn, args):
        if self.busy:
            return
        self.busy = True
        self.progress.value = 0.25
        self.result.text = "جارٍ التحليل… هذا تقدير من التسجيل وليس اختبارًا مضمونًا."
        self._set_status("جارٍ تحليل التسجيل؛ اترك التطبيق مفتوحًا.")

        def work():
            output = io.StringIO()
            before = len(ffsens.load_data().get("sessions", []))
            try:
                with contextlib.redirect_stdout(output):
                    fn(args)
                data = ffsens.load_data()
                if hasattr(args, "videos"):
                    for session in data.get("sessions", [])[before:]:
                        session["aim_mode"] = args.aim_mode
                        session["finger_count"] = args.hud["finger_count"]
                        session["fire_button_size_pct"] = args.hud.get("fire_button_size_pct")
                        session["fire_button_x_pct"] = args.hud.get("fire_button_x_pct")
                        session["fire_button_y_pct"] = args.hud.get("fire_button_y_pct")
                    ffsens.save_data(data)
                else:
                    calib = data.get("calib", [])
                    for item in calib:
                        if item.get("scope") == args.scope and item.get("sens") == args.sens and "aim_mode" not in item:
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
        self.result.text = text + "\n\nالتوصية تقريبية، ولا تضمن الهيدشوت أو تغيّر اللعبة تلقائيًا."
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
                lines.append(f"• {title}: أبقِ {current:g} مؤقتًا؛ لا توجد بيانات كافية لهذا المنظار")
            elif report.get("enough"):
                if report.get("keep"):
                    lines.append(f"• {title}: القياس قريب من الهدف؛ اختبر {current:g} كما هي")
                else:
                    lines.append(f"• {title}: جرّب {report['suggested']:g} بدل {current:g} (اقتراح مبني على التسجيل)")
            else:
                lines.append(f"• {title}: جرّب مؤقتًا {report.get('suggested', current):g}؛ البيانات غير كافية بعد")
        lines.append("\nتقدير الحركة بالبكسل يختلف حسب دقة الفيديو؛ التطبيق لا يدّعي أن كل نقطة حساسية لها تحويل ثابت.")
        self.profile_result.text = "\n".join(lines)


class FFApp(App):
    title = "FF Sens Lab"
    PICK_VIDEO_REQUEST = 7314

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
