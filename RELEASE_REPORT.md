# EXE 发布与视频权限修复

2026-09-07 已完成新版构建及实际启动验证。

- EXE：[<项目目录>\dist\PPT转视频工具.exe](./dist/PPT转视频工具.exe)
- 大小：111,679,521 字节，约 106.5 MiB。
- 包含三套 UI 主题、增强解析/合成、TTS 模块和三首内置 BGM；使用窗口模式启动。
- 已实际运行打包后的 EXE，窗口标题为 `PPT转视频工具 v2.1.0`，启动正常；[窗口截图](./artifacts/release-exe.png)。
- 包内验证：`ui_themes`、`tts_audio`、`edge_tts`、`moviepy`、`pptx_parser`、`video_composer`、`main` 均存在，三首 MP3 均存在。现有 `dist/.env` 保留，未把密钥文件打进 EXE。
- 此次直接验证了打包程序启动及包内模块/资源；完整视频生成的功能验收见前面的源码验收报告。

构建使用本机 Python 3.14.5 / PyInstaller 6.20.0：

```powershell
& '<用户目录>\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m PyInstaller --noconfirm --distpath dist --workpath build 'PPT转视频工具.spec'
```

构建退出码 0。排除了无关的 PyTorch、TensorFlow 和 Notebook 等可选后端，避免打入大型无用依赖。`build.bat` 已改为使用保留的 spec，不再删除 spec 或清空项目构建目录；`build.bat debug` 可构建带控制台的版本。

[构建日志](./artifacts/release-build.log) · [包内容与 SHA-256](./artifacts/release-package.json) · [实际启动记录](./artifacts/release-startup.json)

## out.mp4 为什么提示没有权限

成片不是损坏或编码不兼容。`out.mp4` 原先由 `CodexSandboxOffline` 创建，保留了临时目录的受保护 ACL，仅文件所有者、SYSTEM 和管理员获得访问权限，没有继承项目文件夹中普通用户的读取权限。

已对根目录 `out.mp4` 和 `artifacts/acceptance` 中同样受影响的另外五个成片恢复权限继承；不修改视频内容，六个文件修复前后 SHA-256 全部一致。已用实际桌面账户 `LAPTOP-STJG47NB\kk` 打开并读取根目录视频的全部 6,794,341 字节，ffmpeg 完整解码成功。

现在可以重新打开：[out.mp4](./out.mp4)。视频为 10 秒，H.264 / AAC，1280×720。

实际操作对每个已确认受影响的文件执行 `icacls <文件路径> /inheritance:e`，未修改项目以外的文件权限。修复前的 ACL 和文件哈希记录保存在本轮备份目录的 `media-acl-before.json`。

## 备份

[backups/release-20260907-103914](./backups/release-20260907-103914) 保存旧 EXE、原 build.bat、原 spec 和本轮修改的三份说明文档 `.bak`。上一轮 UI 和核心升级的备份也继续保留。

新版 EXE 的所有者为桌面用户 `kk`，权限继承正常。桌面主题选择保存在 EXE 旁的 `ui_preferences.json`。本机已装 ffmpeg/ffprobe；在其他机器上运行仍需可用的外部 ffmpeg/ffprobe，Edge TTS 与在线生成服务仍需联网。
