# FinSight 项目在 GitHub 上的「添加」与「合并」操作指南

> 适用仓库：`https://github.com/zhixiny581-max/FinSight`
> 编写日期：2026-11-04
> 本指南只讲协作流程与命令，不涉及业务逻辑改动。所有命令在仓库根目录执行（Git Bash / PowerShell 均可）。

---

## 0. 先给结论

**你的项目已经完整托管在 GitHub 上，不需要再「添加项目」。** 当前本地 `AI智能体设计/FinSight` 就是一份完整的 clone，`origin` 已指向该仓库，默认分支 `main`，本地与远端 `main` 都停在提交 `47cdb6a`（2026-11-03）。

因此真正要做的是这条链路：

```
在功能分支提交改动 → 推送分支到 GitHub → 发起 Pull Request → 小组复核 → 合并进 main → 同步本地并清理分支
```

「添加」和「合并」在小组语境里通常各有两种含义，先对齐，避免操作错对象：

| 词 | 含义 A（Git 层） | 含义 B（GitHub 层） |
|---|---|---|
| 添加 | `git add`：把工作区改动加入暂存区 | 把本地项目接入远端仓库：`clone` / `git remote add` + 首次 `push`；或在网页端上传文件 |
| 合并 | `git merge` / `git rebase`：把一条分支的历史并入另一条 | Pull Request 被 `Merge`，改动进入 `main` |

**本项目一律走 PR 合并，不要直接 `push` 到 `main`。** 仓库历史上已有 3 次 PR 合并（#1 `market-backend-ifind`、#2 `feature/news-import-20260924`、#3 `adding-analysis-module`），这是团队已建立的约定。

---

## 1. 现状核对（先跑一遍，确认自己在哪）

```bash
git remote -v                 # 应显示 origin → https://github.com/zhixiny581-max/FinSight.git
git branch -a                 # 本地分支 + remotes/origin/* 分支
git status                    # 工作区是否干净
git log --oneline -8          # 最近提交
git rev-parse --abbrev-ref HEAD
```

当前实测状态：

- 本地分支：`feature/ui-polish-20261104`（当前所在）、`main`
- 远端分支：`main`、`111`、`adding-analysis-module`、`feature/news-import-20260924`、`market-backend-ifind`
- 本地未提交改动：`deploy/show-v2/index.html`（顶栏移除了「智」字标识与 `SD` 头像两行）
- Git 全局配置：`user.name=sanda`、`core.autocrlf=true`、`core.quotepath=false`、`init.defaultbranch=main`（后两项对中文文件名与换行符很重要，不要改）

---

## 2. 场景 A：新组员把项目「添加」到自己电脑（最常见）

```bash
git clone https://github.com/zhixiny581-max/FinSight.git
cd FinSight
git config user.name  "你的名字"          # 仅本仓库生效，便于 PR 署名
git config user.email "你的GitHub绑定邮箱"
```

**权限说明（容易踩坑）：**

- 读取公开仓库不需要任何凭证。
- 推送需要该仓库的 **Collaborator 权限**（由 owner `zhixiny581-max` 在 `Settings → Collaborators` 添加），或者改用 fork 流程（见场景 D）。
- HTTPS 推送时 GitHub **不接受账号密码**，需要 Personal Access Token（PAT）：`Settings → Developer settings → Personal access tokens → Fine-grained tokens`，勾选目标仓库的 Contents 读写权限；或用 `git credential-manager` 登录。
- 也可以避免输 token，改走 SSH：

```bash
git remote set-url origin git@github.com:zhixiny581-max/FinSight.git
```

按各版本 `.env.example` 配置自己的密钥（**`.env` 永不提交**）。

---

## 3. 场景 B：把一份本地已有代码「添加」到新建的空 GitHub 仓库

仅适用于「先在 GitHub 建了空仓库、本地代码还没关联」的情况。**本仓库不属于此场景，不要执行。**

```bash
cd 你的项目目录
git init -b main
git remote add origin https://github.com/<owner>/<repo>.git
git add .
git commit -m "Initialize project"
git push -u origin main
```

如果远端仓库**已经有内容**（例如已有 README），先同步再推：

```bash
git pull --rebase origin main
git push -u origin main
```

**禁止用 `git push --force` 覆盖他人已有的提交。** 这是小组仓库最常见的不可逆事故。

---

## 4. 场景 C：日常功能协作（推荐主流程）

以本次 UI 优化为例，完整可复制序列：

```bash
# 1) 从最新 main 开工
git switch main
git pull --ff-only origin main

# 2) 建功能分支（本次已经建好，无需重复）
git switch -c feature/ui-polish-20261104

# 3) 改文件后，只暂存明确的文件，不要 git add .
git add deploy/show-v2/index.html \
        versions/feedback/modules/news/prototype/index-core.html \
        docs/GitHub协作指南.md docs/UI优化说明.md

# 4) 提交前确认暂存内容
git status --short
git diff --cached --stat

# 5) 提交
git commit -m "Polish showcase UI: theme tokens, focus states, responsive topbar"

# 6) 推送分支（首次需要 -u 建立追踪）
git push -u origin feature/ui-polish-20261104
```

