# -*- coding: utf-8 -*-
"""واجهة هاتف عربية لتحليل فيديوهات اللعب باستخدام ffsens.py."""
import contextlib
import io
import os
import threading
from argparse import Namespace

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

import ffsens


class Root(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=12, spacing=8, **kw)
        self.path = TextInput(
            hint_text="اختر فيديو اللعب أو أدخل مساره",
            multiline=False, size_hint_y=None, height=48,
        )
        self.sens = TextInput(
            hint_text="الحساسية الحالية (1–100)", text="59",
            multiline=False, input_filter="float", size_hint_y=None, height=48,
        )
        self.btn = TextInput(
            hint_text="حجم زر النار % (اختياري للمعايرة)",
            multiline=False, input_filter="float", size_hint_y=None, height=48,
        )
        self.scope = Spinner(
            text="general",
            values=("general", "reddot", "2x", "4x", "awm"),
            size_hint_y=None, height=48,
        )
        self.add_widget(Label(
            text="FF Sens Lab\nحلّل فيديو لعبك واحصل على توصية للحساسية",
            size_hint_y=None, height=72, halign="center", valign="middle",
        ))

        video_row = BoxLayout(size_hint_y=None, height=48, spacing=6)
        video_row.add_widget(self.path)
        video_row.add_widget(Button(text="اختيار فيديو", size_hint_x=None,
                                    width=120, on_release=self.choose_video))
        self.add_widget(video_row)
        self.add_widget(self.sens)
        self.add_widget(self.scope)
        self.add_widget(self.btn)

        actions = BoxLayout(size_hint_y=None, height=52, spacing=6)
        for title, callback in (
            ("تحليل القتال", self.do_analyze),
            ("معايرة", self.do_calib),
            ("التوصية", self.do_plan),
        ):
            actions.add_widget(Button(text=title, on_release=callback))
        self.add_widget(actions)

        self.out = Label(text="اختر فيديو ثم ابدأ التحليل.", size_hint_y=None,
                         halign="right", valign="top", markup=False)
        self.out.bind(
            width=lambda *_: setattr(self.out, "text_size", (self.out.width, None)),
            texture_size=lambda *_: setattr(self.out, "height", max(100, self.out.texture_size[1])),
        )
        scroll = ScrollView()
        scroll.add_widget(self.out)
        self.add_widget(scroll)

    def choose_video(self, *_):
        start = "/storage/emulated/0" if os.path.isdir("/storage/emulated/0") else os.path.expanduser("~")
        chooser = FileChooserListView(path=start, filters=["*.mp4", "*.mkv", "*.mov", "*.avi"])
        buttons = BoxLayout(size_hint_y=None, height=48, spacing=8)
        popup = Popup(title="اختر فيديو اللعب", content=BoxLayout(orientation="vertical"),
                      size_hint=(0.95, 0.9))
        content = popup.content
        content.add_widget(chooser)
        content.add_widget(buttons)
        buttons.add_widget(Button(text="إلغاء", on_release=popup.dismiss))

        def select_file(*_):
            if chooser.selection:
                self.path.text = chooser.selection[0]
                popup.dismiss()

        buttons.add_widget(Button(text="اختيار", on_release=select_file))
        popup.open()

    def _sens(self):
        try:
            value = float(self.sens.text)
        except ValueError:
            return None
        return value if 0 < value <= ffsens.MAX_SENS else None

    def _run(self, fn, args):
        self.out.text = "جارٍ العمل… قد يستغرق التحليل دقائق. لا تغلق التطبيق."

        def work():
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output):
                    fn(args)
            except SystemExit as error:
                output.write(str(error))
            except Exception as error:
                output.write(f"حدث خطأ: {error}")
            result = output.getvalue() or "اكتملت العملية."
            Clock.schedule_once(lambda _dt: setattr(self.out, "text", result))

        threading.Thread(target=work, daemon=True).start()

    def _video_and_sens(self):
        path = self.path.text.strip()
        sens = self._sens()
        if sens is None:
            self.out.text = "أدخل حساسية صحيحة بين 1 و100."
            return None
        if not path or not os.path.isfile(path):
            self.out.text = "اختر ملف فيديو موجوداً على الجهاز أولاً."
            return None
        return path, sens

    def do_analyze(self, *_):
        values = self._video_and_sens()
        if values is None:
            return
        path, sens = values
        self._run(ffsens.cmd_analyze, Namespace(
            videos=[path], sens=sens, scope=self.scope.text,
            cx=0.5, cy=0.5, head_offset=0.7, max_minutes=0,
        ))

    def do_calib(self, *_):
        values = self._video_and_sens()
        if values is None:
            return
        path, sens = values
        try:
            button_size = float(self.btn.text) if self.btn.text else 0
        except ValueError:
            self.out.text = "حجم زر النار يجب أن يكون رقماً."
            return
        self._run(ffsens.cmd_calibrate, Namespace(
            video=path, sens=sens, scope=self.scope.text,
            max_minutes=0, button_size=button_size,
        ))

    def do_plan(self, *_):
        sens = self._sens()
        if sens is None:
            self.out.text = "أدخل حساسية صحيحة بين 1 و100."
            return
        self._run(ffsens.cmd_plan, Namespace(sens=sens, scope=self.scope.text))


class FFApp(App):
    title = "FF Sens Lab"

    def build(self):
        ffsens.DATA_FILE = os.path.join(self.user_data_dir, "ffsens_data.json")
        try:
            from android.permissions import request_permissions
            request_permissions([
                "android.permission.READ_MEDIA_VIDEO",
                "android.permission.READ_EXTERNAL_STORAGE",
            ])
        except Exception:
            pass  # تشغيل سطح المكتب لا يحتاج صلاحيات أندرويد.
        return Root()


if __name__ == "__main__":
    FFApp().run()
