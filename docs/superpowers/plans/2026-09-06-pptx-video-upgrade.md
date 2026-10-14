# PPTX 转视频升级实施计划

**目标：** 完成用户 A/B 八项要求，保留现有入口与数据字段；新增功能免费可用。

**架构：** 保留现有模块。解析器提供完整 Slide；讲解稿按页生成，统一场景时间轴供动画、TTS、烧录字幕与 SRT 使用。实际配音过长时最多压缩到原时长 80%，仍过长则延长画面，避免截断句子。交叉淡入只在有前一画面覆盖时使用，最终逐秒检测黑段。

**约束：** Windows；Python 3.14.5 与当前 PATH Python 兼容；MoviePy v2；修改前逐文件 .bak；旧 .bak 归档；不依赖付费 API；所有验收实跑。

- [x] 解析：普通文本框、递归组、表格、图表、SmartArt XML 关系、备注、80px 图片过滤与面积排序；用 demo 和合成复杂 PPT 验证。
- [x] 配音/讲解稿：async generate_scene_narrations(scenes, output_dir) 返回 dict 或 None 列表；逐页 narration_text，direct/explain；保留旧全局接口并去重；实跑前三页 MP3。
- [x] 合成：浅色渐变、中文按字符及像素换行、逐要点淡入、图文横竖版、连续覆盖转场；逐段音频、字幕与 SRT 共用场景起止；有界变速后延长画面；失败全局一次朗读降级；清理资源。
- [x] 黑帧：ffmpeg 每秒采样与三个位置预检；最终黑段 ERROR；缺失工具时跳过；实际黑片/正常片验收。
- [x] 配置与入口：config.set_ratio 同时更新 VIDEO_SIZE；CLI ratio/srt-only/narration-style/bgm/no-bgm/audio；GUI 比例、口播、BGM 与音量；保留既有布局。
- [x] BGM：用程序生成原创 45 秒和弦 MP3 与生成脚本/版权说明；v2 音频循环、淡入淡出、配音压低音量；无配音音轨验收。
- [x] 集成：无 API 的纯 fallback 全流程、横竖分辨率、SRT BOM/时间轴、异步 CLI、GUI 启动与控件检查；抽帧目视核对。
- [x] 报告：逐文件行号与原因、十项验收命令和实测结果、使用说明、风险、备份清单。

执行采用 subagent-driven-development：独立子任务实施后由主任务核对需求与质量，合成与全链路验证在主任务完成。项目没有 Git 仓库，以 .bak 哈希清单对照原版。