推送后在 GitHub 网页端：

1. 仓库页会出现黄色提示条 `Compare & pull request` → 点击；或 `Pull requests → New pull request`。
2. `base: main` ← `compare: feature/ui-polish-20261104`，确认 diff 里**只有预期文件**。
3. 标题写清改动范围；描述里说明「改了什么 / 怎么验证 / 是否影响旧版 V1」。
4. 指定 reviewer（至少一位组员），提交 PR。
5. 复核通过后点 `Merge pull request`。

**三种合并策略的取舍：**

| 策略 | 结果 | 适用 |
|---|---|---|
| **Create a merge commit**（推荐本仓库） | 保留完整分支历史，产生一个合并提交 | 与仓库现有 #1/#2/#3 的历史风格一致，便于回溯 |
| Squash and merge | 分支上所有提交压成一个 | 分支内提交很碎、message 不规范时 |
| Rebase and merge | 线性历史，无合并提交 | 团队统一要求线性历史时；不要在公共分支上用 |

**合并后收尾：**

```bash
git switch main
git pull --ff-only origin main
git branch -d feature/ui-polish-20261104          # 删除本地已合并分支
git push origin --delete feature/ui-polish-20261104   # 删除远端分支（GitHub 也会提示按钮）
```

---

## 5. 「合并」的另一层：把 main 的更新合回自己的分支

多人并行时（当前远端有 `111`、`adding-analysis-module` 等活跃分支），别人的 PR 先合并会让你的分支落后：

```bash
git fetch origin
git rebase origin/main          # 推荐：历史干净
# 或保守做法：
# git merge origin/main         # 会产生一个合并提交
```

若出现冲突：

```bash
git status                      # 列出 both modified 的文件
# 用编辑器打开文件，定位 <<<<<<< ======= >>>>>>> 三段，保留正确内容并删除标记
git add <冲突文件>
git rebase --continue           # 若用 merge，则 git commit
# 中途放弃：git rebase --abort / git merge --abort
```

**本仓库的冲突高危区**：`deploy/show-v2/index.html`、`versions/feedback/modules/news/prototype/index-core.html`、`modules/news/prototype/index-core.html` 三个页面的 `<style>` 块原本完全相同。多人同时改样式极易冲突。约定：**同一时间只有一个人在改同一页面的样式块；改动以追加独立 CSS 区块的方式落地，不要重排既有规则。**

---

## 6. 场景 D：没有写权限时（Fork + PR）

```bash
# GitHub 网页端点 Fork，然后
git clone https://github.com/<你的账号>/FinSight.git
cd FinSight
git remote add upstream https://github.com/zhixiny581-max/FinSight.git
git switch -c feature/xxx
# ... 改、提交、push 到自己的 fork ...
git push -u origin feature/xxx
# 在 GitHub 上发起 PR 时，base 选 zhixiny581-max/FinSight 的 main

# 保持 fork 与上游同步
git fetch upstream
git rebase upstream/main
```

---

## 7. 本仓库特有的安全红线（推送前必读）

这些约束来自根 `README.md` 与 `tools/prepare-release.cjs`，**不是通用 Git 规则，但违反会直接造成密钥泄露或交付校验失败**：

1. **推送前跑一次检查**：

   ```bash
   node tools/prepare-release.cjs --check
   ```

   该命令会核对 `tools/publish-files.json` 白名单（103 个文件）、扫描本机 `.env` 与 `deploy/show-v2/api-config.json` 中的真实密钥值、检查 Git 历史里是否曾提交过密钥，以及调用 `tools/check-legacy.cjs` 校验 V1 的 50 个文件哈希。理想输出是 `forbidden_or_secret_hits: 0` 且 `history_secret_hits: 0`。

   **已知既有问题（2026-11-04 实测，非本次改动引入）**：当前 clone 上 `check-legacy.cjs` 返回 `changed: 15`，导致 `--check` 报告 `forbidden_or_secret_hits: 15`。原因是 `docs/review/legacy-files.json` 的 `baseline_commit` 仍停在 `cd69233`（11-02 复核时点），而之后的 3 个提交改动过 V1 目录（例如 `modules/news/prototype/index-core.html` 被删去 183 行），基线未同步；另有部分文件受 CRLF 行尾影响，而校验脚本直接读工作区字节。这 15 项**不是密钥命中**（`history_secret_hits: 0`、`local_secret_values_checked: 0`）。修复方式二选一：①由负责交付复核的同学在新基线上重新生成 `legacy-files.json`；②把 `check-legacy.cjs` 改为对 Git blob 计算哈希并做行尾归一化。修复前，PR 描述里应注明该校验的既有失败，避免被误判为新回归。

