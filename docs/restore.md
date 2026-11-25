# 恢复指南 (`restore/`)

`restore/` 负责从官方 IPSW 解析构建身份、驱动 USB 恢复通道并验收输出盘对。

## 常用命令

- **检查 IPSW 内容**：
  ```sh
  python3 -B restore/cli.py inspect-ipsw --ipsw /path/to/Restore.ipsw
  ```
- **结构预检（不启动 VM）**：
  ```sh
  python3 -B boot/preflight.py restore --ipsw /path/to/Restore.ipsw --output /path/to/new-dir
  ```
- **执行恢复（默认使用内置控制器 [controller.py](../restore/controller.py)）**：
  ```sh
  python3 -B restore/cli.py run \
    --ipsw /path/to/Restore.ipsw \
    --qemu /path/to/qemu-system-aarch64 \
    --firmware /path/to/AVPBooter.vmapple2.bin \
    --output /path/to/new-dir \
    --execute
  ```
  > 也可通过 `--controller /path/to/custom` 覆盖默认控制器；内置控制器需宿主 `PATH` 中有 `idevicerestore` 与 `qemu-img`。

## 控制器契约 (`restore-v1`)

`restore/cli.py run` 要求输出目录尚不存在，完成后校验：
1. 控制器退出码为 `0`；
2. `restore-evidence.json`（`schema == "restore-v1"`）确认 `Status: Restore Finished`、无错误码、客体已完成且写入器全部停止；
3. 输出目录内生成独立的非空 `system.img` 与 `aux.img`。

`restore/transport/` 同时提供 `usbmux` v2、包队列、流缓冲与恢复控制流的 Python 组件供控制器复用。
