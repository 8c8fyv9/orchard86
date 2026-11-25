#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
set -eu

command -v vulkaninfo >/dev/null || {
    echo '未找到 vulkaninfo，请安装 vulkan-tools 并确认宿主 Vulkan ICD 可用。' >&2
    exit 1
}
vulkaninfo --summary
