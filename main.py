# -*- coding: utf-8 -*-
"""FF Sens Lab — Free Fire sensitivity helper with separate aim-precision profiles."""
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

# Full in-game precision modes. These are labels for organizing the user's own
# recordings, not a way for this app to modify Free Fire or Aim Assist.
AIM_MODES = {
    "افتراضي (Default)": "default",
    "دقيق عند المنظار (Precise on Scope)": "precise_on_scope",
    "تحكم كامل (Full Control)": "full_control",
}
AIM_SCOPES = (
    ("الحساسية العامة", "general", "sens_general"),
    ("ريد دوت", "reddot", "sens_reddot"),
    ("منظار 2x", "2x", "sens_2x"),
    ("منظار 4x", "4x", "sens_4x"),
    ("قناص / AWM", "awm", "sens_awm"),
)
# Free Look is shown and saved as a game setting, but not used to calculate
# aiming recommendations because it controls looking around rather than aiming.
FREE_LOOK_KEY = "sens_free_look"


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
        super().__init__(orientation="vertical", padding=[dp(11), dp(8)], spacing=dp(5),
                         size_hint_y=None, height=dp(82), **kwargs)
        self.add_widget(Label(text=title, color=MUTED, font_size="12sp",
                              halign="right", valign="middle", size_hint_y=None, height=dp(22)))
        self.input = TextInput(text=str(value), hint_text="القيمة الحالية 1–100",
                               multiline=False, input_filter="float", keyboard_type="number",
                               size_hint_y=None, height=dp(40), font_size="16sp",
                               foreground_color=TEXT, cursor_color=CYAN,
                               background_normal="", background_active="",
                               background_color=(0.045, 0.065, 0.10, 1), padding=[dp(9), dp(8)])
        self.add_widget(self.input)


