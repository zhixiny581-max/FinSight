# FinSight UI 优化说明（2026-11-04）

> 分支：`feature/ui-polish-20261104`（基于 `main` / `47cdb6a`）
> 本文记录资料核对、评审清单、实际改动、验证结果、既有问题与回退方法。
> 文中行号均指**本次改动前**的文件行号。

---

## 0. 资料核对：承接了什么，什么没找到

按要求先核对「之前跑过的一些结果和得出的修改意见」，实际找到的痕迹如下：

| 项 | 位置 | 内容 |
|---|---|---|
| 功能分支 | `.git` | 已存在 `feature/ui-polish-20261104`，从 `main 47cdb6a` 切出，尚未推送远端 |
| 上一轮 UI 成果（未提交） | `deploy/show-v2/index.html` 顶栏 | 删除 `<div class="mark">智</div>` 与 `<div class="avatar">SD</div>` 两行，即移除个人/开发者标识 |
| 设计令牌体系 | 同上，第 8–46 行 | 浅/深双主题、涨红跌绿语义色、分类色板 CVD 校验结论（注释中记录了 all-pairs ΔE 与对比度补偿方案） |
| 展示站清理记录 | 根 `README.md`「课程展示与 Python 部署」 | 展示页保留快讯/智能分析/相关公司/行情，开发交接与标注入口已移除 |
| 页面回归结论 | `docs/review/交付复核.md` 第 19、58 行 | 两页面 4 种范围的 8 个行情视图、6 个刷新/失败状态案例、20 行公司清单的桌面与手机检查通过 |

**未找到独立文档**：全仓 `*.md / *.txt / *.json`、全工作区 11-03 之后修改的文件、远端分支与 Issues、以及历史会话检索中，均没有单独的「UI 运行结果 / 修改意见清单 / 评审截图」文件。因此本次以「代码现状 + 交付复核记录 + 上一轮未提交改动」为依据继续推进，并把上述两项遗留痕迹一并纳入正式改动。**若那份意见文档在别处，请给出路径，我按它再迭代一轮即可。**

---

## 1. 范围与边界

**改动文件（2 个）**

- `deploy/show-v2/index.html` —— 课程展示站 `https://mf12.show.lingnan.top/core` 的实际页面，也是上一轮改动的落点
- `versions/feedback/modules/news/prototype/index-core.html` —— 新版反馈修订版核心页

两者 `<style>` 块在改动前完全一致（41,770 字符），因此共用同一份补丁。

**明确不改动**

| 对象 | 原因 |
|---|---|
| `frontend/index.html`、`modules/news/prototype/*` | 属于 `docs/review/legacy-files.json` 中受 SHA-256 保护的 V1 50 个文件，改动即触发 `check-legacy.cjs` 失败；仓库约定旧版原位保留 |
| `versions/feedback/.../index.html`（完整原型页） | 样式块已分叉（44,119 字符）且含开发标注，属开发用途，优先级低，列入后续建议 |
| 所有 JS 业务逻辑、API 绑定、提示词 | 本次只做界面层，不改变数据口径与分析行为 |

**改动方式**：在 `</style>` 前追加一段带版本标记的独立 CSS 补丁，不重写、不重排任何既有规则；HTML 只做语义化替换。好处是 diff 集中、review 容易、可整段删除回退。

---

## 2. UI 评审清单

| 优先级 | 问题 | 证据（改动前行号） | 影响 | 状态 |
|---|---|---|---|---|
| P0-1 | 深色模式下出现不跟随主题的硬编码色：`.validation-status` 用 `#fff4d8 / #8a5b00`，卡片光晕写死 `rgba(35,116,225,..)` | 399、335、386、402 | 深色模式亮黄底深字突兀；光晕与当前 `--accent` 不同步 | **已修** |
| P0-2 | 全局只有 3 处 `:focus`（66、259、300 行），按钮/链接/卡片/导航都没有可见焦点环 | 全文 | 键盘用户无法判断当前焦点 | **已修** |
| P0-3 | 导航项是 `<div class="nav-item">`，不可聚焦、不响应 Enter/Space、无按钮语义 | 627–631 | 键盘与读屏软件不可用 | **已修** |
| P0-4 | 顶栏 6 个 flex 项无窄屏断点；侧栏固定 212px 且 `sticky`；`<760px` 无规则 | 57–99 | 窄屏挤压、内容区被压缩 | **已修** |
| P0-5 | 无 `prefers-reduced-motion`，抽屉/弹层/卡片共 10 余处 transition | 207、334、384、539、543 等 | 前庭敏感用户不适 | **已修** |
| P0-6 | 顶栏 `.spacer` 与 `.searchbox` 同为 `flex:1`，窄屏平分剩余宽度 | 63、68 | 搜索框被压到约 100px 以下 | **已修** |
| P1-1 | 上一轮移除 logo 后品牌区失去视觉锚，且 `.brand .mark` / `.avatar` 成为死规则 | 60–61、76–77、606–607 | 顶栏左侧层次弱；样式表残留 | **已修**（仅展示站） |
| P1-2 | `main` 无最大宽度 | 99 | 2K/4K 屏正文行长过长 | **已修** |
| P1-3 | 页脚写着「示例数据仅用于界面评审，非真实行情与真实快讯」 | 732 | 与线上展示站身份冲突，误导观众 | **已修** |
| P2-1 | `.feed-col` / `.feedlist` 各定义两组互相覆盖的规则（500–505 行），前一组已成死代码 | 500–505 | 后续维护易误改 | 建议清理 |
| P2-2 | 大量内联 `style="padding:...;font-size:..."`（40 处以上） | 全文 | 样式难以统一调整 | 建议抽工具类 |
| P2-3 | 三个页面的 `<style>` 块完全相同却各自维护 | 多文件 | 改一处需手工同步，易分叉 | 建议抽公共样式表 |
| P2-4 | 第 10–14 行注释提到色板「已通过校验脚本」，但仓库内没有该脚本 | 10–14 | 设计约束无法复验 | 建议入库 |

