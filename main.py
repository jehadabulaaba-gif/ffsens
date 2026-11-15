# -*- coding: utf-8 -*-
"""FF Sens Lab — Arabic, mobile-first sensitivity dashboard."""
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

SCOPES = {"العامة": "general", "ريد دوت": "reddot", "منظار 2x": "2x", "منظار 4x": "4x", "AWM": "awm"}
SENSITIVITIES = (
    ("الحساسية العامة", "sens_general", "general"),
    ("ريد دوت", "sens_reddot", "reddot"),
    ("منظار 2x", "sens_2x", "2x"),
    ("منظار 4x", "sens_4x", "4x"),
    ("AWM", "sens_awm", "awm"),
)


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


class SensitivityCard(Panel):
    def __init__(self, title, value="", **kwargs):
        super().__init__(orientation="vertical", padding=[dp(12), dp(10)], spacing=dp(5),
                         size_hint_y=None, height=dp(94), **kwargs)
        self.add_widget(Label(text=title, color=MUTED, font_size="13sp",
                              halign="right", valign="middle", size_hint_y=None, height=dp(24)))
        self.input = TextInput(text=str(value), hint_text="1–100", multiline=False,
                               input_filter="float", keyboard_type="number",
                               size_hint_y=None, height=dp(42), font_size="17sp",
                               foreground_color=TEXT, cursor_color=CYAN,
                               background_normal="", background_active="",
                               background_color=(0.045, 0.065, 0.10, 1), padding=[dp(10), dp(9)])
        self.add_widget(self.input)


