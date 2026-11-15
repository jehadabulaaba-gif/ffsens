[app]

title = FF Sens Lab
package.name = ffsens
package.domain = org.jehadabulaaba

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,mp4

version = 1.0.0

# FIX: pin to a compatible Python version for Android
requirements = python3==3.11.8,hostpython3==3.11.8,kivy,numpy,opencv

orientation = portrait

android.api = 35
android.minapi = 24
android.ndk = 25b
android.androidx = True
android.architectures = arm64-v8a,armeabi-v7a
android.permissions = READ_MEDIA_VIDEO,READ_EXTERNAL_STORAGE
android.accept_sdk_license = True

p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1