---

## 3. 本次实际改动

### 3.1 两个页面共用的 CSS 补丁

追加在 `</style>` 前，标记 `UI 优化补丁 v1 · 2026-11-04`，包含 6 组规则：

1. **主题一致性**：新增 `--ui-halo`（浅/深两套），把 `.validation-status` 与 3 处卡片光晕改为 `var(--warn-soft)` / `var(--warn)` / `var(--ui-halo)`。
2. **键盘可达性**：`:where(button,a,input,select,textarea,[tabindex]):focus-visible` 统一 2px 焦点环（用 `!important` 压过 `.searchbox input{outline:none}`）；`.nav-item` 补 `appearance:none / width / text-align` 以适配 button 化。
3. **行长上限**：`main{max-width:1680px;width:100%;justify-self:center}`。
4. **响应式骨架**：
   - `<1080px`：隐藏次要的 `mkt-tag`，给 `.searchbox` 加 `min-width:0`；
   - `<820px`：隐藏品牌副标题、隐藏 `.topbar .spacer`（P0-6 根因）、收紧间距；
   - `<760px`：`.shell` 改单列，侧栏由 212px 竖列改为可横向滚动的标签条且不使用 `sticky`（避免吸顶遮挡正文），`.rail-col` / `.src-doc` 取消吸顶，统计卡改两列；
   - `<520px`：数据状态标签限宽、隐藏搜索图标并补偿输入框内边距。
5. **动效偏好**：`prefers-reduced-motion: reduce` 下统一收敛动画与过渡。
6. **展示站专属**（仅第 1 个文件）：`.brand::before` 加一条 3px 中性蓝色竖条作为品牌锚，**不恢复**「智」字标与 `SD` 头像，尊重上一轮去个人化的方向。

顶栏始终保持单行，因此 `.shell{padding-top:58px}` 与 `.sidebar{top:58px}` 无需改动，降低回归风险。

### 3.2 HTML 与文案

- 4 个 `<div class="nav-item">` → `<button type="button" class="nav-item">`。JS 用的是 `$$('.nav-item')` 与 `$$('.nav-item[data-screen]')`，class 与 `data-screen` 均保留，点击逻辑与 `classList.toggle('active')` 不变；button 额外带来原生键盘激活与语义。
- 页脚原型文案改为：「数据状态以页面顶部标识为准；外部数据源不可用时页面会明确回退为缓存或示例内容。结论为条件性推演，不构成投资建议或收益预测。」与 `README.md` 的边界声明一致。
- 仅展示站：删除已无对应 HTML 的 `.brand .mark`、`.avatar` 两条死规则。

### 3.3 新增交付物

| 文件 | 说明 |
|---|---|
| `docs/GitHub协作指南.md` | 项目添加、提交、推送、PR 合并、冲突处理、本仓库安全红线与可直接复制的命令 |
| `docs/UI优化说明.md` | 本文 |
| `docs/ui-preview/01-light-desktop.png` | 1440×900 浅色验证图 |
| `docs/ui-preview/02-dark-desktop.png` | 1440×900 深色验证图 |
| `docs/ui-preview/03-mobile-390.png` | 390×844 真机视口验证图 |

> 新增文件均不在 `tools/publish-files.json` 白名单（90 个文件）内，不会进入清洁上传包；如需随包分发，需手动加入白名单。

---

## 4. 验证结果

