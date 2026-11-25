# orchard86

在 **x86-64 Linux** 上通过 QEMU AArch64 TCG 与 Reims/Vulkan 图形后端恢复并运行 ARM64 macOS（VMApple）的模块化工具链。

> **资产边界**：本仓库仅包含源码补丁、构建脚本、恢复/启动工具与文档，**不提供** Apple IPSW、固件、系统盘、AUX、TSS 票据或私有运行库。用户须自行获取合法授权的输入文件并遵守 [Apple SLA](https://www.apple.com/legal/sla/)。
>
> **性能提示**：当前版本的 TCG 动态二进制转译性能较差，**图形化界面（GUI）几乎不可用**，现阶段建议仅用于串口/SSH 命令行验证，请等待后续转译优化更新。

## 目录结构

| 模块 | 职责 | 许可证 |
|---|---|---|
| [qemu/](qemu/) | 固定基线 (`509a4ce5`) 与分层补丁：`01-vmapple-base`、`02-reims-display`、`03-tcg-accel` | 补丁栈 `GPL-2.0-or-later`；脚本/测试 `GPL-3.0-or-later` |
| [graphics/](graphics/) | Reims C ABI 头文件（`include/reims_vgpu.h`）、`libreims_vgpu_c.so` 构建与 Vulkan 预检 | `GPL-3.0-or-later` |
| [restore/](restore/) | **恢复阶段**：IPSW 解析、TSS 签名、USB mux / `restored` 传输与恢复控制器 | `GPL-3.0-or-later` |
| [boot/](boot/) | **启动阶段**：停机盘对预检、独立启动参数生成与非 root 启动（`run-installer=off`） | `GPL-3.0-or-later` |
| [console/](console/) | 可选本地回环 VNC → WebSocket / noVNC 浏览器控制台 | `GPL-3.0-or-later` |
| [docs/](docs/) | 架构说明、恢复与启动指南、图形 ABI 说明与第三方许可边界 | — |

## 快速开始（非 root）

### 1. 环境依赖
- **图形后端**：`cargo` / `rustc`、`cmake`、`gcc`/`g++`、`vulkan-tools`（`graphics/build.sh` 默认启用 `CARGO_FEATURE_SDL_UNIX_CONSOLE_BUILD=1`，无需 X11/Wayland 开发头文件）。
- **QEMU**：`git`、`cc`、`python3`（含 `python3-venv`）、`ninja`、`pkg-config`、`glib-2.0`、`pixman-1`、`zlib`、`gnutls`、`libslirp`、`libnuma`（以及 `libfdt-dev` 或允许 `configure` 拉取 `dtc` 子项目）。
- **恢复阶段**：`idevicerestore`（宿主环境提供，独立子进程调用）。

### 2. 构建图形后端（Reims）
```sh
./graphics/check_vulkan.sh
./graphics/build.sh /path/to/reims-vgpu "$PWD/out-graphics"
# 输出 .../reims-vgpu.pc 路径
```

### 3. 构建 QEMU
```sh
git clone https://github.com/steelbrain/experiment-macOS-arm64-on-linux-x86.git /path/to/public-qemu
git -C /path/to/public-qemu checkout 509a4ce52bc703dfc79eb8b4283f51acd88b8594

# 验证补丁栈
./qemu/build.sh --verify /path/to/public-qemu

# 编译（接入上一步生成的 reims-vgpu.pc 目录；无显示 CLI 验证可传 --no-reims）
./qemu/build.sh --reims-pc-dir "$PWD/out-graphics" /path/to/public-qemu "$PWD/out-qemu"
```

### 4. 恢复写入磁盘（阶段 1–3）
```sh
python3 -B restore/cli.py inspect-ipsw --ipsw /path/to/Restore.ipsw
python3 -B restore/cli.py run \
  --ipsw /path/to/Restore.ipsw \
  --qemu "$PWD/out-qemu/objects/qemu-system-aarch64" \
  --firmware /path/to/AVPBooter.vmapple2.bin \
  --output /path/to/new-restore-dir \
  --execute
```
> 若需显式指定 Apple 根证书或跳过默认配置，可直接调用 `python3 -B restore/controller.py ... --ca /path/to/apple-root.pem`（默认不设恢复超时）。

### 5. 独立启动系统（阶段 4）
```sh
# 预览启动参数（默认不启动）
python3 -B boot/cli.py \
  --qemu "$PWD/out-qemu/objects/qemu-system-aarch64" \
  --firmware /path/to/AVPBooter.vmapple2.bin \
  --system /path/to/system.qcow2 \
  --aux /path/to/aux.raw \
  --output /path/to/new-boot-dir \
  --ecid 0x12345678 --cpus 4 --memory-gib 8 \
  --display vnc --vnc-display 9 --ssh-port 2229

# 确认磁盘已停机并启动（加 --run-immediately 可跳过 -S 直接运行）
python3 -B boot/cli.py ... --confirm-offline-pair --launch-paused
```

## 文档索引

- [整体架构与五阶段链条](docs/architecture.md)
- [恢复指南](docs/restore.md)
- [启动、SSH 与显示指南](docs/boot.md)
- [项目图形 ABI 说明](docs/graphics-abi.md)
- [第三方组件与许可边界](docs/third-party.md)

## TODO

- 持续纳入更多 AArch64 → x86-64 TCG 动态二进制转译优化（当前正在独立开发与验证中，后续将分批合入 `qemu/patches/03-tcg-accel/`）。

## 许可证

本项目采用分层双许可（详见 [LICENSE](LICENSE) 与 [docs/third-party.md](docs/third-party.md)）：
- 主机侧工具链（`boot/`、`console/`、`graphics/`、`restore/`、`qemu/build.sh`、`qemu/tests/`）：**`GPL-3.0-or-later`**（[COPYING.GPL3](COPYING.GPL3)）
- QEMU 补丁栈（`qemu/patches/`）：**`GPL-2.0-or-later`**（[COPYING](COPYING)，与 QEMU 基线兼容）