class Root(BoxLayout):
    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", padding=[dp(14), dp(10)], spacing=dp(9), **kwargs)
        self.app = app
        self.video_path = ""
        self.busy = False
        self.value_inputs = {}
        self._loading_mode = False
        with self.canvas.before:
            Color(*BG)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)
        self._header()
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(3), scroll_type=["bars", "content"])
        self.content = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        self.content.bind(minimum_height=self.content.setter("height"))
        scroll.add_widget(self.content)
        self.add_widget(scroll)
        self._dashboard()

    def _update_bg(self, *_):
        self._bg_rect.pos, self._bg_rect.size = self.pos, self.size

    def _header(self):
        header = Panel(orientation="horizontal", size_hint_y=None, height=dp(58),
                       spacing=dp(10), padding=[dp(12), dp(6)], background=PANEL_ALT)
        logo = Label(text="FF", size_hint_x=None, width=dp(44), bold=True,
                     font_size="18sp", color=(0.02, 0.07, 0.09, 1))
        with logo.canvas.before:
            Color(*CYAN)
            logo._logo_bg = RoundedRectangle(pos=logo.pos, size=logo.size, radius=[dp(10)])
        logo.bind(pos=lambda w, *_: setattr(w._logo_bg, "pos", w.pos),
                  size=lambda w, *_: setattr(w._logo_bg, "size", w.size))
        header.add_widget(logo)
        brand = BoxLayout(orientation="vertical")
        brand.add_widget(Label(text="FF Sens Lab", color=TEXT, bold=True,
                               font_size="18sp", halign="right", valign="middle"))
        brand.add_widget(Label(text="مساعد إعداد الحساسية في Free Fire", color=MUTED,
                               font_size="11sp", halign="right", valign="middle"))
        header.add_widget(brand)
        self.add_widget(header)

    def _dashboard(self):
        self._section("لوحة التحكم", "افتراضي وPrecise on Scope وFull Control أوضاع مختلفة؛ اختر الوضع الذي استخدمته في الفيديو.")
        intro = Panel(orientation="vertical", padding=dp(13), spacing=dp(6),
                      size_hint_y=None, height=dp(112), background=PANEL_ALT)
        intro.add_widget(Label(text="اقتراحات منفصلة لكل وضع تصويب", color=TEXT,
                               font_size="17sp", bold=True, halign="right", valign="middle"))
        intro.add_widget(Label(text="التطبيق يحلل تسجيلك بعد المباراة فقط. لا يغيّر اللعبة ولا يشغّل التصويب المساعد.",
                               color=MUTED, font_size="12sp", halign="right", valign="middle"))
        self.content.add_widget(intro)

        self._section("١ — اختر وضع التصويب الذي استخدمته", "من إعدادات Free Fire، ثم اختر الوضع نفسه هنا قبل تحليل فيديوهاته.")
        self.mode = Spinner(text="افتراضي (Default)", values=tuple(AIM_MODES),
                            size_hint_y=None, height=dp(44), font_size="13sp")
        self.mode.bind(text=self._mode_changed)
        self.content.add_widget(self.mode)
        self.mode_note = Label(text=self._mode_explanation(), color=MUTED, font_size="11sp",
                               size_hint_y=None, height=dp(40), halign="right", valign="middle")
        self.mode_note.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        self.content.add_widget(self.mode_note)

        self._section("٢ — قيم الحساسية الحالية", "أدخل أرقامك كما تظهر في اللعبة. القناص / AWM إعداد واحد هنا.")
        saved = self._saved_values_for_mode()
        grid = GridLayout(cols=2, spacing=dp(7), size_hint_y=None,
                          height=dp(6 * 82 + 5 * 7))
        for title, scope, key in AIM_SCOPES:
            card = ValueCard(title, saved.get(scope, ""))
            self.value_inputs[scope] = card.input
            grid.add_widget(card)
        free_card = ValueCard("النظر الحر (Free Look)", saved.get("free_look", ""))
        self.value_inputs["free_look"] = free_card.input
        grid.add_widget(free_card)
        self.content.add_widget(grid)
        self.content.add_widget(self._button("حفظ القيم الحالية لهذا الوضع", self.save_values))

        self._section("٣ — اختر تسجيل لعب", "يفضل فيديو أفقي واضح يتضمن عدة اشتباكات. التحليل لا يعرف نية اللاعب أو يضمن إصابة الرأس.")
        video = Panel(orientation="vertical", padding=dp(12), spacing=dp(6),
                      size_hint_y=None, height=dp(86))
        video.add_widget(self._button("اختيار فيديو من الهاتف", self.pick_video, primary=True))
        self.video_label = Label(text="لم يتم اختيار فيديو", color=MUTED, font_size="11sp",
                                 halign="right", valign="middle", size_hint_y=None, height=dp(22))
        video.add_widget(self.video_label)
        self.content.add_widget(video)
        controls = Panel(orientation="vertical", padding=dp(12), spacing=dp(7),
                         size_hint_y=None, height=dp(105))
        self.scope = Spinner(text="العامة", values=("العامة", "ريد دوت", "منظار 2x", "منظار 4x", "قناص / AWM"),
                             size_hint_y=None, height=dp(40), font_size="13sp")
        controls.add_widget(self.scope)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(7))
        row.add_widget(self._button("حلّل الفيديو", self.analyze, primary=True))
        row.add_widget(self._button("معايرة اللمس", self.calibrate))
        controls.add_widget(row)
        self.content.add_widget(controls)
        self.progress = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(4))
        self.content.add_widget(self.progress)
        self.status = Label(text="جاهز. ابدأ باختيار وضع التصويب وإدخال قيمك.",
                            color=GREEN, font_size="12sp", halign="right", valign="middle",
                            size_hint_y=None, height=dp(36))
        self.content.add_widget(self.status)

        self._section("ملخص هذا الوضع", "لن نخلط نتائج Default بنتائج Full Control؛ لكل وضع بياناته واقتراحاته الخاصة.")
        summary = GridLayout(cols=2, spacing=dp(7), size_hint_y=None, height=dp(132))
        self.stat_gain = self._stat("مؤشر السحب", "—")
        self.stat_count = self._stat("محاولات مفيدة", "—")
        self.stat_recommendation = self._stat("اقتراح", "—")
        self.stat_confidence = self._stat("موثوقية", "بانتظار البيانات")
        for item in (self.stat_gain, self.stat_count, self.stat_recommendation, self.stat_confidence):
            summary.add_widget(item)
        self.content.add_widget(summary)
        self.result_panel = Panel(orientation="vertical", padding=dp(12), spacing=dp(5),
                                  size_hint_y=None, height=dp(190))
        self.result = Label(text="النتيجة ستظهر هنا بعد تحليل الفيديو.", color=TEXT,
                            font_size="12sp", halign="right", valign="top")
        self.result.bind(width=lambda w, width: setattr(w, "text_size", (width, None)),
                         texture_size=lambda w, size: setattr(w, "height", max(dp(150), size[1] + dp(8))))
        self.result_panel.add_widget(self.result)
        self.content.add_widget(self.result_panel)
        caution = Panel(orientation="vertical", padding=dp(11), spacing=dp(4),
                        size_hint_y=None, height=dp(105), background=PANEL_ALT)
        caution.add_widget(Label(text="مهم", color=CYAN, bold=True, font_size="13sp",
                                 halign="right", valign="middle"))
        caution.add_widget(Label(text="المساعدة على التصويب تختلف باختلاف الوضع، لكن التطبيق لا يستطيع قياسها بدقة من الفيديو وحده. لا يوجد إعداد يضمن الهيدشوت؛ اختبر أي تغيير في التدريب وبخطوات صغيرة.",
                                 color=MUTED, font_size="10sp", halign="right", valign="top"))
        self.content.add_widget(caution)

    def _section(self, title, subtitle):
        box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(48), spacing=dp(1))
        box.add_widget(Label(text=title, color=TEXT, bold=True, font_size="15sp", halign="right", valign="middle"))
        box.add_widget(Label(text=subtitle, color=MUTED, font_size="9sp", halign="right", valign="middle"))
        self.content.add_widget(box)

    def _stat(self, title, value):
        card = Panel(orientation="vertical", padding=[dp(9), dp(6)], spacing=dp(2),
                     size_hint_y=None, height=dp(62))
        card.add_widget(Label(text=title, color=MUTED, font_size="10sp", halign="right", valign="middle"))
        value_label = Label(text=value, color=CYAN, bold=True, font_size="13sp", halign="right", valign="middle")
        card.add_widget(value_label)
        card.value_label = value_label
        return card

    def _button(self, text, callback, primary=False):
        button = Button(text=text, size_hint_y=None, height=dp(43), font_size="12sp", bold=primary,
                        color=(0.02, 0.07, 0.09, 1) if primary else TEXT,
                        background_normal="", background_down="",
                        background_color=CYAN if primary else PANEL_ALT)
        button.bind(on_release=callback)
        return button

    def _mode_key(self):
        return AIM_MODES.get(self.mode.text, "default")

    def _mode_explanation(self):
        key = AIM_MODES.get(self.mode.text, "default")
        explanations = {
            "default": "Default: وضع اللعبة الافتراضي للمساعدة على التصويب؛ نسجّل نتائجه منفصلة.",
            "precise_on_scope": "Precise on Scope: اختره فقط إذا كان هذا هو وضعك داخل اللعبة.",
            "full_control": "Full Control: تحكم يدوي أكبر؛ سجّل وحلّل فيديوهات هذا الوضع وحده.",
        }
        return explanations[key]

    def _mode_changed(self, *_):
        if not hasattr(self, "mode_note"):
            return
        self.mode_note.text = self._mode_explanation()
        saved = self._saved_values_for_mode()
        for scope, field in self.value_inputs.items():
            field.text = str(saved.get(scope, ""))
        self._refresh_summary()

    def _saved_values_for_mode(self):
        data = ffsens.load_data()
        profile = data.get("profile", {})
        mode_profile = profile.get("aim_profiles", {}).get(self._mode_key(), {})
        if not mode_profile:
            mode_profile = profile
        values = {}
        for _title, scope, key in AIM_SCOPES:
            values[scope] = mode_profile.get(scope, mode_profile.get(key, ""))
        values["free_look"] = mode_profile.get("free_look", mode_profile.get(FREE_LOOK_KEY, ""))
        return values

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
                self._set_status("كل قيم الحساسية يجب أن تكون أرقامًا.", error=True)
                return None
            if not 0 < number <= ffsens.MAX_SENS:
                self._set_status("قيم الحساسية يجب أن تكون بين 1 و100.", error=True)
                return None
            values[scope] = number
        if require_all and missing:
            labels = {"general": "العامة", "reddot": "ريد دوت", "2x": "2x", "4x": "4x", "awm": "القناص/AWM", "free_look": "النظر الحر"}
            self._set_status("أدخل القيم الحالية أولًا: " + "، ".join(labels[item] for item in missing), error=True)
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
        profiles = profile.setdefault("aim_profiles", {})
        profiles[self._mode_key()] = dict(values)
        ffsens.save_data(data)
        self._set_status("حُفظت القيم لهذا الوضع فقط؛ لن تختلط مع بيانات أوضاع التصويب الأخرى.")

    def _scope_key(self):
        return {"العامة": "general", "ريد دوت": "reddot", "منظار 2x": "2x",
                "منظار 4x": "4x", "قناص / AWM": "awm"}.get(self.scope.text, "general")

    def _current_sensitivity(self):
        values = self._values(require_all=False)
        return None if values is None else values.get(self._scope_key())

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
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(7))
        content.add_widget(actions)
        actions.add_widget(self._button("إلغاء", popup.dismiss))
        def select(*_args):
            if chooser.selection:
                self._set_video(chooser.selection[0], os.path.basename(chooser.selection[0]))
                popup.dismiss()
        actions.add_widget(self._button("اختيار", select, primary=True))
        popup.open()

    def on_android_activity_result(self, request_code, result_code, data):
        if request_code == self.app.PICK_VIDEO_REQUEST and data and data.getData() is not None:
            self._set_status("جارٍ استيراد الفيديو…")
            threading.Thread(target=self._copy_video_uri, args=(data.getData(),), daemon=True).start()
        elif request_code == self.app.PICK_VIDEO_REQUEST:
            self._set_status("لم يتم اختيار فيديو.")

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
        self.video_label.text = "الفيديو: " + name
        self._set_status("تم اختيار الفيديو. تأكد أن وضع اللعبة المختار يطابق التسجيل.")

    def analyze(self, *_):
        if self.busy:
            return
        sens = self._current_sensitivity()
        if sens is None:
            self._set_status("أدخل قيمة الحساسية لهذا المنظار بين 1 و100.", error=True)
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو محفوظًا على الهاتف أولًا.", error=True)
            return
        self._run(ffsens.cmd_analyze, Namespace(
            videos=[self.video_path], sens=sens, scope=self._scope_key(),
            aim_mode=self._mode_key(), cx=0.5, cy=0.5, head_offset=0.7, max_minutes=0))

    def calibrate(self, *_):
        if self.busy:
            return
        sens = self._current_sensitivity()
        if sens is None:
            self._set_status("أدخل قيمة الحساسية لهذا المنظار بين 1 و100.", error=True)
            return
        if not self.video_path or not os.path.isfile(self.video_path):
            self._set_status("اختر فيديو أولًا. المعايرة تتطلب تفعيل إظهار اللمسات أثناء التسجيل.", error=True)
            return
        self._run(ffsens.cmd_calibrate, Namespace(video=self.video_path, sens=sens,
                  scope=self._scope_key(), aim_mode=self._mode_key(), max_minutes=0, button_size=0))

    def _run(self, fn, args):
        if self.busy:
            return
        self.busy = True
        self.progress.value = 0.3
        self.result.text = "جارٍ تحليل التسجيل…"
        self._set_status("جارٍ التحليل. أبقِ التطبيق مفتوحًا؛ قد تستغرق معالجة الفيديو دقائق.")
        def work():
            output = io.StringIO()
            try:
                before = len(ffsens.load_data().get("sessions", []))
                with contextlib.redirect_stdout(output):
                    fn(args)
                if hasattr(args, "videos"):
                    data = ffsens.load_data()
                    for session in data.get("sessions", [])[before:]:
                        session["aim_mode"] = args.aim_mode
                    ffsens.save_data(data)
                text = output.getvalue().strip() or "اكتملت العملية."
            except SystemExit as error:
                text = str(error) or "تعذر إكمال العملية."
            except Exception as error:
                text = f"حدث خطأ أثناء التحليل:\n{error}"
            Clock.schedule_once(lambda _dt: self._finish(text, args))
        threading.Thread(target=work, daemon=True).start()

    def _finish(self, text, args):
        self.busy = False
        self.progress.value = 1
        self.result.text = self._friendly_result(text)
        self._set_status("اكتملت العملية. راجع ملخص وضع التصويب المختار.")
        self._refresh_summary()

    @staticmethod
    def _friendly_result(text):
        replacements = {
            "النتيجة -": "نتيجة التحليل —", "مدة التحليل:": "مدة الفيديو:",
            "سحبات صالحة:": "محاولات مفيدة:", "التوصية:": "اقتراح تجريبي:",
            "لا توجد بيانات كافية:": "لا توجد بيانات كافية بعد:",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text + "\n\nهذا قياس تقريبي من الفيديو، ولا يضمن إصابة الرأس أو يغيّر إعداد اللعبة."

    def _refresh_summary(self):
        try:
            mode = self._mode_key()
            mode_sessions = [s for s in ffsens.load_data().get("sessions", [])
                             if s.get("aim_mode") == mode]
            scope = self._scope_key()
            sens = self._current_sensitivity()
            if sens is None:
                return
            report = ffsens.build_report(mode_sessions, scope, sens)
            self.stat_count.value_label.text = str(report.get("valid", 0))
            gain = report.get("gain")
            self.stat_gain.value_label.text = "—" if gain is None else f"{gain:.2f}×"
            if gain is None:
                self.stat_recommendation.value_label.text = "حلّل فيديو لهذا الوضع"
                self.stat_confidence.value_label.text = "لا توجد بيانات"
            else:
                suggested = report.get("suggested", sens)
                self.stat_recommendation.value_label.text = f"جرّب {suggested:g}" if not report.get("keep") else f"أبقِ {sens:g}"
                self.stat_confidence.value_label.text = "أفضل" if report.get("enough") else "مبدئي"
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
