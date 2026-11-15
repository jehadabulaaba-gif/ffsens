[app]

# (str) Title of your application
title = My Application

# (str) Package name
package.name = myapp

# (str) Package domain (needed for android packaging)
package.domain = org.test

# (list) Source files to include (let it empty to include all files)
source.include_exts = py,png,jpg,kv,atlas

# (list) Application requirements
# أضف مكتباتك هنا مثل kivy, python3 إلخ
requirements = python3,kivy

# (str) Supported orientations
orientation = portrait

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK will support
android.minapi = 24

# (str) Android NDK version to use (تم إصلاح المشكلة هنا وتثبيته على الإصدار المتوافق تماماً)
android.ndk = 25b

# (bool) Enable AndroidX support
android.androidx = True

# (str) Supported architectures
android.architectures = armeabi-v7a, arm64-v8a

# (bool) Automatically accept SDK license
android.accept_sdk_license = True

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug)
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
