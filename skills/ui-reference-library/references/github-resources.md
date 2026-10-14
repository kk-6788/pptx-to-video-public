# GitHub 检索与轻量资源

核验日期：2026-09-08。以下只读研究与少量示例下载没有安装包或修改应用。优先在官网找到 GitHub 链接；GitHub 搜索补充同类项目，不能用搜索排名代替所属和许可核验。

## 三站官方 GitHub 入口

| 站点 | 所属证据 | 已确认 GitHub 入口 | 范围 |
| --- | --- | --- | --- |
| Uiverse | [首页 Uiverse Galaxy 区域](https://uiverse.io/)直接链接仓库，仓库 README 反链官网 | [uiverse-io/galaxy](https://github.com/uiverse-io/galaxy) | UI 元素集合，MIT；按具体元素取用，不镜像全库 |
| React Bits | [官网入口](https://reactbits.dev/)、[官网源文件结构化身份信息](https://github.com/DavidHDev/react-bits/blob/main/index.html)与仓库 README 相互对应 | [DavidHDev/react-bits](https://github.com/DavidHDev/react-bits) | 免费库；MIT + Commons Clause，使用范围见 [站点许可说明](sites.md) |
| Aceternity | [官方 Brand Facts 的 GitHub 链接](https://ui.aceternity.com/brand-facts)及[机器可读 social.github](https://ui.aceternity.com/.well-known/brand-facts.json)指向官方组织 | [github.com/aceternity](https://github.com/aceternity) | 确认的是组织，不能据此把任何同名第三方组件镜像当成官方。组织可见 saasternity 与归档 nextjs-boilerplate，未确认有完整 UI 库的公开官方仓库 |

## 下载前核验顺序

1. 从具体界面需求形成搜索词，如 `tkinter ttk theme`、`icons svg presentation`；先检索官网仓库，补充检索时检查作者、README 官网、是否 fork/归档和最近维护。星数仅作线索。
2. 打开真正要用的文件、同目录与仓库 LICENSE、NOTICE 和依赖声明。仓库总体许可不能自动覆盖媒体素材、内嵌第三方代码或付费区域。
3. 通过 GitHub 提交页或只读 API `https://api.github.com/repos/OWNER/REPO/commits/REF` 解析完整 SHA，记录返回时间。下载使用 `https://raw.githubusercontent.com/OWNER/REPO/FULL_SHA/path/to/file`，许可使用同一 SHA。
4. 在来源清单中同时保存：官网所属证据、仓库 URL、文件路径、commit SHA、下载字节的 SHA256、许可及用途。只有分支链接时如实标为可变版本，不伪造 SHA。
5. 下载范围是所选文件及必要许可，先阅读后集成。不执行 README 中未经审查的命令，不镜像全库、不提取付费预览底层代码、不把受限组件作为 skill 库再分发。

## 适合当前 Python / tkinter 应用的候选项

| 候选 | 官方资源与许可 | 本次取舍 |
| --- | --- | --- |
| Pillow / ImageDraw | [官方仓库](https://github.com/python-pillow/Pillow)、[绘图文档](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html)、[LICENSE](https://github.com/python-pillow/Pillow/blob/main/LICENSE) 当前写明 MIT-CMU，并保留 PIL 版权条款 | **优先已有依赖**。可以独立编写柔光、边框、纹理和抗锯齿图标绘制。生成 PNG 后 Tk PhotoImage/ImageTk 使用，无需加入 WebGL 或浏览器 |
| Lucide | [官网到 GitHub 链接](https://lucide.dev/license)、[官方仓库](https://github.com/lucide-icons/lucide)、[完整 LICENSE](https://github.com/lucide-icons/lucide/blob/main/LICENSE)：ISC，并包含列明 Feather 衍生图标的 MIT 许可 | **可按需采用少量图标**。已查看 [presentation.svg](https://github.com/lucide-icons/lucide/blob/main/icons/presentation.svg)、[video.svg](https://github.com/lucide-icons/lucide/blob/main/icons/video.svg)。Tk/Pillow 默认不是完整 SVG 渲染器；使用已具备的 SVG 转换工具，或读懂简单几何后本地绘制并保留衍生来源；不能假装 SVG 直接可用。不要为了几个图标安装整个 npm 工程 |
| Sun Valley ttk | [作者项目](https://github.com/rdbende/Sun-Valley-ttk-theme)、[MIT LICENSE](https://github.com/rdbende/Sun-Valley-ttk-theme/blob/main/LICENSE) | **仅候选，未安装**。可提供标准 ttk 主题，官方 README 明确不完整作用于普通 tk 控件。已有三主题体系的应用直接替换可能破坏自定义风格；本次优先现有 ttk + Pillow 独立实现。如果未来采用，要连同必要 Tcl/图片资源打包，并验证主题切换与 EXE |

## 本次固定版本证据

通过 GitHub 官方只读 commits/HEAD API 实际查询；记录的是当时提交，不代表建议升级现有依赖至这些提交。

| 仓库 | 查询到的完整 commit SHA |
| --- | --- |
| lucide-icons/lucide | `a537cb6eb323b885f4c60baf3cec1a995982d167` |
| uiverse-io/galaxy | `adbd2adde0a299a3956ea288fb444ec01891ca41` |
| DavidHDev/react-bits | `0e69e737242df1d257b4e5e399b01ae1d7901375` |
| rdbende/Sun-Valley-ttk-theme | `16a9ccca67d9e64f8b77bf189e854c2131073dae` |
| python-pillow/Pillow | `31da642cdfd5235b2b5fe0257a2e7802d44457b4` |

Lucide 示例仅下载一个 `presentation.svg`，同目录保留完整 LICENSE 和包含固定版本 URL、SHA256 的 `.source.json`。样本位于 `../reference-assets/lucide/`，未自动安装依赖或修改当前应用。该样本用于证明按需下载流程，实际项目仍按需求选择；保留完整 ISC/Feather MIT 文本可避免遗漏继承条款。
