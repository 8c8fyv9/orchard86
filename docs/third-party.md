# 第三方组件与许可边界

- **分层双许可**：本项目主机侧工具链（`boot/`、`console/`、`graphics/`、`restore/`、`qemu/build.sh`、`qemu/tests/`）采用 **`GPL-3.0-or-later`**（见 `COPYING.GPL3`）；`qemu/patches/` 补丁栈采用 **`GPL-2.0-or-later`**（见 `COPYING`、`COPYING.LIB`），确保与 QEMU 上游完全兼容。
- **QEMU**：基线为 [steelbrain/experiment-macOS-arm64-on-linux-x86 @ 509a4ce5](https://github.com/steelbrain/experiment-macOS-arm64-on-linux-x86/commit/509a4ce52bc703dfc79eb8b4283f51acd88b8594)，整体遵循 GPLv2（见根目录 `LICENSE`、`COPYING`、`COPYING.LIB`）。
- **Reims / Metal2Vulkan**：`reims-vgpu` 与 `metal2vulkan` 声明 `GPL-2.0-or-later OR LGPL-3.0-or-later`，由用户按 `graphics/build.sh` 从对应源码树自行构建。
- **idevicerestore / libimobiledevice**：`restore/` 通过独立子进程调用宿主环境中的 `idevicerestore`（通常为 LGPL-2.1+），不与本仓库代码静态链接。
- **noVNC / websockify**：`console/` 仅包含本地网关代码与前端封装，运行时依赖见 `console/requirements.txt`。
- **Apple 专有资产**：IPSW、固件、系统盘、AUX、TSS 票据与私钥**严禁**纳入本仓库或提交到 GitHub。
