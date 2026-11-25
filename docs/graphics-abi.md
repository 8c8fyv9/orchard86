# 项目图形 ABI 说明 (`graphics/`)

本仓库使用**项目自维护的 Reims C ABI**，头文件固定为 [graphics/include/reims_vgpu.h](../graphics/include/reims_vgpu.h)。

## 为什么单独维护 ABI

QEMU 补丁 `02-reims-display`（`hw/vmapple/reims.inc.c` 与 `vmapple.c`）采用 **VMApple 双 MMIO + IOSurface + FrameTarget** 接口：
- 设备创建：`rvg_device_create()`、`rvg_iosurface_device_create()`
- MMIO 转发：`rvg_device_mmio_read/write()`、`rvg_iosurface_device_mmio_read/write()`
- 帧读回：`rvg_display_create()`、`rvg_frame_target_create()`、`rvg_display_encode_frame()`、`rvg_frame_commit()`、`rvg_frame_wait()`、`rvg_frame_target_read_pixels()`

这与上游 `reims-vgpu` 早期基于 PCI BAR 0/2 的 `RvgGraphicsDeviceConfig / rvg_graphics_device_create` 接口**不兼容**。

## 构建与校验

`graphics/build.sh` 在编译 `libreims_vgpu_c.so` 后会自动通过 `readelf` 校验上述核心导出符号，并生成指向 `graphics/include/` 的 `reims-vgpu.pc`，供 `qemu/build.sh --reims-pc-dir` 直接消费。
