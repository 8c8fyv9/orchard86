#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# 从本地已检出的 reims-vgpu 源码树构建 libreims_vgpu_c.so，并校验其导出符号与
# graphics/include/reims_vgpu.h（项目自维护图形 ABI）一致，同时生成 reims-vgpu.pc。
set -eu

fail() { printf 'graphics/build.sh: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -ne 0 ] || fail '请勿以 root 身份运行'
[ "$#" = 2 ] || fail '用法: graphics/build.sh REIMS_SRC_DIR NEW_OUT_DIR'

case "$1" in /*) ;; *) fail 'REIMS_SRC_DIR 必须是绝对路径';; esac
case "$2" in /*) ;; *) fail 'NEW_OUT_DIR 必须是绝对路径';; esac

src_dir=$(CDPATH='' cd -P -- "$1" && pwd) || fail '无效的 REIMS_SRC_DIR'
module=$(CDPATH='' cd -P -- "$(dirname -- "$0")" && pwd)
[ -f "$src_dir/Cargo.toml" ] || fail 'REIMS_SRC_DIR 缺少 Cargo.toml'

parent=$(CDPATH='' cd -P -- "$(dirname -- "$2")" && pwd) || fail 'OUT_DIR 父目录必须已存在'
out_dir=${parent%/}/$(basename -- "$2")
mkdir -- "$out_dir" || fail 'OUT_DIR 必须尚不存在'

for tool in cargo readelf; do
    command -v "$tool" >/dev/null || fail "缺少构建工具: $tool"
done

export CARGO_TARGET_DIR="$out_dir/target"
export CARGO_FEATURE_SDL_UNIX_CONSOLE_BUILD="${CARGO_FEATURE_SDL_UNIX_CONSOLE_BUILD:-1}"
(
    cd "$src_dir"
    cargo build --locked --release -p reims-vgpu-c --no-default-features --features vulkan
) > "$out_dir/cargo.log" 2>&1 || fail "编译失败，详见 $out_dir/cargo.log"

lib_path="$CARGO_TARGET_DIR/release/libreims_vgpu_c.so"
[ -f "$lib_path" ] || fail "未生成 $lib_path"

# 校验项目自维护 ABI 的核心符号（VMApple APV MMIO + IOSurface + FrameTarget）
for sym in rvg_device_create rvg_iosurface_device_create rvg_display_create rvg_frame_target_create rvg_display_encode_frame; do
    readelf --dyn-syms --wide "$lib_path" | grep -qE "[[:space:]]${sym}$" || fail "ABI 符号缺失（与 graphics/include/reims_vgpu.h 不匹配）: $sym"
done

cat > "$out_dir/reims-vgpu.pc" <<EOF
Name: reims-vgpu
Description: project-maintained VMApple Reims C ABI backend
Version: 0.1.0
Cflags: -I$module/include
Libs: -L$CARGO_TARGET_DIR/release -lreims_vgpu_c -Wl,-rpath,$CARGO_TARGET_DIR/release
EOF

printf '%s\n' "$out_dir/reims-vgpu.pc"
