# 内置背景音乐

`bgm.mp3`、`gentle_steps.mp3`、`quiet_light.mp3` 均由同目录 `generate_bgm.py` 从正弦波和弦与稀疏铃音程序合成，45 秒、44.1 kHz 双声道、128 kbps MP3。没有下载或采样第三方录音，不需要付费 API；随本项目按 MIT 许可使用、修改和分发。

默认使用 `bgm.mp3`。通过 `--bgm assets/bgm/quiet_light.mp3` 选择另一段，或 `--no-bgm` 关闭。也可以自行放入已获使用许可的音乐文件。

重新生成：`python assets/bgm/generate_bgm.py`（需要 NumPy 和 ffmpeg）。

GUI 音量滑条表示基础音量：默认 15% 在配音时降到 8%，无配音时升到 30%；滑条为 0 或文件不存在时静默跳过。声音的实际听感还取决于源文件响度。