| 检查项 | 结果 |
|---|---|
| `git diff --stat` | 2 个文件，**+162 / −16**，改动集中在补丁区块与顶栏/页脚，无整文件变更 |
| 行尾一致性 | 两文件仍为纯 CRLF（`bareLF = 0`），未因编辑触发全文件 diff |
| `node tools/check-legacy.cjs` | `checked 50 / changed 15` —— **既有基线过期问题，与本次改动无关**（见第 5 节） |
| `node tools/prepare-release.cjs --check` | `publish_files: 90`、`forbidden_or_secret_hits: 15`（同上，均为 legacy 项）、`history_secret_hits: 0`、`local_secret_values_checked: 0` |
| `node tools/test-release.cjs` | `PASS`（打包态 HTTP 回归：版本标识、最新行情与事前输入隔离、单次模型调用、公司范围、显式受限回退） |
| 浏览器渲染（Edge 156 headless，`file://` 示例数据回退态） | 浅色桌面、深色桌面、390×844 移动端三种场景均正常 |
| 390px 真机视口（CDP `Emulation.setDeviceMetricsOverride`） | `vw=390, sw=390, noHorizontalOverflow=true`；`topbarSpacer=none`；`sidebarDirection=row`；搜索框 111px；唯一超出视口的元素是横向导航条内可滚动项与本来就隐藏的 K 线抽屉 |
| 交互回归 | JS 文件零改动；导航选择器与 `dataset.screen` 在 button 上仍匹配，`showScreen()` 行为不变 |

**关于截图的一个方法说明**：Edge 无头模式用 `--window-size=390,844` 时实际视口被钳制到 508px，直接截图会出现「右侧被裁」的假象。上述 390px 结论通过 CDP 设备模拟获得，`scrollWidth == clientWidth`，是可靠的无溢出证据。

---

## 5. 顺带发现的两个既有问题（本次未改）

1. **V1 哈希基线已过期。** `docs/review/legacy-files.json` 的 `baseline_commit` 停在 `cd69233`（11-02 复核时点），其后 3 个提交改动过 V1 目录（例如 `modules/news/prototype/index-core.html` 被删去 183 行），基线未同步；另有部分文件因 `core.autocrlf=true` 的 CRLF 行尾与脚本直接读工作区字节的口径不一致。结果就是**任何人在当前 clone 上运行 `--check` 都会看到 15 项失败**，容易掩盖真正的密钥问题。修复方式：在新基线上重生成清单，或把 `check-legacy.cjs` 改为对 Git blob 计算哈希并做行尾归一化。详见协作指南第 7 节。

2. **示例数据下右栏开市日历脚注出现 `undefined (undefined)`。** 三张验证截图均可见「下一次休市上班: undefined (undefined)」。这是示例数据缺少对应字段导致的展示层问题，属数据/JS 范畴，不在本次界面补丁范围，建议由负责新闻与日历模块的同学处理。

---

## 6. 未做事项与建议（需小组决策）

1. **是否同步到 V1 页面**：`frontend/index.html` 与 `modules/news/prototype/index-core.html` 有完全相同的 P0 问题，但要改就必须同步更新 `legacy-files.json` 基线，并全组确认「V1 保持原样」的约定是否调整。**本次未动。**
2. **是否同步到 `versions/feedback/.../index.html`（完整原型页）**：样式块已分叉，需单独适配；该页含开发标注，属开发用途。
3. **抽取公共样式表**：当前 3 个页面各自内嵌 4 万字符 CSS，长期必然分叉；建议抽为单文件后在三个入口引用。改动面较大，适合单独开一个 PR。
4. **把色板校验脚本入库**：页面注释声称「已通过校验脚本」，但仓库内无该脚本，设计约束无法复验。
5. **原型残留文案**：词云口径「…· 示例数据」（726 行）、K 线抽屉默认副标题「示例数据」（1069 行）等，建议与页脚一起统一清理，需确认展示站在真实数据下是否仍有回退态文案需求。

---

## 7. 回退方法

- **整段回退 CSS**：删除两个文件中从 `/* UI 优化补丁 v1 · 2026-11-04 */` 到 `</style>` 之间的内容，样式即恢复原状。
- **HTML 回退**：把 4 个 `<button type="button" class="nav-item ...">…</button>` 改回 `<div class="nav-item ...">…</div>`；页脚文案改回原文。
- **Git 级回退**：`git checkout -- <文件路径>` 会把文件恢复到 `47cdb6a`，**但会同时清掉上一轮那两行未提交的顶栏删改**，使用前先备份。
- **新增文档与截图**：直接删除即可，不影响任何既有校验与发布白名单。

---

## 8. 提交与合并

完整命令见 `docs/GitHub协作指南.md` 第 8 节。要点：

- 在 `feature/ui-polish-20261104` 上提交 → 推送分支 → 发起 PR 到 `main` → 至少一位组员复核后合并。
- `deploy/show-v2/` 不在发布白名单内，**改动不会进入清洁包**；上线展示站需按 `deploy/show-v2/README.md` 单独部署。
- PR 建议附上 `docs/ui-preview/` 的三张截图，并在描述中注明第 5 节的既有校验失败，避免被误判为本次引入的回归。
