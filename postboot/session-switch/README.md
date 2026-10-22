# 修复桌面／游戏会话切换时的 SDDM 配置缓存

本组件修复 SDDM 0.21.0 的配置重读条件。
使用 Fedora `sddm-0.21.0-13.fc44.src.rpm` 的完整补丁集，只改 `ConfigReader.cpp` 和 `ConfigReader.h`。
不修改 Steam、Armada Control、steamos-manager、登录目标、网络或时钟。

## 已复现的原因

设备 RTC 回到 1970 年，Linux 启动时钟先升到 2026-10-18，随后才由 NTP 同步。
SDDM 启动时读取的配置目录 mtime 在 2026-10-22。
上游代码只在“所有配置文件／目录的最大 mtime 严格增大”时重读。
用户在同步前请求桌面，manager 写入的临时文件和目录 mtime 反而更早，SDDM 继续按旧配置登录 Steam。

同一启动中，第一次 `steamosctl switch-to-desktop-mode` 返回成功却重新登录 gamescope。
NTP 自然同步后，完全相同的请求进入 KDE。
两次之间没有改桌面版／移动版，也没有重启 SDDM。

修复后，每次显式 `ConfigBase::load()` 都先恢复默认值，再按原优先级读取当前文件。
这也处理删除配置文件、移除键、同秒同大小替换和系统时钟倒退。
配置文件少且仅在显式加载时读取，不增加后台轮询、会话 hook 或自动重启。

## 文件

- `patches/0001-reload-config-without-wall-clock-cache.patch`：真实 SDDM 源码补丁。
- `tests/config_reload_regression.cpp`：直接链接真实 `ConfigReader.cpp` 的八个 QtCore 回归测试。
- `tests/CMakeLists.txt`：独立测试构建，不复制或模拟解析器算法。
- `build_native.py`：仅在 Linux AArch64 本地构建；记录输入、红／绿测试、daemon 和链接证据。
- `install.py`：默认显示计划；显式安装私有 daemon 和单独的 systemd drop-in；支持回滚。
- `test_install.py`：安装器的隔离测试。
- `PROVENANCE.json`：主来源与修复范围。

## 原生构建

构建、依赖安装和设备操作由设备维护者执行。
不要在 macOS 交叉构建本组件。
先检查 source RPM 的 Fedora 签名，按原 spec 应用全部 Fedora 补丁，再运行本组件。
源树必须是“已应用 Fedora 补丁、尚未应用本组件补丁”的 SDDM 0.21.0。

已准备的设备目录：

```text
/var/home/armada/src/sddm-fedora-0.21.0-13/SOURCES
/var/home/armada/src/sddm-fedora-0.21.0-13/SPECS/sddm.spec
/var/home/armada/src/sddm-fedora-0.21.0-13/prepared/sddm-0.21.0
```

默认只查看计划：

```bash
python3 build_native.py \
  --source /var/home/armada/src/sddm-fedora-0.21.0-13/prepared/sddm-0.21.0 \
  --fedora-spec /var/home/armada/src/sddm-fedora-0.21.0-13/SPECS/sddm.spec \
  --srpm /tmp/sddm-0.21.0-13.fc44.src.rpm \
  --expected-srpm-sha256 644dd505e52e94547b52715ef4257f178ff5c12e408db7870cb41557e28c61cb \
  --work-dir /var/home/armada/.local/state/caihong-session-switch/build-first
```

核对路径与摘要后，在同一命令末尾加 `--build`。
新工作目录不得已存在。
构建器复制完整准备树，先让真实旧解析器复现失败，再应用零 fuzz 补丁，确认八个测试通过，最后仅构建 `sddm` daemon target。
它不调用安装、systemctl、切换会话或修改系统配置。
`build-evidence.json` 记录原生平台、源 RPM、spec、补丁、完整准备树文件摘要、命令输出和 daemon SHA-256。

若维护者已手动完成相同的红／绿验证，可直接按 Fedora spec 的 CMake 选项构建现有树，不需重复套补丁。
需要保留原生构建与八项测试的证据；不能用重新实现算法的 Python 测试代替。

### 仅运行真实解析器回归

```bash
cmake -S tests -B /tmp/caihong-sddm-regression \
  -DSDDM_SOURCE_DIR=/var/home/armada/src/sddm-fedora-0.21.0-13/prepared/sddm-0.21.0
cmake --build /tmp/caihong-sddm-regression --parallel 2
/tmp/caihong-sddm-regression/config-reload-regression
```

未修复源码应通过 `unchanged_load` 控制，并在未来时间、倒退、删除和同时间替换用例失败。
修复后八项全部通过。

## 安装边界

优先保留已验证的 Fedora source RPM 和完整补丁集。
本组件的私有 daemon 安装不覆盖 `/usr/bin/sddm`，也不替换 greeter、helper、PAM 或已有配置。
候选 daemon 安装到 `/usr/local/libexec/caihong-sddm/<SHA-256>/sddm`。
单独的 `90-caihong-config-reload.conf` 只改变 `ExecStart`，保留原有参数和其他 drop-in。

安装器默认只显示计划。
只有 Linux AArch64 root 明确指定 `--apply` 才写入。
它检查 daemon 的 AArch64 ELF、指定摘要、原生构建证据、现有 unit 和冲突 drop-in，并保存私有备份和回执。
安装器从不停止、启动、重启 SDDM，也不自动执行 `daemon-reload`。
文件安装完成后，运行中的 SDDM 仍是原进程；维护者决定何时加载和切换服务。

先读取实际构建回执中的 daemon SHA-256，再执行只读计划：

```bash
python3 install.py \
  --source /tmp/caihong-sddm-daemon-build/src/daemon/sddm \
  --expected-sha256 "$(python3 -c 'import json; print(json.load(open("/var/home/armada/src/caihong-session-switch/native-build-evidence.json"))["daemon"]["sha256"])')" \
  --build-evidence /var/home/armada/src/caihong-session-switch/native-build-evidence.json
```

维护者核对计划后，使用相同参数并显式加 `--apply`。
回执固定保存在 `/var/lib/caihong-sddm/receipts/<事务编号>/receipt.json`。
回滚使用 `python3 install.py --rollback <实际回执路径>` 查看计划，明确加 `--apply` 后恢复原 drop-in。
以上命令都不执行服务切换；维护者单独安排 `daemon-reload` 和服务交接。

## 设备验收

1. 保留原 daemon、unit、配置和本次构建回执。
2. 核对私有 daemon 的 SELinux 标签、`ldd`、版本和 daemon 路径。
3. 维护者安排一次服务切换后，确认 `/proc/<SDDM PID>/exe` 指向审定的私有 daemon。
4. 原生 Steam“切换至桌面”进入 KDE；桌面返回游戏进入 gamescope。
5. 在真实解析器回归中确认未来 mtime 和时钟倒退，不为测试修改整机时间。
6. 验证既有 Wi-Fi 连接、后端和 inputplumber 保持正常。

本次不添加时钟服务。
启动时钟的持久化问题可另行修复，SDDM 本身仍应正确处理配置时间倒退或删除。
