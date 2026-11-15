# -*- coding: utf-8 -*-
"""واجهة Kivy لأداة ffsens.py - ضعها بجانب ffsens.py في نفس المجلد."""
import contextlib
import io
import os
import threading
from argparse import Namespace

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

import ffsens


def ask_permissions():
    try:
        from android.permissions import Permission, request_permissions
        request_permissions([Permission.READ_EXTERNAL_STORAGE,
                             Permission.WRITE_EXTERNAL_STORAGE,
                             "android.permission.READ_MEDIA_VIDEO"])
    except Exception:
        pass  # لسنا على أندرويد


class Root(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=8, spacing=6, **kw)
        self.path = TextInput(hint_text="مسار الفيديو /storage/emulated/0/Movies/a.mp4",
                              multiline=False, size_hint_y=None, height=90)
        self.sens = TextInput(hint_text="الحساسية الحالية (1-100)", text="59",
                              multiline=False, input_filter="float",
                              size_hint_y=None, height=90)
        self.btn = TextInput(hint_text="حجم زر النار % من ارتفاع الشاشة (مثال 14)",
                             multiline=False, input_filter="float",
                             size_hint_y=None, height=90)
        self.scope = Spinner(text="general",
                             values=("general", "reddot", "2x", "4x", "awm"),
                             size_hint_y=None, height=90)
        for w in (self.path, self.sens, self.btn, self.scope):
            self.add_widget(w)
        row = BoxLayout(size_hint_y=None, height=110, spacing=6)
        for name, fn in (("تحليل قتال", self.do_analyze), ("معايرة", self.do_calib),
                         ("التوصية", self.do_plan)):
            row.add_widget(Button(text=name, on_release=fn))
        self.add_widget(row)
        self.out = Label(text="جاهز.", size_hint_y=None, halign="right",
                         valign="top", markup=False)
        self.out.bind(width=lambda *_: setattr(self.out, "text_size", (self.out.width, None)),
                      texture_size=lambda *_: setattr(self.out, "height", self.out.texture_size[1]))
        sv = ScrollView()
        sv.add_widget(self.out)
        self.add_widget(sv)

    def _sens(self):
        try:
            v = float(self.sens.text)
        except ValueError:
            return None
        return v if 0 < v <= ffsens.MAX_SENS else None

    def _run(self, fn, args):
        self.out.text = "جاري العمل... قد يستغرق دقائق، لا تغلق التطبيق."

        def work():
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    fn(args)
            except SystemExit as e:
                buf.write(str(e))
            except Exception as e:
                buf.write(f"خطأ: {e}")
            Clock.schedule_once(lambda _dt: setattr(self.out, "text", buf.getvalue() or "تم."))
        threading.Thread(target=work, daemon=True).start()

    def do_analyze(self, *_):
        s = self._sens()
        if s is None or not os.path.exists(self.path.text.strip()):
            self.out.text = "تأكد من المسار ومن الحساسية (1-100)."
            return
        self._run(ffsens.cmd_analyze, Namespace(
            videos=[self.path.text.strip()], sens=s, scope=self.scope.text,
            cx=0.5, cy=0.5, head_offset=0.7, max_minutes=0))

    def do_calib(self, *_):
        s = self._sens()
        if s is None or not os.path.exists(self.path.text.strip()):
            self.out.text = "تأكد من المسار ومن الحساسية (1-100)."
            return
        try:
            b = float(self.btn.text) if self.btn.text else 0
        except ValueError:
            b = 0
        self._run(ffsens.cmd_calibrate, Namespace(
            video=self.path.text.strip(), sens=s, scope=self.scope.text,
            max_minutes=0, button_size=b))

    def do_plan(self, *_):
        s = self._sens()
        if s is None:
            self.out.text = "أدخل الحساسية الحالية."
            return
        self._run(ffsens.cmd_plan, Namespace(sens=s, scope=self.scope.text))


class FFApp(App):
    title = "FF Sens Lab"

    def build(self):
        ffsens.DATA_FILE = os.path.join(self.user_data_dir, "ffsens_data.json")
        ask_permissions()
        return Root()


if __name__ == "__main__":
    FFApp().run()
