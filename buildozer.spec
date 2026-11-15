mkdir -p recipes/numpy

cat > buildozer.spec <<'EOF'
[app]

title = FF Sens Lab
package.name = ffsens
package.domain = org.jehadabulaaba

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,mp4

version = 1.0.0

requirements = python3==3.11.8,hostpython3==3.11.8,kivy,numpy,opencv

orientation = portrait

android.api = 34
android.minapi = 24
android.ndk = 25b
android.androidx = True
android.archs = arm64-v8a
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.accept_sdk_license = True

p4a.bootstrap = sdl2
p4a.local_recipes = recipes

[buildozer]
log_level = 2
warn_on_root = 1
EOF

cat > recipes/numpy/__init__.py <<'EOF'
from os.path import join
import shutil

from pythonforandroid.recipe import MesonRecipe, Recipe


class NumpyRecipe(MesonRecipe):
    version = "v2.3.0"
    url = "git+https://github.com/numpy/numpy"
    patches = ["fix-unordered-map.patch"]

    extra_build_args = [
        "-Csetup-args=-Dblas=none",
        "-Csetup-args=-Dlapack=none",
    ]
    opt_depends = ["libopenblas"]
    need_stl_shared = True
    min_ndk_api_support = 24

    def get_include(self, arch):
        return join(
            self.ctx.get_python_install_dir(arch.arch),
            "numpy/_core/include",
        )

    def get_recipe_meson_options(self, arch):
        options = super().get_recipe_meson_options(arch)
        options["properties"]["longdouble_format"] = (
            "IEEE_DOUBLE_LE"
            if arch.arch in ["armeabi-v7a", "x86"]
            else "IEEE_QUAD_LE"
        )
        return options

    def get_recipe_env(self, arch, **kwargs):
        env = super().get_recipe_env(arch, **kwargs)
        env["_PYTHON_HOST_PLATFORM"] = arch.command_prefix
        env["NPY_DISABLE_SVML"] = "1"

        env["TARGET_PYTHON_EXE"] = join(
            Recipe.get_recipe("python3", self.ctx).get_build_dir(arch.arch),
            "android-build",
            "python",
        )

        if "libopenblas" in self.ctx.recipe_build_order:
            blas_dir = join(
                Recipe.get_recipe("libopenblas", self.ctx).get_build_dir(
                    arch.arch
                ),
                "build",
            )
            env["CXXFLAGS"] += f" -I{blas_dir} -L{join(blas_dir, 'lib')}"

            self.extra_build_args = [
                "-Csetup-args=-Dblas=auto",
                "-Csetup-args=-Dlapack=auto",
                "-Csetup-args=-Dallow-noblas=False",
            ]

        return env

    def get_hostrecipe_env(self, arch=None):
        env = super().get_hostrecipe_env(arch=arch)
        env["RANLIB"] = shutil.which("ranlib")
        return env


recipe = NumpyRecipe()
EOF

cat > recipes/numpy/fix-unordered-map.patch <<'EOF'
diff --git a/numpy/_core/src/multiarray/unique.cpp b/numpy/_core/src/multiarray/unique.cpp
--- a/numpy/_core/src/multiarray/unique.cpp
+++ b/numpy/_core/src/multiarray/unique.cpp
@@ -4,6 +4,7 @@
 #include <Python.h>
 
 #include <unordered_set>
+#include <unordered_map>
 #include <functional>
 
 #include <numpy/npy_common.h>
EOF