class Root(BoxLayout):
    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", padding=[dp(14), dp(12)], spacing=dp(10), **kwargs)
        self.app = app
        self.video_path = ""
        self.busy = False
        self.profile_fields = {}
        self.generated_profile = None
        with self.canvas.before:
            Color(*BG)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)
        self._build_header()
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(3), scroll_type=["bars", "content"])
        self.content = BoxLayout(orientation="vertical", spacing=dp(12), size_hint_y=None)
        self.content.bind(minimum_height=self.content.setter("height"))
        scroll.add_widget(self.content)
        self.add_widget(scroll)
        self._build_dashboard()

    def _update_bg(self, *_):
        self._bg_rect.pos, self._bg_rect.size = self.pos, self.size

    def _build_header(self):
        header = Panel(orientation="horizontal", size_hint_y=None, height=dp(66),
                       spacing=dp(10), padding=[dp(12), dp(7)], background=PANEL_ALT)
        logo = Label(text="FF", size_hint_x=None, width=dp(48), bold=True,
                     font_size="19sp", color=BG)
        with logo.canvas.before:
            Color(*CYAN)
            logo._logo_bg = RoundedRectangle(pos=logo.pos, size=logo.size, radius=[dp(12)])
        logo.bind(pos=lambda w, *_: setattr(w._logo_bg, "pos", w.pos),
                  size=lambda w, *_: setattr(w._logo_bg, "size", w.size))
        header.add_widget(logo)
        brand = BoxLayout(orientation="vertical")
        brand.add_widget(Label(text="FF Sens Lab", color=TEXT, bold=True,
                               font_size="19sp", halign="right", valign="middle"))
        brand.add_widget(Label(text="مساعد إعداد الحساسية", color=MUTED,
                               font_size="12sp", halign="right", valign="middle"))
        header.add_widget(brand)
        self.add_widget(header)

    def _build_dashboard(self):
        self._section_title("لوحة التحكم", "إعدادات شخصية مبنية على قيمك وتجاربك — لا تعدّل اللعبة تلقائيًا")
        hero = Panel(orientation="vertical", padding=dp(15), spacing=dp(7),
                     size_hint_y=None, height=dp(145), background=PANEL_ALT)
        hero.add_widget(Label(text="تحكم أدق. إعدادات تناسبك.", color=TEXT,
                              font_size="19sp", bold=True, halign="right", valign="middle"))
        hero.add_widget(Label(text="أدخل إعداداتك الحالية، ثم حلّل فيديو اللعب لإنشاء اقتراحين قابلين للتجربة.",
                              color=MUTED, font_size="13sp", halign="right", valign="middle"))
        hero.add_widget(self._button("اختيار فيديو المباراة", self.pick_video, primary=True))
        self.content.add_widget(hero)

        self._section_title("ملخص التحليل", "يتحدث بعد تحليل الفيديو")
        stats = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, height=dp(148))
        self.stat_gain = self._stat_card("مؤشر السحب", "—", "1.0 قريب من الهدف")
        self.stat_events = self._stat_card("محاولات مفيدة", "—", "من الفيديوهات المحللة")
        self.stat_recommendation = self._stat_card("اقتراح التحكم", "—", "تحكم متوازن")
        self.stat_quality = self._stat_card("موثوقية القياس", "بانتظار التحليل", "النتائج الأولية تقريبية")
        for card in (self.stat_gain, self.stat_events, self.stat_recommendation, self.stat_quality):
            stats.add_widget(card)
        self.content.add_widget(stats)

        self._section_title("إعداداتك الحالية", "أدخل القيم الموجودة في اللعبة؛ نحتاجها كي لا نخترع أرقامًا عامة لا تناسب جهازك.")
        profile = ffsens.load_data().get("profile", {})
        grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, height=dp(5 * 94 + 4 * 8))
        for title, key, _scope in SENSITIVITIES:
            card = SensitivityCard(title, profile.get(key, ""))
            self.profile_fields[key] = card.input
            grid.add_widget(card)
        self.content.add_widget(grid)
        self.content.add_widget(self._button("حفظ إعداداتي الحالية", self.save_profile))

        self._section_title("ملف الإعداد المطلوب", "أنشئ ملفًا للتحكم الكامل أو ملفًا تجريبيًا للهيدشوت الافتراضي.")
        mode_panel = Panel(orientation="vertical", padding=dp(13), spacing=dp(8),
                           size_hint_y=None, height=dp(154))
        self.mode_spinner = Spinner(text="تحكم كامل ومتوازن",
                                    values=("تحكم كامل ومتوازن", "هيدشوت افتراضي"),
                                    size_hint_y=None, height=dp(44), font_size="14sp")
        mode_panel.add_widget(self.mode_spinner)
        mode_panel.add_widget(self._button("إنشاء إعداداتي المقترحة", self.generate_profile, primary=True))
        self.content.add_widget(mode_panel)
        self.profile_result_panel = Panel(orientation="vertical", padding=dp(13), spacing=dp(6),
                                          size_hint_y=None, height=dp(80))
        self.profile_result = Label(text="أدخل القيم الحالية ثم أنشئ الملف. يحتاج التطبيق إلى بيانات فيديو لكل منظار كي يضبطه بناءً على تجربتك.",
                                    color=MUTED, font_size="13sp", halign="right", valign="top")
        self.profile_result.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
                                 texture_size=lambda w, size: setattr(w, "height", max(dp(52), size[1] + dp(8))))
        self.profile_result_panel.add_widget(self.profile_result)
        self.content.add_widget(self.profile_result_panel)
        self.content.add_widget(self._button("حفظ الملف المقترح كإعداداتي الحالية", self.apply_generated_profile))

        self._section_title("تحليل تسجيل لعب", "اختر فيديو أفقيًا واضحًا يتضمن تحريك المؤشر واشتباكات، ثم اختر نوع الحساسية.")
        chooser = Panel(orientation="vertical", padding=dp(13), spacing=dp(7),
                        size_hint_y=None, height=dp(100))
        chooser.add_widget(self._button("استعراض فيديوهات الهاتف", self.pick_video, primary=True))
        self.video_label = Label(text="لم يتم اختيار فيديو", color=MUTED, font_size="12sp",
                                 halign="right", valign="middle", size_hint_y=None, height=dp(28))
        chooser.add_widget(self.video_label)
        self.content.add_widget(chooser)
        controls = Panel(orientation="vertical", padding=dp(13), spacing=dp(8),
                         size_hint_y=None, height=dp(150))
        self.scope = Spinner(text="العامة", values=tuple(SCOPES), size_hint_y=None,
                             height=dp(42), font_size="14sp")
        controls.add_widget(self.scope)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        row.add_widget(self._button("تحليل الفيديو", self.analyze, primary=True))
        row.add_widget(self._button("معايرة اللمس", self.calibrate))
        controls.add_widget(row)
        self.content.add_widget(controls)
        self.progress = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(5))
        self.content.add_widget(self.progress)
        self.status = Label(text="جاهز. ابدأ بإدخال إعداداتك الحالية.", color=GREEN,
                            font_size="13sp", halign="right", valign="middle",
                            size_hint_y=None, height=dp(38))
        self.content.add_widget(self.status)

        self._section_title("تفاصيل النتيجة", "التوصية لا تضمن الهيدشوت؛ اختبرها في ساحة التدريب وزدها تدريجيًا.")
        self.result_panel = Panel(orientation="vertical", padding=dp(13), spacing=dp(7),
                                  size_hint_y=None, height=dp(210))
        self.result = Label(text="لا توجد نتيجة بعد.\n١. اختر فيديو.\n٢. اختر نوع الحساسية.\n٣. اضغط تحليل الفيديو.",
                            color=TEXT, font_size="13sp", halign="right", valign="top")
        self.result.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
                         texture_size=lambda w, size: setattr(w, "height", max(dp(170), size[1] + dp(8))))
        self.result_panel.add_widget(self.result)
        self.content.add_widget(self.result_panel)
        self.content.add_widget(self._section_title(
            "طريقة الاستخدام الآمن", "القيم المقترحة شخصية وتجريبية وليست إعدادات رسمية من اللعبة. لا يوجد رقم سحري يضمن الهيدشوت؛ نوع الهاتف، معدل الإطارات، وحجم الشاشة تؤثر على الإحساس بالحساسية."))

    def _section_title(self, title, subtitle):
        box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(52), spacing=dp(2))
        box.add_widget(Label(text=title, color=TEXT, bold=True, font_size="16sp", halign="right", valign="middle"))
        box.add_widget(Label(text=subtitle, color=MUTED, font_size="10sp", halign="right", valign="middle"))
        self.content.add_widget(box)

    def _stat_card(self, title, value, detail):
        card = Panel(orientation="vertical", padding=[dp(10), dp(7)], spacing=dp(2),
                     size_hint_y=None, height=dp(70))
        card.add_widget(Label(text=title, color=MUTED, font_size="10sp", halign="right", valign="middle"))
        value_label = Label(text=value, color=CYAN, bold=True, font_size="15sp", halign="right", valign="middle")
        card.add_widget(value_label)
        card.add_widget(Label(text=detail, color=MUTED, font_size="9sp", halign="right", valign="middle"))
        card.value_label = value_label
        return card

    def _button(self, text, callback, primary=False):
        button = Button(text=text, size_hint_y=None, height=dp(46), font_size="13sp", bold=primary,
                        color=(0.02, 0.07, 0.09, 1) if primary else TEXT,
                        background_normal="", background_down="",
                        background_color=CYAN if primary else PANEL_ALT)
        button.bind(on_release=callback)
        return button

    def _set_status(self, text, error=False):
        self.status.text = text
        self.status.color = RED if error else GREEN

    def _scope(self):
        return SCOPES.get(self.scope.text, "general")

    def _current_profile(self, require_all=True):
        data = ffsens.load_data()
        saved = data.get("profile", {})
        values = {}
        missing = []
        for _title, key, scope in SENSITIVITIES:
            raw = self.profile_fields[key].text.strip() or str(saved.get(key, ""))
            try:
                value = float(raw)
            except (TypeError, ValueError):
                missing.append(scope)
                continue
            if not 0 < value <= ffsens.MAX_SENS:
                self._set_status("كل قيمة حساسية يجب أن تكون بين 1 و100.", error=True)
                return None
            values[scope] = value
        if require_all and missing:
            labels = {"general": "العامة", "reddot": "ريد دوت", "2x": "2x", "4x": "4x", "awm": "AWM"}
            self._set_status("أدخل القيم الحالية لكل الحساسيات أولًا: " + "، ".join(labels[s] for s in missing), error=True)
            return None
        return values

    def save_profile(self, *_):
        values = self._current_profile(require_all=False)
        if values is None:
            return
        data = ffsens.load_data()
        profile = data.setdefault("profile", {})
        for scope, value in values.items():
            key = next(key for _title, key, item_scope in SENSITIVITIES if item_scope == scope)
            profile[key] = value
        ffsens.save_data(data)
        self._set_status("حُفظت إعداداتك الحالية على الهاتف.")

    def generate_profile(self, *_):
        values = self._current_profile()
        if values is None:
            return
        style = "headshot" if self.mode_spinner.text == "هيدشوت افتراضي" else "control"
        profile = ffsens.build_sensitivity_profile(values, ffsens.load_data().get("sessions", []), style)
        self.generated_profile = profile
        labels = {"general": "العامة", "reddot": "ريد دوت", "2x": "منظار 2x", "4x": "منظار 4x", "awm": "AWM"}
        lines = ["إعدادات مقترحة للتجربة — " + ("هيدشوت افتراضي" if style == "headshot" else "تحكم كامل ومتوازن")]
        for scope, item in profile["settings"].items():
            suggested = item["suggested"]
            current = item["current"]
            if suggested is None:
                lines.append(f"• {labels[scope]}: أدخل قيمة صحيحة")
            elif item["gain"] is None:
                lines.append(f"• {labels[scope]}: {suggested:g} (القيمة الحالية؛ لم تُحلل بيانات هذا المنظار)")
            else:
                lines.append(f"• {labels[scope]}: {suggested:g} (حاليًا {current:g}; {item['status']})")
        lines.append("\nهذه نقطة بداية للتجربة فقط، وليست ضبطًا مضمونًا للهيدشوت. لا تتغير إعدادات اللعبة تلقائيًا.")
        self.profile_result.text = "\n".join(lines)
        self._set_status("تم إنشاء ملف مقترح. راجعه ثم احفظه إذا أردت.")
        for _title, key, scope in SENSITIVITIES:
            suggested = profile["settings"][scope]["suggested"]
            if suggested is not None:
                self.profile_fields[key].text = f"{suggested:g}"

    def apply_generated_profile(self, *_):
        if not self.generated_profile:
            self._set_status("أنشئ ملفًا مقترحًا أولًا.", error=True)
            return
        self.save_profile()

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
                self._set_status(f"تعذر فتح قائمة الفيديو: {error}", error=True)
            return
        chooser = FileChooserListView(path=os.path.expanduser("~"), filters=["*.mp4", "*.mkv", "*.mov", "*.avi"])
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        content.add_widget(chooser)
        popup = Popup(title="اختر فيديو اللعب", content=content, size_hint=(0.95, 0.9))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        content.add_widget(row)
        row.add_widget(self._button("إلغاء", popup.dismiss))
        def select(*_args):
            if chooser.selection:
                self._set_video(chooser.selection[0], os.path.basename(chooser.selection[0]))
                popup.dismiss()
        row.add_widget(self._button("اختيار الفيديو", select, primary=True))
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
            display_name = self._display_name(resolver, uri)
            ext = os.path.splitext(display_name)[1].lower()
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
            Clock.schedule_once(lambda _dt: self._set_video(destination, display_name))
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

    def _set_video(self, path, display_name):
        self.video_path = path
        self.video_label.text = "الفيديو: " + display_name
        self._set_status("تم اختيار الفيديو. اختر المنظار وحلّله.")

    def _current_sensitivity(self):
        values = self._current_profile(require_all=False)
        return None if values is None else values.get(self._scope())

    def analyze(self, *_):
        if self.busy:
            return
        sens = self._current_sensitivity()
        if sens is None:
            self._set_status("أدخل قيمة الحساسية المختارة (1 إلى 100).", error=True)
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو محفوظًا على الهاتف أولًا.", error=True)
            return
        self._run(ffsens.cmd_analyze, Namespace(videos=[self.video_path], sens=sens,
                  scope=self._scope(), cx=0.5, cy=0.5, head_offset=0.7, max_minutes=0), True)

    def calibrate(self, *_):
        if self.busy:
            return
        sens = self._current_sensitivity()
        if sens is None:
            self._set_status("أدخل قيمة الحساسية المختارة (1 إلى 100).", error=True)
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو أولًا. للمعايرة فعّل «إظهار اللمسات» في خيارات المطوّر.", error=True)
            return
        self._run(ffsens.cmd_calibrate, Namespace(video=self.video_path, sens=sens,
                  scope=self._scope(), max_minutes=0, button_size=0), False)

    def _run(self, fn, args, update_report):
        self.busy = True
        self.progress.value = 0.3
        self._set_status("جارٍ التحليل… قد يستغرق عدة دقائق. اترك التطبيق مفتوحًا.")
        self.result.text = "يتم تحليل تسجيل اللعب…"
        def work():
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output):
                    fn(args)
                text = output.getvalue().strip() or "اكتملت العملية."
            except SystemExit as error:
                text = str(error) or "تعذر إكمال العملية."
            except Exception as error:
                text = f"حدث خطأ أثناء التحليل:\n{error}"
            Clock.schedule_once(lambda _dt: self._finish(text, args, update_report))
        threading.Thread(target=work, daemon=True).start()

    def _finish(self, text, args, update_report):
        self.busy = False
        self.progress.value = 1
        self.result.text = self._friendly_result(text)
        self._set_status("انتهت العملية. راجع النتيجة أدناه.")
        if update_report:
            self._refresh_summary(args.scope, args.sens)

    @staticmethod
    def _friendly_result(text):
        changes = {
            "النتيجة -": "نتيجة التحليل —", "مدة التحليل:": "مدة الفيديو:",
            "سحبات صالحة:": "محاولات مفيدة:", "نسبة الوصول للهدف": "مؤشر توافق السحب (1.0 قريب من الهدف)",
            "التوصية:": "الاقتراح:", "البيانات كافية.": "البيانات كافية لإعطاء اقتراح أفضل.",
            "لا توجد بيانات كافية:": "لا توجد بيانات كافية بعد:",
        }
        for old, new in changes.items():
            text = text.replace(old, new)
        return text + "\n\nالتوصية تجريبية ولا تضمن إصابة الرأس."

    def _refresh_summary(self, scope, sens):
        try:
            report = ffsens.build_report(ffsens.load_data().get("sessions", []), scope, sens)
            self.stat_events.value_label.text = str(report.get("valid", 0))
            gain = report.get("gain")
            self.stat_gain.value_label.text = "—" if gain is None else f"{gain:.2f}×"
            if gain is None:
                self.stat_recommendation.value_label.text = "لا تكفي البيانات"
                self.stat_quality.value_label.text = "أعد التسجيل"
            else:
                suggested = report.get("suggested")
                self.stat_recommendation.value_label.text = f"جرّب {suggested:g}" if not report.get("keep") else f"أبقِ {sens:g}"
                self.stat_quality.value_label.text = "أفضل" if report.get("enough") else "مبدئي"
        except Exception:
            pass


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
