# -*- coding: utf-8 -*-
"""واجهة عربية لتحليل حساسية Free Fire من تسجيلات اللعب."""
import contextlib
import io
import os
import threading
import uuid
from argparse import Namespace

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
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
MUTED = (0.66, 0.73, 0.82, 1)
CYAN = (0.10, 0.78, 0.88, 1)
GREEN = (0.28, 0.82, 0.57, 1)
RED = (1, 0.38, 0.38, 1)

AIM_MODES = {
    "افتراضي": "default",
    "دقيق عند استخدام المنظار": "precise_on_scope",
    "تحكم كامل": "full_control",
}
MODE_HELP = {
    "default": "اختر الوضع نفسه المستخدم في إعدادات التصويب داخل اللعبة.",
    "precise_on_scope": "اختره إذا كان التصويب الدقيق عند استخدام المنظار مفعّلًا أثناء التسجيل.",
    "full_control": "اختره إذا كان خيار التحكم الكامل هو المستخدم أثناء التسجيل.",
}
SENSITIVITIES = (
    ("الحساسية العامة", "general", "sens_general", "تؤثر في حركة الكاميرا عند النظر دون منظار."),
    ("حساسية المنظار الأحمر", "reddot", "sens_reddot", "تُستخدم عند التصويب بالمنظار الأحمر."),
    ("حساسية منظار ٢×", "2x", "sens_2x", "تُستخدم عند التصويب بمنظار التكبير ٢×."),
    ("حساسية منظار ٤×", "4x", "sens_4x", "تُستخدم عند التصويب بمنظار التكبير ٤×."),
    ("حساسية القناص", "awm", "sens_awm", "تُستخدم مع منظار القناص والقناصة."),
)
SCOPE_LABELS = {"العامة": "general", "المنظار الأحمر": "reddot",
                "منظار ٢×": "2x", "منظار ٤×": "4x", "القناص": "awm"}
SCOPE_NAMES = {value: key for key, value in SCOPE_LABELS.items()}


class Panel(BoxLayout):
    def __init__(self, background=PANEL, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*background)
            self.shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_):
        self.shape.pos, self.shape.size = self.pos, self.size


class SensitivityCard(Panel):
    def __init__(self, title, description, value="", **kwargs):
        super().__init__(orientation="vertical", padding=[dp(12), dp(8)], spacing=dp(3),
                         size_hint_y=None, height=dp(92), **kwargs)
        self.add_widget(Label(text=title, color=TEXT, bold=True, font_size="14sp",
                              halign="right", valign="middle", size_hint_y=None, height=dp(25)))
        note = Label(text=description, color=MUTED, font_size="10sp", halign="right",
                     valign="middle", size_hint_y=None, height=dp(22))
        note.bind(size=lambda widget, *_: setattr(widget, "text_size", widget.size))
        self.add_widget(note)
        self.input = TextInput(text=str(value), hint_text="اكتب القيمة الحالية من اللعبة",
                               multiline=False, input_filter="float", keyboard_type="number",
                               size_hint_y=None, height=dp(34), font_size="14sp",
                               foreground_color=TEXT, cursor_color=CYAN,
                               background_normal="", background_active="",
                               background_color=(0.045, 0.065, 0.10, 1), padding=[dp(8), dp(5)])
        self.add_widget(self.input)


