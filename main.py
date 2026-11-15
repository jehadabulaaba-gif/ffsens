# -*- coding: utf-8 -*-
"""FF Sens Lab — Arabic, mobile-first sensitivity analysis UI."""
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

SCOPES = {
    "العامة": "general",
    "ريد دوت": "reddot",
    "منظار 2x": "2x",
    "منظار 4x": "4x",
    "AWM": "awm",
}
SENSITIVITIES = (
    ("الحساسية العامة", "sens_general", "general"),
    ("ريد دوت", "sens_reddot", "reddot"),
    ("منظار 2x", "sens_2x", "2x"),
    ("منظار 4x", "sens_4x", "4x"),
    ("AWM", "sens_awm", "awm"),
)


class Panel(BoxLayout):
    """Rounded dark card that resizes with the mobile layout."""

    def __init__(self, background=PANEL, radius=dp(16), **kwargs):
        super().__init__(**kwargs)
        self._background = background
        self._radius = radius
        with self.canvas.before:
            self._color = Color(*self._background)
            self._shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[self._radius])
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_):
        self._shape.pos = self.pos
        self._shape.size = self.size


class SensitivityCard(Panel):
    def __init__(self, title, value, **kwargs):
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

        with self.canvas.before:
            Color(*BG)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[0])
        self.bind(pos=self._update_bg, size=self._update_bg)

        self._build_header()
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(3), scroll_type=["bars", "content"])
        self.content = BoxLayout(orientation="vertical", spacing=dp(12), size_hint_y=None)
        self.content.bind(minimum_height=self.content.setter("height"))
        scroll.add_widget(self.content)
        self.add_widget(scroll)
        self._build_dashboard()

    def _update_bg(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _build_header(self):
        header = BoxLayout(size_hint_y=None, height=dp(62), spacing=dp(10), padding=[dp(12), dp(5)])
        header.add_widget(Label(text="FF", size_hint_x=None, width=dp(48), bold=True,
                                font_size="20sp", color=BG,
                                canvas_before=Color(*CYAN)))
        # A compact brand block; the app name and explanation remain readable on small screens.
        title_box = BoxLayout(orientation="vertical", spacing=dp(0))
        title_box.add_widget(Label(text="FF Sens Lab", color=TEXT, bold=True,
                                   font_size="19sp", halign="right", valign="middle"))
        title_box.add_widget(Label(text="محلل حساسية Free Fire", color=MUTED,
                                   font_size="12sp", halign="right", valign="middle"))
        header.add_widget(title_box)
        self.add_widget(header)

    def _build_dashboard(self):
        self._section_title("لوحة التحكم", "تحليل تسجيل اللعب بعد المباراة — لا يغيّر إعدادات اللعبة تلقائيًا")
        hero = Panel(orientation="vertical", padding=dp(16), spacing=dp(8),
                     size_hint_y=None, height=dp(154), background=PANEL_ALT)
        hero.add_widget(Label(text="حساسية تناسب طريقة لعبك", color=TEXT,
                              font_size="20sp", bold=True, halign="right", valign="middle"))
        hero.add_widget(Label(text="اختر فيديو المباراة وأدخل الحساسية المستخدمة لتحصل على قراءة واضحة وتوصية مبدئية.",
                              color=MUTED, font_size="13sp", halign="right", valign="top"))
        self.primary_button = self._button("ابدأ تحليل فيديو", self.pick_video, primary=True)
        hero.add_widget(self.primary_button)
        self.content.add_widget(hero)

        self._section_title("ملخص آخر نتيجة", "تتحدث هذه البطاقات تلقائيًا بعد التحليل")
        stats = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, height=dp(148))
        self.stat_gain = self._stat_card("دقة السحب", "—", "نسبة حركة المؤشر إلى الهدف")
        self.stat_events = self._stat_card("سحبات صالحة", "—", "عدد المحاولات التي حللها التطبيق")
        self.stat_recommendation = self._stat_card("التوصية", "—", "تظهر بعد تحليل فيديو")
        self.stat_quality = self._stat_card("جودة البيانات", "بانتظار التحليل", "سجّل وقتًا كافيًا للحصول على نتيجة أفضل")
        for card in (self.stat_gain, self.stat_events, self.stat_recommendation, self.stat_quality):
            stats.add_widget(card)
        self.content.add_widget(stats)

        self._section_title("إعدادات الحساسية", "اكتب القيم التي تستخدمها في اللعبة. يمكنك حفظها للرجوع إليها لاحقًا.")
        data = ffsens.load_data()
        profile = data.get("profile", {})
        grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, height=dp(5 * 94 + 4 * 8))
        for title, key, _scope in SENSITIVITIES:
            card = SensitivityCard(title, profile.get(key, ""))
            self.profile_fields[key] = card.input
            grid.add_widget(card)
        self.content.add_widget(grid)
        self.content.add_widget(self._button("حفظ إعداداتي", self.save_profile))

        self._section_title("تحليل تسجيل", "من الأفضل اختيار فيديو أفقي واضح يظهر حركة التصويب أثناء الاشتباكات.")
        chooser_panel = Panel(orientation="vertical", padding=dp(14), spacing=dp(8),
                              size_hint_y=None, height=dp(160))
        chooser_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self.choose_button = self._button("اختيار فيديو من الهاتف", self.pick_video, primary=True)
        chooser_row.add_widget(self.choose_button)
        chooser_panel.add_widget(chooser_row)
        self.video_label = Label(text="لم يتم اختيار فيديو", color=MUTED,
                                 font_size="13sp", halign="right", valign="middle",
                                 size_hint_y=None, height=dp(30))
        chooser_panel.add_widget(self.video_label)
        self.content.add_widget(chooser_panel)

        controls = Panel(orientation="vertical", padding=dp(14), spacing=dp(9),
                         size_hint_y=None, height=dp(160))
        controls.add_widget(Label(text="اختر نوع الحساسية المراد تحليله", color=TEXT,
                                  font_size="14sp", halign="right", valign="middle",
                                  size_hint_y=None, height=dp(28)))
        self.scope = Spinner(text="العامة", values=tuple(SCOPES), size_hint_y=None,
                             height=dp(44), font_size="15sp")
        controls.add_widget(self.scope)
        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self.analyze_button = self._button("تحليل الآن", self.analyze, primary=True)
        self.calibrate_button = self._button("معايرة الإصبع", self.calibrate)
        actions.add_widget(self.analyze_button)
        actions.add_widget(self.calibrate_button)
        controls.add_widget(actions)
        self.content.add_widget(controls)

        self.progress = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(5))
        self.content.add_widget(self.progress)
        self.status = Label(text="جاهز. ابدأ باختيار فيديو.", color=GREEN,
                            font_size="13sp", halign="right", valign="middle",
                            size_hint_y=None, height=dp(38))
        self.content.add_widget(self.status)

        self._section_title("تفاصيل التحليل", "النتائج مكتوبة بلغة مبسطة، مع توضيح إن كانت البيانات كافية.")
        self.result_panel = Panel(orientation="vertical", padding=dp(14), spacing=dp(7),
                                  size_hint_y=None, height=dp(230))
        self.result = Label(text="لم يتم تحليل فيديو بعد.\n\n1) اختر الفيديو.\n2) اختر نوع الحساسية.\n3) اضغط «تحليل الآن».",
                            color=TEXT, font_size="14sp", halign="right", valign="top")
        self.result.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
                         texture_size=lambda w, size: setattr(w, "height", max(dp(180), size[1] + dp(8))))
        self.result_panel.add_widget(self.result)
        self.content.add_widget(self.result_panel)

        tips = Panel(orientation="vertical", padding=dp(14), spacing=dp(6),
                     size_hint_y=None, height=dp(140), background=PANEL_ALT)
        tips.add_widget(Label(text="كيف أحصل على نتيجة جيدة؟", color=CYAN,
                              bold=True, font_size="15sp", halign="right", valign="middle"))
        tips.add_widget(Label(text="• سجّل اللعب أفقيًا وبجودة واضحة.\n• اجعل التسجيل يتضمن عدة اشتباكات وسحبات تصويب.\n• التحليل تقريبي؛ لا يغيّر إعدادات اللعبة ولا يضمن إصابة الرأس.",
                              color=MUTED, font_size="12sp", halign="right", valign="top"))
        self.content.add_widget(tips)

    def _section_title(self, title, subtitle):
        box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(52), spacing=dp(2))
        box.add_widget(Label(text=title, color=TEXT, bold=True, font_size="17sp",
                             halign="right", valign="middle"))
        box.add_widget(Label(text=subtitle, color=MUTED, font_size="11sp",
                             halign="right", valign="middle"))
        self.content.add_widget(box)

    def _stat_card(self, title, value, detail):
        card = Panel(orientation="vertical", padding=[dp(11), dp(8)], spacing=dp(3),
                     background=PANEL, size_hint_y=None, height=dp(70))
        card.add_widget(Label(text=title, color=MUTED, font_size="11sp",
                              halign="right", valign="middle"))
        value_label = Label(text=value, color=CYAN, bold=True, font_size="16sp",
                            halign="right", valign="middle")
        card.add_widget(value_label)
        card.add_widget(Label(text=detail, color=MUTED, font_size="9sp",
                              halign="right", valign="middle"))
        card.value_label = value_label
        return card

    def _button(self, text, callback, primary=False):
        button = Button(text=text, size_hint_y=None, height=dp(48), font_size="14sp",
                        bold=primary, color=TEXT, background_normal="", background_down="",
                        background_color=CYAN if primary else PANEL_ALT)
        button.bind(on_release=callback)
        return button

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

        chooser = FileChooserListView(path=os.path.expanduser("~"),
                                      filters=["*.mp4", "*.mkv", "*.mov", "*.avi"])
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        content.add_widget(chooser)
        popup = Popup(title="اختر فيديو اللعب", content=content, size_hint=(0.95, 0.9))
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        content.add_widget(row)
        row.add_widget(self._button("إلغاء", popup.dismiss))
        def select(*_args):
            if chooser.selection:
                self._set_video(chooser.selection[0], os.path.basename(chooser.selection[0]))
                popup.dismiss()
        row.add_widget(self._button("اختيار", select, primary=True))
        popup.open()

    def on_android_activity_result(self, request_code, result_code, data):
        if request_code != self.app.PICK_VIDEO_REQUEST:
            return
        if not data or data.getData() is None:
            self._set_status("لم يتم اختيار فيديو.")
            return
        uri = data.getData()
        self._set_status("جارٍ استيراد الفيديو إلى التطبيق…")
        threading.Thread(target=self._copy_video_uri, args=(uri,), daemon=True).start()

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
            Clock.schedule_once(lambda _dt: self._set_status(
                f"لم أتمكن من قراءة هذا الفيديو. اختر ملفًا محفوظًا محليًا.\n{error}", error=True))

    @staticmethod
    def _display_name(resolver, uri):
        try:
            from jnius import autoclass, jarray
            columns = jarray("java.lang.String")(["_display_name"])
            cursor = resolver.query(uri, columns, None, None, None)
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
        self.video_label.text = "الفيديو المختار: " + display_name
        self._set_status("تم اختيار الفيديو. اختر نوع الحساسية واضغط تحليل الآن.")

    def _scope(self):
        return SCOPES.get(self.scope.text, "general")

    def _current_sensitivity(self):
        key = next((key for _title, key, scope in SENSITIVITIES if scope == self._scope()), "sens_general")
        try:
            value = float(self.profile_fields[key].text)
        except (ValueError, KeyError):
            return None
        return value if 0 < value <= ffsens.MAX_SENS else None

    def save_profile(self, *_):
        data = ffsens.load_data()
        profile = data.setdefault("profile", {})
        for _title, key, _scope in SENSITIVITIES:
            raw = self.profile_fields[key].text.strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                self._set_status(f"قيمة {key} غير صحيحة.", error=True)
                return
            if not 0 < value <= ffsens.MAX_SENS:
                self._set_status("قيم الحساسية يجب أن تكون بين 1 و100.", error=True)
                return
            profile[key] = value
        ffsens.save_data(data)
        self._set_status("حُفظت إعدادات الحساسية على هذا الهاتف.")

    def analyze(self, *_):
        if self.busy:
            return
        sens = self._current_sensitivity()
        if sens is None:
            self._set_status("أدخل قيمة الحساسية المختارة بين 1 و100 أولاً.", error=True)
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو من زر «اختيار فيديو من الهاتف» أولاً.", error=True)
            return
        self._run(ffsens.cmd_analyze, Namespace(
            videos=[self.video_path], sens=sens, scope=self._scope(),
            cx=0.5, cy=0.5, head_offset=0.7, max_minutes=0), update_report=True)

    def calibrate(self, *_):
        if self.busy:
            return
        sens = self._current_sensitivity()
        if sens is None:
            self._set_status("أدخل قيمة الحساسية المختارة بين 1 و100 أولاً.", error=True)
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو أولاً. المعايرة تحتاج تسجيلًا مع إظهار اللمسات.", error=True)
            return
        self._run(ffsens.cmd_calibrate, Namespace(
            video=self.video_path, sens=sens, scope=self._scope(), max_minutes=0,
            button_size=0), update_report=False)

    def _run(self, fn, args, update_report):
        self.busy = True
        self.progress.value = 0.3
        self._set_status("جارٍ التحليل… قد يستغرق عدة دقائق. اترك التطبيق مفتوحًا.")
        self.result.text = "يتم تحليل الفيديو…"
        output = io.StringIO()

        def work():
            try:
                with contextlib.redirect_stdout(output):
                    fn(args)
                result = output.getvalue().strip() or "اكتملت العملية."
            except SystemExit as error:
                result = str(error) or "تعذر إكمال العملية."
            except Exception as error:
                result = f"حدث خطأ أثناء التحليل:\n{error}"
            Clock.schedule_once(lambda _dt: self._finish(result, args, update_report))

        threading.Thread(target=work, daemon=True).start()

    def _finish(self, result, args, update_report):
        self.busy = False
        self.progress.value = 1
        self.result.text = self._friendly_result(result)
        self._set_status("انتهت العملية. راجع تفاصيل النتيجة أدناه.")
        if update_report:
            self._refresh_summary(args.scope, args.sens)

    @staticmethod
    def _friendly_result(text):
        replacements = {
            "النتيجة -": "نتيجة التحليل —",
            "مدة التحليل:": "مدة الفيديو:",
            "سحبات صالحة:": "محاولات تصويب مفيدة:",
            "نسبة الوصول للهدف": "مؤشر توافق السحب مع الهدف (1.0 يعني قريبًا من المثالي)",
            "تجاوز الهدف:": "تجاوز الهدف:",
            "تقصير:": "عدم الوصول إلى الهدف:",
            "التوصية:": "اقتراح التطبيق:",
            "البيانات غير ��افية بعد:": "البيانات غير كافية بعد؛ سجّل وقتًا أطول أو اشتباكات أكثر:",
            "البيانات كافية.": "البيانات كافية لإعطاء اقتراح أفضل.",
            "لا توجد بيانات كافية:": "لا أستطيع إعطاء اقتراح بعد:",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    def _refresh_summary(self, scope, sens):
        try:
            report = ffsens.build_report(ffsens.load_data().get("sessions", []), scope, sens)
            self.stat_events.value_label.text = str(report.get("valid", 0))
            gain = report.get("gain")
            self.stat_gain.value_label.text = "—" if gain is None else f"{gain:.2f}×"
            if gain is None:
                self.stat_recommendation.value_label.text = "بيانات أقل من المطلوب"
                self.stat_quality.value_label.text = "أضف تسجيلًا أوضح وأطول"
            else:
                suggestion = report.get("suggested")
                self.stat_recommendation.value_label.text = (
                    f"أبقِ {sens:g}" if report.get("keep") else f"جرّب {suggestion:g}"
                )
                self.stat_quality.value_label.text = "مناسبة" if report.get("enough") else "مبدئية"
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
