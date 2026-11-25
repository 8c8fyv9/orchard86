# 整体架构与五阶段链条

本工具链将 macOS 27 在 x86-64 Linux 上的生命周期拆分为**恢复安装**与**独立运行**两个隔离阶段：

```text
[Apple IPSW + AVPBooter]
        │
        ▼  1. 固件引导与 Stage 1/2 传输 (vmapple-bdif recovery-host-fd)
[RecoveryOS 内核启动]
        │
        ▼  2. 运行时 USB 恢复 (vmapple-virtio-usb-pci + usbmux v2 + restored v15)
        │     写入 APFS / Cryptex / Seal / Snapshot
        ▼
[停机校验后的 (system.qcow2, aux.raw) 盘对]
        │
        ▼  3. 独立启动 (run-installer=off, vmapple-virtio-blk-pci, 无恢复 USB)
[XNU → launchd → WindowServer / SSH]
        │
        ├── CPU 转译：QEMU AArch64 TCG + SHA-NI / CRC32 / AESE / DC-ZVA / SIMD
        └── 图形显示：VMAppleReimsScreen → libreims_vgpu_c.so → Vulkan → VNC/noVNC
```

## 模块分工

- **恢复与启动隔离**：`restore/` 仅在初始化新盘对时接入 `bdif` 与 `virtio-usb`；日常使用通过 `boot/` 以 `run-installer=off` 启动，不挂载恢复宿主或安装通道。
- **QEMU 补丁分层**：
  1. `01-vmapple-base/`：运行时 USB、BDIF USB、整盘 discard、共享页、RTC、MSI/保护、PAC 初始化、QMP 状态与 PCI 能力链排序。
  2. `02-reims-display/`：Reims 显示设备、异步双缓冲 `reims-readback` 线程、清理通知与 VNC 16ms 即时唤醒。
  3. `03-tcg-accel/`：SHA-NI、IEEE CRC-32 查表、AdvSIMD `AESE` 直接降级、`DC ZVA` 64B 快路径、`TBL` SSSE3/AVX 与 `RBIT` 内联。
