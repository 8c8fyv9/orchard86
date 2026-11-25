# 启动、SSH 与显示指南 (`boot/` & `console/`)

## 独立启动 (`boot/cli.py`)

日常启动已安装系统时，必须使用**已停机且成对**的 `system.qcow2` 与 `aux.raw`：

- 默认输出 JSON 启动计划（不创建运行目录、不启动 QEMU）。
- 传入 `--write-plan /path/to/plan-dir` 可将启动计划以 `0700/0600` 权限落盘。
- 传入 `--confirm-offline-pair --launch-paused` 会创建运行目录并以暂停态（`-S`）启动 QEMU；若需直接运行，追加 `--run-immediately`。

### 关键参数
- `--ecid`：与恢复阶段一致的 ECID（十进制或 `0x` 十六进制）。
- `--cpus` / `--memory-gib`：vCPU 核数与内存（GiB）。
- `--display vnc --vnc-display 9`：在 `127.0.0.1:5909` 开启回环 VNC。
- `--ssh-port 2229`：通过隔离的 `user,restrict=on` 网络将客体 `22` 端口映射至 `127.0.0.1:2229`。

## Web 浏览器控制台 (`console/`)

启动 VNC 后，可通过 `console/server.py` 将本地回环 VNC 转发至浏览器：
```sh
pip install -r console/requirements.txt
python3 -B console/server.py --vnc-host 127.0.0.1 --vnc-port 5909 --listen-port 8770
```
该服务仅限本地回环调试，不提供远程鉴权或公网暴露能力。