2. **绝不提交**：`.env`、`mcp_config.json`、`**/data/`、`*.log`、运行审计、个人导入记录、`release/`。`.env.example` 空模板可以提交。

3. **网页端手动拖文件上传不受 `.gitignore` 保护**。如果必须用网页上传（而非 Git 推送），只能上传清洁包：

   ```bash
   node tools/prepare-release.cjs        # 生成 release/FinSight-GitHub.zip
   ```

   解压后只上传包内的 `FinSight` 文件夹内容。

4. **V1 的 50 个文件受 SHA-256 保护**（清单见 `docs/review/legacy-files.json`），包括 `frontend/index.html`、`modules/news/prototype/index.html` 与 `index-core.html`。改动任何一个都会让 `node tools/check-legacy.cjs` 返回 `changed > 0`。**本次 UI 优化因此不触碰 V1。**

5. **双版本目录隔离**：不要把 `versions/feedback/` 整体覆盖到 `modules/`；两版各自独立的 `.env`、缓存与分析记录。

6. **`deploy/show-v2/` 只把辅助脚本与空模板纳入清洁包**（`config_store.py`、`setup_keys.py`、`open_config.py`、`打开配置文件.cmd`、`api-config.example.json` 等）。`index.html`、`app.py` 这类部署主体仍不在 `publish-files.json` 内，需要按 `deploy/show-v2/README.md` 单独部署到展示站（`https://mf12.show.lingnan.top/core`）。

7. **`deploy/show-v2/api-config.json` 是本机密钥文件，永不提交**。它由 `打开配置文件.cmd` 从 `api-config.example.json` 生成，展示机与同学各自填写。三重拦截：`.gitignore` 的 `**/api-config.json`、`prepare-release.cjs` 的 `forbidden` 规则、以及打包前对其中真实值的泄漏扫描。详见 [接口配置说明](接口配置说明.md)。

8. 新增的文档若要随清洁包分发，需手动把路径加入 `tools/publish-files.json`；否则它们只存在于 Git 仓库中。

---

## 8. 当前这次改动的具体落地命令

本次工作已在本地 `feature/ui-polish-20261104` 分支上完成（含你此前未提交的顶栏两行删改）。确认无误后：

```bash
cd "C:/Users/Sanda/Desktop/SYSU/AI智能体设计/FinSight"

node tools/check-legacy.cjs            # 当前基线过期，预期 changed: 15（既有问题，见第 7 节）
node tools/prepare-release.cjs --check # 重点确认 history_secret_hits: 0；15 项为 legacy 基线，非密钥
node tools/test-release.cjs            # 期望 PASS

git add deploy/show-v2/index.html \
        versions/feedback/modules/news/prototype/index-core.html \
        docs/GitHub协作指南.md docs/UI优化说明.md
git status --short
git commit -m "Polish showcase UI: theme-safe colors, focus visibility, responsive shell"
git push -u origin feature/ui-polish-20261104
```

随后在 GitHub 发起 PR 到 `main`。

> 说明：当前执行环境的 Git HTTPS 出口返回 `CONNECT tunnel failed, response 502`（网络代理限制），所以 `git fetch/push` 无法在这里代跑，请在你本机正常网络下执行推送。本地的提交与校验已经可以离线完成。

---

## 9. 常见报错与处理

| 现象 | 原因 | 处理 |
|---|---|---|
| `CONNECT tunnel failed, response 502` | 代理/网络拦截 | 换网络；或 `git config --global http.proxy <可用代理>`；或改 SSH |
| `Permission denied (publickey)` / `403` | 无 Collaborator 权限或凭证过期 | 让 owner 加 Collaborator，或重新生成 PAT；或走 Fork 流程 |
| `! [rejected] non-fast-forward` | 远端已有你本地没有的提交 | `git pull --rebase origin <branch>` 后再推，不要 force |
| `both modified: xxx.html` | 两人改了同一处 | 按第 5 节处理冲突；必要时与对方确认保留哪一段 |
| 中文文件名显示成 `\344\270\255...` | `core.quotepath=true` | `git config core.quotepath false`（本机已设） |
| 提交后整文件 diff | CRLF/LF 不一致 | 保持 `core.autocrlf=true`（本机已设），不要批量转换行尾 |

---

## 10. 建议写进小组约定的四条

1. `main` 设为保护分支：禁止直接 push，必须经 PR + 至少 1 人 review。
2. 分支命名统一 `feature/<主题>-<日期>` 或 `fix/<问题>-<日期>`；合并后即删分支，避免远端堆积（当前已有 4 个长期未清理分支）。
3. 提交信息用「动词 + 范围 + 目的」，例如 `Polish showcase UI: fix dark-mode badge colors`。
4. 每次 PR 描述固定三项：**改动范围 / 验证方式 / 是否影响旧版 V1 的哈希校验**；涉及 UI 的 PR 附浅色、深色、窄屏三张截图。
