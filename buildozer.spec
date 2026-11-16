[app]

title = FF Sens Lab
package.name = ffsens
package.domain = org.jehadabulaaba

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,mp4

version = 1.0.0

# Build NumPy with the local python-for-android recipe (not a PyPI wheel).
requirements = python3==3.11.8,hostpython3==3.11.8,kivy,numpy,opencv

orientation = portrait

android.api = 35
android.minapi = 24
android.ndk = 25b
android.androidx = True
# Build for 32-bit ARM devices.
android.archs = armeabi-v7a
android.permissions = READ_MEDIA_VIDEO,READ_EXTERNAL_STORAGE
android.accept_sdk_license = True

p4a.bootstrap = sdl2
p4a.local_recipes = recipes

[buildozer]
log_level = 2
warn_on_root = 1
