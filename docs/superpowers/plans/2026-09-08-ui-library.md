# UI 参考技能与桌面组件升级

用户授权：将 Uiverse、React Bits、Aceternity 沉淀为今后可用的技能，并应用于 PPTX to Video EXE；延续三主题、免费优先、修改前备份与现有转换功能。

选择：保留 tkinter + MoviePy，采用独立实现的桌面组件。完整 React/WebView 迁移会新增浏览器运行时与 Python 桥接风险，本次不需要；仅改颜色无法满足此次要求。

参考映射（2026-09-08 实际访问）：
- Uiverse https://uiverse.io/barisdogansutcu/little-penguin-13 与 https://uiverse.io/Cevorob/good-wolverine-51 ：圆角按钮、禁用/悬停/选中反馈。
- React Bits https://reactbits.dev/components/spotlight-card 与 https://reactbits.dev/components/stepper ：低幅度指针聚光、步骤完成与当前状态。
- Aceternity https://ui.aceternity.com/components/file-upload、/components/bento-grid、/components/tabs ：文件入口、信息卡片分区、清晰的活动标签。

视觉方向：桌面创作工作台，左侧文件/参数，右侧可交互文件预览与分镜；圆角表面、细边框、柔和阴影、克制的局部辉光，保留内容可读性。用真实文件状态及导出参数填充界面，不添加虚构统计。

三主题语义稳定：简约浅色（雾白/深蓝/青蓝）、柔和暖色（浅砂/森林绿/暖铜）、深色科技（深靛/雾紫/冷青）。中文正文 Microsoft YaHei UI，标题 Segoe UI Semibold/微软雅黑，参数数字等宽字体。统一圆角 10–18、组件高 36–46、间距 8/12/20。

组件：原生 Canvas 圆角按钮（鼠标/键盘/禁用反馈），圆角面板，滑动开关，分段比例选择，步骤状态指示，指针局部聚光的文件入口；动效仅在交互发生时播放，支持“减弱动效”。保留标准 Entry/Combobox 的输入与键盘行为。界面主题与视频内容独立。

- [x] 查阅三站组件入口与许可；备份既有文件/EXE。
- [x] 创建并验证 ui-reference-library 技能、来源清单与安全下载流程；安装到用户级技能目录。
- [x] 创建可复用 Tk 组件并整合三主题，保留实际工作流与所有输入参数。
- [x] 实际桌面验证三主题、悬停/开关/键盘/禁用/小窗口/减弱动效与完整转换流程；回归测试。
- [x] 重新打包 EXE，实际启动，提交截图/来源映射/验收报告。

来源代码下载仅用于许可证允许的具体用途，保留许可与 SHA-256；不下载付费模板、不自动执行安装命令、不向网站上传 PPT 或密钥。本 EXE 的 Tk 组件独立实现，不直接拷贝 React/CSS 组件。

交付：UI_REFERENCE_REPORT.md。两运行时各 79 项核心回归；下载助手各 9 项测试；三主题及 8 组真实控件检查；完整 GUI 转换 2/2 页；最终 EXE v2.3.0 启动、out.mp4 普通用户读取与完整解码通过。Windows 转换后窗口截图曾失败，最终重跑截图成功；三主题与 EXE 截图已取得。独立审查指出的旧步骤完成状态已修复并加入实机覆盖。
