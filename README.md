# NotebookLM → Obsidian Export

一键将 NotebookLM 笔记本中的所有「来源指南」批量导出为 Obsidian Markdown 文件，带完整 YAML frontmatter。

## 这是什么？

Google NotebookLM 是一个 AI 研究助手，你可以上传文档、PDF、网页、YouTube 视频，AI 会为每个来源生成「来源指南」（摘要、关键问题、建议等）。但 NotebookLM 不提供批量导出功能。

这个工具利用 macOS 的 JXA (JavaScript for Automation)，直接操控已登录的 Chrome 浏览器，**无需 API、无需 cookie 注入、无需重新登录**，自动遍历所有笔记本和来源，把 AI 生成的内容保存为干净的 `.md` 文件。

## 功能

- 📓 支持「我的笔记本」「与我共享」「精选笔记本」
- 📄 支持所有来源类型：文档、PDF、YouTube、网页、文本
- 🏷️ 自动生成 YAML frontmatter（类型、标签、日期、来源 URL）
- 🧹 自动清理 UI 干扰内容，保留纯净正文
- 📂 按笔记本名称自动创建子文件夹

## 前置条件

- **macOS**（依赖 JXA，不支持 Windows/Linux）
- **Chrome** 浏览器，已登录 NotebookLM 的 Google 账号
- **Chrome 开发者设置**：`菜单栏 → 显示 → 开发者 → 允许 Apple 事件中的 JavaScript`
- **cliclick**：`brew install cliclick`
- **Python 3.6+**

## 安装

```bash
git clone https://github.com/yi923507762-lgtm/notebooklm-obsidian-export.git
cd notebooklm-obsidian-export
brew install cliclick
```

## 使用

### 1. 获取笔记本 UUID

打开 https://notebooklm.google.com/，进入你要导出的笔记本。URL 格式为：

```
https://notebooklm.google.com/notebook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

复制 UUID 部分。

### 2. 运行导出

```bash
python3 notebooklm_auto_v3.py <uuid1> <uuid2> ...
```

可以一次传入多个 UUID，脚本会依次处理。

### 3. 输出

文件保存在 `raw/notebooklm/<笔记本名>/<来源名>.md`，格式如下：

```yaml
---
type: notebooklm-clip
notebook: "钟老师-TK顶级内容思维"
source: "4-12.docx"
source_type: "article"
date_clipped: 2026-05-01
url: https://notebooklm.google.com/notebook/...
tags: [notebooklm, article]
---
```

## 性能

- 每个来源约 4-5 秒
- 25 个来源的笔记本约 2 分钟
- 360 个来源（30 个笔记本）约 25-30 分钟

导出期间 Chrome 需要保持在前台。

**增量导出**：已导出的来源会被自动跳过（基于文件名检测），可以安全地重复运行。

## 工作原理

```
Python 脚本
  → base64 编码 JavaScript 代码
    → JXA (JavaScript for Automation) 桥接
      → 在 Chrome 当前标签页中执行 JavaScript
        → 点击「来源」面板 → 遍历每个来源 → 提取内容
          → 写回 Python → 保存为 .md 文件
```

核心技巧：利用 Angular Material 的 `.click()` 原生方法（而非 `dispatchEvent`），触发 NotebookLM 的 SPA 导航。

## 局限性

- 约 5-10% 的来源因特殊字符（emoji、中文括号等）匹配失败
- 内容提取基于启发式规则（扫描 DOM 元素），NotebookLM 界面改版可能需要调整
- 支持增量导出：已存在的文件自动跳过，可安全重复运行
- 仅支持 macOS

## 与 Obsidian 知识库集成

这个工具最初为「第二大脑」Obsidian 知识库系统设计。导出后的文件可以配合该系统的 [NotebookLM 批量导入工作流](CLAUDE.md) 自动归类到 `raw/notebooklm/` 目录并提取概念。

## License

MIT