class Root(BoxLayout):
    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", padding=[dp(12), dp(8)], spacing=dp(8), **kwargs)
        self.app = app
        self.video_path = ""
        self.busy = False
        self.inputs = {}
        with self.canvas.before:
            Color(*BG)
            self.bg_shape = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._redraw, size=self._redraw)

        header = Panel(orientation="vertical", padding=[dp(12), dp(7)], spacing=dp(2),
                       size_hint_y=None, height=dp(66), background=PANEL_ALT)
        header.add_widget(Label(text="محلل حساسية فري فاير", color=TEXT, bold=True,
                                font_size="18sp", halign="right", valign="middle"))
        header.add_widget(Label(text="حلّل تسجيلك واحصل على اقتراح مبني على أدائك",
                                color=MUTED, font_size="10sp", halign="right", valign="middle"))
        self.add_widget(header)

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(3), scroll_type=["bars", "content"])
        self.content = BoxLayout(orientation="vertical", spacing=dp(9), size_hint_y=None)
        self.content.bind(minimum_height=self.content.setter("height"))
        scroll.add_widget(self.content)
        self.add_widget(scroll)
        self._build_form()

    def _redraw(self, *_):
        self.bg_shape.pos, self.bg_shape.size = self.pos, self.size

    def _section(self, title, description):
        box = BoxLayout(orientation="vertical", spacing=dp(2), size_hint_y=None, height=dp(48))
        box.add_widget(Label(text=title, color=CYAN, bold=True, font_size="15sp",
                             halign="right", valign="middle"))
        label = Label(text=description, color=MUTED, font_size="10sp", halign="right",
                      valign="middle")
        label.bind(size=lambda widget, *_: setattr(widget, "text_size", widget.size))
        box.add_widget(label)
        self.content.add_widget(box)

    def _button(self, text, callback, primary=False):
        button = Button(text=text, size_hint_y=None, height=dp(44), font_size="13sp",
                        bold=primary, color=(0.02, 0.07, 0.09, 1) if primary else TEXT,
                        background_normal="", background_down="",
                        background_color=CYAN if primary else PANEL_ALT)
        button.bind(on_release=callback)
        return button

    def _build_form(self):
        self._section("الخطوة الأولى: وضع التصويب", "اختر الوضع المطابق لإعدادات اللعبة وقت تسجيل المباراة.")
        self.mode = Spinner(text="افتراضي", values=tuple(AIM_MODES), size_hint_y=None,
                            height=dp(44), font_size="13sp")
        self.mode.bind(text=self._mode_changed)
        self.content.add_widget(self.mode)
        self.mode_help = Label(text=MODE_HELP["default"], color=MUTED, font_size="10sp",
                               halign="right", valign="middle", size_hint_y=None, height=dp(34))
        self.mode_help.bind(size=lambda widget, *_: setattr(widget, "text_size", widget.size))
        self.content.add_widget(self.mode_help)

        self._section("الخطوة الثانية: حساسيّاتك الحالية", "انسخ القيم من إعدادات اللعبة. الأرقام هنا هي قيمك الحالية وليست اقتراحات.")
        saved = self._saved_values()
        for title, scope, key, description in SENSITIVITIES:
            card = SensitivityCard(title, description, saved.get(scope, ""))
            self.inputs[scope] = card.input
            self.content.add_widget(card)
        free = SensitivityCard("حساسية النظر الحر", "تؤثر في تحريك الكاميرا أثناء النظر حولك.",
                               saved.get("free_look", ""))
        self.inputs["free_look"] = free.input
        self.content.add_widget(free)
        self.content.add_widget(self._button("حفظ حساسياتي", self.save_values))

        self._section("الخطوة الثالثة: تسجيل المباراة", "اختر فيديو لعب واضحًا. إظهار اللمسات في التسجيل يساعد في المعايرة.")
        video_panel = Panel(orientation="vertical", padding=dp(10), spacing=dp(6),
                            size_hint_y=None, height=dp(78))
        video_panel.add_widget(self._button("اختيار فيديو من الهاتف", self.pick_video, primary=True))
        self.video_label = Label(text="لم يتم اختيار فيديو بعد", color=MUTED, font_size="11sp",
                                 halign="right", valign="middle", size_hint_y=None, height=dp(22))
        video_panel.add_widget(self.video_label)
        self.content.add_widget(video_panel)

        self._section("الخطوة الرابعة: اختر نوع الحساسية", "حدد الحساسية التي تريد تحليلها، ثم ابدأ التحليل.")
        self.scope = Spinner(text="العامة", values=tuple(SCOPE_LABELS), size_hint_y=None,
                             height=dp(44), font_size="13sp")
        self.content.add_widget(self.scope)
        actions = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(7))
        actions.add_widget(self._button("تحليل التسجيل", self.analyze, primary=True))
        actions.add_widget(self._button("معايرة اللمس", self.calibrate))
        self.content.add_widget(actions)

        self.progress = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(5))
        self.content.add_widget(self.progress)
        self.status = Label(text="جاهز. اتبع الخطوات بالترتيب للبدء.", color=GREEN,
                            font_size="11sp", halign="right", valign="middle",
                            size_hint_y=None, height=dp(34))
        self.status.bind(size=lambda widget, *_: setattr(widget, "text_size", widget.size))
        self.content.add_widget(self.status)
        self._section("اقتراحات حساسياتك", "تُعرض اقتراحات كل منظار اعتمادًا على تسجيلات وضع التصويب المختار.")
        self.profile_result = Label(text="احفظ حساسياتك وحلّل تسجيلًا لعرض الاقتراحات هنا.",
                                    color=TEXT, font_size="11sp", halign="right", valign="top",
                                    size_hint_y=None, height=dp(100))
        self._fit_label(self.profile_result, dp(96))
        self.content.add_widget(self.profile_result)
        self._section("تفاصيل آخر تحليل", "النتائج تقديرية وتساعدك على التجربة؛ لا تضمن إصابة الرأس ولا تغيّر إعدادات اللعبة.")
        self.result = Label(text="لم يتم تحليل أي تسجيل بعد.", color=TEXT, font_size="11sp",
                            halign="right", valign="top", size_hint_y=None, height=dp(110))
        self._fit_label(self.result, dp(106))
        self.content.add_widget(self.result)

    @staticmethod
    def _fit_label(widget, minimum):
        widget.bind(width=lambda label, width: setattr(label, "text_size", (width, None)),
                    texture_size=lambda label, size: setattr(label, "height", max(minimum, size[1] + dp(8))))

    def _mode_key(self):
        return AIM_MODES.get(self.mode.text, "default")

    def _saved_values(self):
        profile = ffsens.load_data().get("profile", {})
        mode_profile = profile.get("aim_profiles", {}).get(self._mode_key(), {})
        saved = mode_profile or profile
        values = {scope: saved.get(scope, saved.get(key, ""))
                  for _title, scope, key, _description in SENSITIVITIES}
        values["free_look"] = saved.get("free_look", saved.get("sens_free_look", ""))
        return values

    def _mode_changed(self, *_):
        self.mode_help.text = MODE_HELP[self._mode_key()]
        for scope, field in self.inputs.items():
            field.text = str(self._saved_values().get(scope, ""))
        self._show_recommendations()

    def _values(self, require_all=True):
        values, missing = {}, []
        for scope, field in self.inputs.items():
            raw = field.text.strip()
            if not raw:
                if scope != "free_look":
                    missing.append(scope)
                continue
            try:
                number = float(raw)
            except ValueError:
                self._set_status("اكتب قيم الحساسية بالأرقام فقط.", error=True)
                return None
            if not 0 < number <= ffsens.MAX_SENS:
                self._set_status(f"يجب أن تكون قيمة الحساسية أكبر من صفر ولا تتجاوز {ffsens.MAX_SENS:g}.", error=True)
                return None
            values[scope] = number
        if require_all and missing:
            names = {scope: title for title, scope, _key, _description in SENSITIVITIES}
            self._set_status("أكمل قيم الحساسية التالية أولًا: " + "، ".join(names[key] for key in missing), error=True)
            return None
        return values

    def _set_status(self, text, error=False):
        self.status.text = text
        self.status.color = RED if error else GREEN

    def save_values(self, *_):
        values = self._values(require_all=True)
        if values is None:
            return
        data = ffsens.load_data()
        profile = data.setdefault("profile", {})
        mode_profile = profile.setdefault("aim_profiles", {}).setdefault(self._mode_key(), {})
        mode_profile.update(values)
        ffsens.save_data(data)
        self._set_status("تم حفظ حساسياتك لهذا الوضع على الجهاز.")
        self._show_recommendations()

    def _scope_key(self):
        return SCOPE_LABELS.get(self.scope.text, "general")

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
                                      filters=["*.mp4", "*.mkv", "*.mov", "*.avi", "*.webm"])
        box = BoxLayout(orientation="vertical", spacing=dp(7), padding=dp(7))
        box.add_widget(chooser)
        popup = Popup(title="اختر تسجيل المباراة", content=box, size_hint=(0.95, 0.9))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(7))
        row.add_widget(self._button("إلغاء", popup.dismiss))
        def select(*_args):
            if chooser.selection:
                self._accept_video(chooser.selection[0], os.path.basename(chooser.selection[0]))
                popup.dismiss()
        row.add_widget(self._button("استخدام هذا الفيديو", select, primary=True))
        box.add_widget(row)
        popup.open()

    def on_android_activity_result(self, request_code, result_code, data):
        if request_code != self.app.PICK_VIDEO_REQUEST or not data or data.getData() is None:
            return
        uri = data.getData()
        self._set_status("جارٍ استيراد الفيديو إلى التطبيق…")
        threading.Thread(target=self._copy_android_video, args=(uri,), daemon=True).start()

    def _copy_android_video(self, uri):
        try:
            from jnius import autoclass, jarray
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            resolver = activity.getContentResolver()
            name = "تسجيل المباراة.mp4"
            cursor = resolver.query(uri, jarray("java.lang.String")(["_display_name"]), None, None, None)
            if cursor and cursor.moveToFirst():
                index = cursor.getColumnIndex("_display_name")
                if index >= 0:
                    name = str(cursor.getString(index))
                cursor.close()
            ext = os.path.splitext(name)[1].lower()
            if ext not in (".mp4", ".mkv", ".mov", ".avi", ".3gp", ".webm"):
                ext = ".mp4"
            destination = os.path.join(self.app.user_data_dir, f"video_{uuid.uuid4().hex}{ext}")
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
            Clock.schedule_once(lambda _dt: self._accept_video(destination, name))
        except Exception as error:
            message = str(error)
            Clock.schedule_once(lambda _dt: self._set_status(f"تعذرت قراءة الفيديو: {message}", error=True))

    def _accept_video(self, path, name):
        self.video_path = path
        self.video_label.text = "الفيديو المختار: " + name
        self._set_status("تم اختيار الفيديو. تأكد من مطابقة وضع التصويب للتسجيل.")

    def analyze(self, *_):
        if self.busy:
            return
        values = self._values(require_all=False)
        if values is None:
            return
        sensitivity = values.get(self._scope_key())
        if sensitivity is None:
            self._set_status("أدخل قيمة الحساسية المختارة قبل التحليل.", error=True)
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو المباراة أولًا.", error=True)
            return
        args = Namespace(videos=[self.video_path], sens=sensitivity, scope=self._scope_key(),
                         aim_mode=self._mode_key(), cx=0.5, cy=0.5, head_offset=0.7,
                         max_minutes=0)
        self._run(ffsens.cmd_analyze, args)

    def calibrate(self, *_):
        if self.busy:
            return
        values = self._values(require_all=False)
        if values is None:
            return
        sensitivity = values.get(self._scope_key())
        if sensitivity is None:
            self._set_status("أدخل قيمة الحساسية المختارة قبل المعايرة.", error=True)
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو أولًا. للمعايرة، فعّل إظهار اللمسات أثناء التسجيل.", error=True)
            return
        args = Namespace(video=self.video_path, sens=sensitivity, scope=self._scope_key(),
                         aim_mode=self._mode_key(), max_minutes=0, button_size=0)
        self._run(ffsens.cmd_calibrate, args)

    def _run(self, function, args):
        if self.busy:
            return
        self.busy = True
        self.progress.value = 0.2
        self.result.text = "جارٍ التحليل. قد يستغرق ذلك بعض الوقت حسب مدة الفيديو."
        self._set_status("جارٍ معالجة التسجيل؛ اترك التطبيق مفتوحًا.")

        def work():
            output = io.StringIO()
            before_sessions = len(ffsens.load_data().get("sessions", []))
            try:
                with contextlib.redirect_stdout(output):
                    function(args)
                data = ffsens.load_data()
                for session in data.get("sessions", [])[before_sessions:]:
                    session["aim_mode"] = args.aim_mode
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
        for internal, arabic in (("general", "العامة"), ("reddot", "المنظار الأحمر"),
                                 ("2x", "منظار ٢×"), ("4x", "منظار ٤×"), ("awm", "القناص")):
            text = text.replace(internal, arabic)
        self.result.text = text + "\n\nتنبيه: التحليل تقديري ولا يضمن إصابة الرأس ولا يغيّر إعدادات اللعبة."
        self._set_status("اكتمل التحليل. راجع التفاصيل والاقتراحات.")
        self._show_recommendations()

    def _show_recommendations(self):
        values = self._values(require_all=False)
        if values is None:
            return
        sessions = [item for item in ffsens.load_data().get("sessions", [])
                    if item.get("aim_mode", "default") == self._mode_key()]
        lines = ["اقتراحات وضع التصويب: " + self.mode.text]
        for title, scope, _key, _description in SENSITIVITIES:
            current = values.get(scope)
            if current is None:
                lines.append(f"• {title}: أدخل قيمتك الحالية لعرض الاقتراح.")
                continue
            report = ffsens.build_report(sessions, scope, current)
            if report.get("gain") is None:
                lines.append(f"• {title}: احتفظ بقيمتك {current:g}؛ لا توجد بيانات كافية بعد.")
            elif report.get("enough") and report.get("keep"):
                lines.append(f"• {title}: القياس قريب من الهدف؛ اختبر القيمة الحالية {current:g}.")
            elif report.get("enough"):
                lines.append(f"• {title}: جرّب {report['suggested']:g} بدلًا من {current:g} في التدريب.")
            else:
                lines.append(f"• {title}: اقتراح أولي {report.get('suggested', current):g}؛ سجّل لعبًا أكثر.")
        lines.append("\nالتوصيات إرشادية؛ اختبر أي تغيير في ساحة التدريب أولًا.")
        self.profile_result.text = "\n".join(lines)


class FFApp(App):
    title = "محلل حساسية فري فاير"
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
