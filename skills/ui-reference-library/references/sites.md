# 官方来源索引

核验日期：2026-09-08。这里只记录入口和许可范围；下次下载以具体文件当时附带的许可为准。没有将展示素材或网页截图作为实现资源打包。

| 站点 | 适合寻找 | 已核验入口 |
| --- | --- | --- |
| Uiverse | 按钮、输入、开关、卡片的 CSS 状态与质感 | [全部元素](https://uiverse.io/elements)、[按钮](https://uiverse.io/buttons)、[按钮实例 / adamgiebl](https://uiverse.io/adamgiebl/massive-insect-65)、[官方 Galaxy 源库](https://github.com/uiverse-io/galaxy) |
| React Bits 免费库 | 背景氛围、局部聚光、文字和卡片动效 | [Aurora](https://reactbits.dev/backgrounds/aurora)、[Spotlight Card](https://reactbits.dev/components/spotlight-card)、[安装入口](https://reactbits.dev/get-started/installation)、[官方源库](https://github.com/DavidHDev/react-bits) |
| Aceternity UI | 网格、卡片、分层表面、按钮边框与任务分组 | [组件目录](https://ui.aceternity.com/components)、[Bento Grid](https://ui.aceternity.com/components/bento-grid)、[Moving Border](https://ui.aceternity.com/components/moving-border) |

React Bits 文档依赖客户端渲染；本次文本抓取返回空正文，已检查官方 [SpotlightCard.jsx](https://github.com/DavidHDev/react-bits/blob/main/src/content/Components/SpotlightCard/SpotlightCard.jsx) 和 [Aurora.jsx](https://github.com/DavidHDev/react-bits/blob/main/src/content/Backgrounds/Aurora/Aurora.jsx)。前者处理指针位置与 CSS 聚光，后者含图形着色器；不能据此声称在本 skill 任务中完成了浏览器动态视觉检查。两者代码均未捆绑进 skill。

## 许可证与免费范围

**Uiverse**：[首页](https://uiverse.io/)说明 UI 元素免费用于个人和商业；[Galaxy README](https://github.com/uiverse-io/galaxy#licensing-and-attribution) 与 [完整 MIT 许可](https://github.com/uiverse-io/galaxy/blob/main/LICENSE)相互印证。代码复制或实质复用时保留版权及许可，来源清单记作者。该范围针对 UI 元素，不能自动推广到站点品牌、广告、外链设计产品或所有媒体素材。

**React Bits 免费库**：[官方 LICENSE.md](https://github.com/DavidHDev/react-bits/blob/main/LICENSE.md) 当前为 **MIT + Commons Clause License Condition v1.0**，Copyright (c) 2026 David Haz。允许作为应用、网站、产品的一部分使用，含商业用途，并要求保留许可。附加限制禁止售卖、转许可或再分发组件本身，包括单独、打包和移植版本。不能简称“纯 MIT”，也不应作为第三方组件素材库重新分发。下载到具体应用内部前核验使用方式。

**React Bits Pro**：与免费库分开，[官方介绍](https://pro.reactbits.dev/about)说明为付费产品；[Pro License](https://pro.reactbits.dev/license)适用于其组件、模板和 Agent Kit。公开预览不授予底层代码使用权。本 skill 没有拷贝其 Agent Kit、付费组件或模板，不以登录/付费预览页面提取源码。

**Aceternity**：组件页提供公开预览与安装入口，导航另列免费区以及付费 All-Access/Pro。核验到的 [官方 /licence](https://ui.aceternity.com/licence) 是自定义 Aceternity License，页面标题面向 UI Pro，正文涵盖购买或下载的条目；允许构建终端产品，限制源条目再分发及作为主题/模板转售。[站点 /terms](https://ui.aceternity.com/terms)还有网站内容条款。因此**没有依据把整个站或所有免费组件统一标成 MIT**。具体资源附带独立许可时按其范围处理；不能确认时仅参考一般布局原则、独立实现，或选用许可明确的替代项。外部依赖和素材不随组件自动获得许可。

## 选型提示（设计判断）

- 生产力桌面应用：Bento 的主次分组、Uiverse 的控件状态、Spotlight 的局部光感可以转化为原生面板/边框/轻量绘制；不要加载 React/WebGL 仅为了装饰。
- 静态精致感也能成立：通过两层表面、细线边界、克制的强调色和清晰文字实现。使用动效时把变化局限于装饰层，提供静态状态。
- Aurora 等连续着色器适合部分网页展示，但桌面视频编码时可能争抢资源，选择静态柔光通常更合适。这是针对场景的取舍，不是站点许可声明。

核验样本见 `../reference-assets/react-bits-LICENSE.md` 与同名 `.source.json`；保留完整条文及实际下载哈希，作为当日证据。它不是可替代新下载许可核验的授权文件。
