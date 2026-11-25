#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
set -eu

fail() { printf 'qemu/build.sh: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -ne 0 ] || fail '请勿以 root 身份运行'
[ "$(uname -s):$(uname -m)" = Linux:x86_64 ] || fail '需要 x86-64 Linux 环境'

enable_reims=1
enable_accel=1
mode=build
reims_pc_dir=

while [ "$#" -gt 0 ]; do
    case "$1" in
        --verify) mode=verify; shift ;;
        --no-reims) enable_reims=0; shift ;;
        --no-accel) enable_accel=0; shift ;;
        --reims-pc-dir)
            [ "$#" -ge 2 ] || fail '--reims-pc-dir 需要路径参数'
            reims_pc_dir=$2
            shift 2
            ;;
        --) shift; break ;;
        -*) fail "未知选项: $1" ;;
        *) break ;;
    esac
done

if [ "$mode" = verify ]; then
    [ "$#" = 1 ] || fail '用法: qemu/build.sh [--no-reims] [--no-accel] --verify SOURCE_DIR'
else
    [ "$#" = 2 ] || fail '用法: qemu/build.sh [--no-reims] [--no-accel] [--reims-pc-dir DIR] SOURCE_DIR NEW_BUILD_DIR'
fi

case "$1" in /*) ;; *) fail 'SOURCE_DIR 必须是绝对路径';; esac
source_dir=$(CDPATH='' cd -P -- "$1" && pwd) || fail '无效的源码目录'
module=$(CDPATH='' cd -P -- "$(dirname -- "$0")" && pwd)

commit=509a4ce52bc703dfc79eb8b4283f51acd88b8594
tree=a0d5ec2a47cbfa85072876df96d8e208a433b288

patch_manifest() {
    cat <<'EOF'
a4746485e5823ebf06496877b32de669bac637c66a73e9e0c322f7cc31846281  01-vmapple-base/0001-vmapple-runtime-usb.patch
9e405e3f21556edc162c2f3aa75a183891daaa925158bb558bc5444625d91d9a  01-vmapple-base/0002-vmapple-bdif-usb.patch
6f87657727fe0a56a50e8a1c251d6e1a9c497cee5f8376fae02a8204cb1d7af4  01-vmapple-base/0003-vmapple-disk-discard.patch
e06d73154bf9f462895f24e5887acb4a973d281b77f3672d2e5f38c29628754e  01-vmapple-base/0004-vmapple-recovery-shared-page.patch
852a9b21ebeeeb510108b35fa9ab538acb3ada3075620f9f21de06d3aa43b77d  01-vmapple-base/0005-vmapple-recovery-rtc.patch
742ebabb2a6f377ff09111269752e14c2497226ee73e55d42a25c8bfe485f1e1  01-vmapple-base/0006-vmapple-protection-msi.patch
178106e385f4aa3c579f3ae9fb54911de8c48fd5db19356d28cb1567b2013a3b  01-vmapple-base/0007-vmapple-arm-recovery-init.patch
b3c492b9966f3bc53aa2c034ffc08004edc748605661a3fad64286afa84f293b  01-vmapple-base/0008-vmapple-usb-qmp-status.patch
859561246ae2495fbe791b05bd5545fc6226a06f21c82a9e0a1000661c9a8dd1  01-vmapple-base/0009-virtio-pci-capability-order.patch
EOF
    if [ "$enable_reims" -eq 1 ]; then
        cat <<'EOF'
d40f88738b5832df3ee5823f7dce8f0cf09bd62f08beeee65346e8bb43f72831  02-reims-display/0001-vmapple-reims-display.patch
EOF
    fi
    if [ "$enable_accel" -eq 1 ]; then
        cat <<'EOF'
6e6523fa7b1d2d2cec5d45b12b6e69b30222c2757405e36c8428b1a15c25c6f1  03-tcg-accel/0001-arm-tcg-sha-ni.patch
ebfacf719b3290a6868a6dce977d8130791a923bcdf2bb9e49b43769214c8c78  03-tcg-accel/0002-arm-tcg-crc32-fast.patch
b407ce2515d1c578e53fb029db1145cfc5eb504802a5b373ebc7b387ad3a2c12  03-tcg-accel/0003-arm-tcg-aese-direct.patch
344aea07b739240a0de99713de8888c9bc72d2cd0a83d90c2574cec772bc60f3  03-tcg-accel/0004-arm-tcg-dc-zva-64b.patch
e71a0256c6a0379cd97ffb3fa8bd7fed9bf731ef51f312be45d9c7a8c82f5509  03-tcg-accel/0005-arm-tcg-simd-tbl-rbit.patch
EOF
    fi
}

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_CONFIG_COUNT
export GIT_NO_REPLACE_OBJECTS=1 GIT_PAGER=cat PAGER=cat
[ "$(git -C "$source_dir" rev-parse --show-toplevel)" = "$source_dir" ] || fail 'SOURCE_DIR 必须是 Git 检出根目录'
[ "$(git -C "$source_dir" rev-parse HEAD)" = "$commit" ] || fail "源码 HEAD 必须固定为 $commit"
[ "$(git -C "$source_dir" rev-parse 'HEAD^{tree}')" = "$tree" ] || fail "源码 tree 必须固定为 $tree"

apply_stack() {
    patch_manifest | while read -r digest filename; do
        patch=$module/patches/$filename
        actual=$(sha256sum < "$patch")
        [ "${actual%% *}" = "$digest" ] || fail "补丁摘要不匹配: $filename"
        git -C "$1" apply "$2" -- "$patch" || fail "补丁应用失败: $filename"
    done
}

if [ "$mode" = verify ]; then
    temp=$(mktemp -d)
    trap 'rm -f -- "$temp/index"; rmdir -- "$temp"' EXIT
    export GIT_INDEX_FILE="$temp/index"
    git -C "$source_dir" read-tree "$commit"
    apply_stack "$source_dir" --cached
    git -C "$source_dir" diff --cached --check
    printf 'verified %s (reims=%s accel=%s)\n' "$commit" "$enable_reims" "$enable_accel"
    exit 0
fi

case "$2" in /*) ;; *) fail 'BUILD_DIR 必须是绝对路径';; esac
parent=$(CDPATH='' cd -P -- "$(dirname -- "$2")" && pwd) || fail 'BUILD_DIR 父目录必须已存在'
name=$(basename -- "$2")
case "$name" in .|..|/) fail '无效的 BUILD_DIR';; esac
build_dir=${parent%/}/$name
case "$build_dir/" in "$source_dir/"*|"$module/"*) fail 'BUILD_DIR 不能位于源码或发布目录内';; esac

for tool in cc python3 ninja pkg-config; do
    command -v "$tool" >/dev/null || fail "缺少构建工具: $tool"
done

if [ -n "$reims_pc_dir" ]; then
    [ -f "$reims_pc_dir/reims-vgpu.pc" ] || fail "未找到 $reims_pc_dir/reims-vgpu.pc"
    export PKG_CONFIG_PATH="$reims_pc_dir${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
fi

mkdir -- "$build_dir" || fail 'BUILD_DIR 必须尚不存在'
git -c core.hooksPath=/dev/null clone --no-local --depth 1 --single-branch --no-tags --no-recurse-submodules -- "$source_dir" "$build_dir/source" > "$build_dir/checkout.log" 2>&1 || fail "详见 $build_dir/checkout.log"
[ "$(git -C "$build_dir/source" rev-parse HEAD)" = "$commit" ] || fail '克隆 HEAD 不一致'
[ "$(git -C "$build_dir/source" rev-parse 'HEAD^{tree}')" = "$tree" ] || fail '克隆 tree 不一致'
apply_stack "$build_dir/source" --index
git -C "$build_dir/source" diff --cached --check

mkdir -- "$build_dir/objects"
(
    cd "$build_dir/objects"
    ../source/configure --target-list=aarch64-softmmu --enable-tcg --enable-vnc \
        --disable-docs --disable-werror --disable-rust --disable-install-blobs --enable-download ${QEMU_CONFIGURE_ARGS:-}
) > "$build_dir/configure.log" 2>&1 || fail "详见 $build_dir/configure.log"
ninja -C "$build_dir/objects" qemu-system-aarch64 qemu-img > "$build_dir/ninja.log" 2>&1 || fail "详见 $build_dir/ninja.log"
printf '%s\n' "$build_dir/objects/qemu-system-aarch64"
