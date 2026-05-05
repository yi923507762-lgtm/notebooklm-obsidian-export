---
name: notebooklm-export
description: Export ALL NotebookLM source guides to Obsidian Markdown via Playwright. Connects to the user's existing Chrome (CDP port 9222) to preserve login state, then navigates each notebook, clicks every source, extracts AI-generated source guide content, and saves clean frontmatter-rich .md files to the vault. Use when the user wants to bulk export NotebookLM notes, migrate from NotebookLM, or back up NotebookLM content to local Obsidian vault.
---

# NotebookLM → Obsidian Export（Playwright 版）

通过 Playwright 连接用户已登录的 Chrome，操控它导出所有 NotebookLM 笔记本的来源指南。

## What It Does

1. Connects to the user's existing Chrome via CDP (port 9222) — no re-login needed
2. Discovers all notebooks with import status (🆕 / 📥 / ✅) — auto-detects what's already in vault
3. Opens each notebook, clicks "来源" (Sources) tab, iterates every source
4. Skips already-exported sources (checks file existence before processing) — **zero duplicate guarantee**
5. Extracts AI-generated source guide content + metadata (author, publish date, description, source type)
6. Saves clean `.md` with Obsidian Web Clipper-style YAML frontmatter
7. Output: `raw/notebooklm/<笔记本名>/<来源名>.md`

## Prerequisites

- **Playwright Python** installed:
  ```bash
  pip3 install playwright
  python3 -m playwright install chromium
  ```

- **Chrome** launched with remote debugging enabled. ⚠️ Chrome 安全策略要求 `--remote-debugging-port` 必须搭配**非默认** `--user-data-dir`。解决方法是先把默认 profile 的登录文件复制到新目录：

  ```bash
  # 一次性：复制登录态到调试用 profile
  mkdir -p ~/.chrome-debug-profile/Default
  for f in "Cookies" "Login Data" "Web Data" "Preferences"; do
    cp "$HOME/Library/Application Support/Google/Chrome/Default/$f" \
       "$HOME/.chrome-debug-profile/Default/$f" 2>/dev/null
  done

  # 启动 Chrome（每次使用前）
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --remote-debugging-port=9222 \
    --user-data-dir="$HOME/.chrome-debug-profile" \
    "https://notebooklm.google.com/"
  ```

> ℹ️ No cliclick, no JXA, no "Allow JavaScript from Apple Events" — just Playwright + CDP.

> ⚠️ **登录态刷新**：如果你在默认 Chrome 中新登录了服务，需要重新复制 `Cookies` 和 `Login Data` 文件到 `~/.chrome-debug-profile/Default/`。

## How to Use

### 1. Launch Chrome with CDP

```bash
# 关闭现有 Chrome（如果有），再启动
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.chrome-debug-profile" \
  "https://notebooklm.google.com/"
```

确认已登录 NotebookLM。

### 2. Discover notebooks

```bash
python3 export_notebooklm_pw.py
```

This lists all visible notebooks with their UUIDs. No export happens — just discovery.

### 3. Export specific notebooks

```bash
# Export one notebook
python3 export_notebooklm_pw.py <uuid1>

# Export multiple
python3 export_notebooklm_pw.py <uuid1> <uuid2> <uuid3>

# Dry-run: scan sources without saving
python3 export_notebooklm_pw.py --dry-run <uuid>
```

The script:
- Navigates to each notebook
- Clicks "来源" to expand the source panel
- Clicks each source via `.source-stretched-button`
- **Skips already-exported sources** by filename check
- After each source, navigates back to the notebook root (fresh state)
- Re-opens source panel before next source

### 4. Output format

Rich YAML frontmatter matching Obsidian Web Clipper's property model:

```yaml
---
type: notebooklm-clip
notebook: "CLI 爬取测试"
source: "粘贴的文字"
source_type: "text_snippet"
date_clipped: 2026-05-06
url: https://notebooklm.google.com/notebook/0a89513c-...
author: "梁毅"                      # optional — extracted if found
published: "2026年5月5日"           # optional — extracted if found
description: "这段源文本描述了一个针对命令行界面..."  # AI-generated summary
tags: [notebooklm, text_snippet]   # source_type included when known
---

# 粘贴的文字

> 📝 文本 · 来自 NotebookLM 笔记本「CLI 爬取测试」
>
> 来源指南 · AI 生成的内容分析

---

<AI-generated source guide content — UI chrome stripped>

---

*由 NotebookLM 来源指南自动导入 · 2026-05-06*
```

**Source type labels** in the blockquote:
| source_type | Label |
|---|---|
| `article` | 📄 文档 |
| `drive_pdf` | 📕 PDF |
| `video_youtube` | 🎬 YouTube |
| `text_snippet` | 📝 文本 |
| `web_link` | 🌐 网页 |
| `unknown` | 📎 来源 |

## Technical Architecture

### Core Mechanism: Playwright CDP

The script uses Playwright's `connect_over_cdp()` to attach to an already-running Chrome instance:

```python
pw = await async_playwright().start()
browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
```

This means:
- **No new browser instance** — reuses the user's existing Chrome
- **No re-authentication** — cookies, sessions, login state all preserved
- **No cookie injection** — the browser is already authenticated
- **Cross-platform** — Playwright runs on macOS, Linux, Windows

### Click Strategy

1. **Primary**: `page.evaluate()` to execute `el.click()` on `.source-stretched-button` inside `.single-source-container` — directly invokes Angular's click handler
2. **Retry on failure**: Re-open the source panel, wait 1s, try clicking again
3. **Recovery**: Navigate back to notebook root and re-open panel

**Key insight**: Angular Material's event delegation ignores `dispatchEvent()` and synthetic clicks. Only native `.click()` on the correct element triggers the source navigation. Playwright's `page.evaluate()` lets us run the exact same JS that works in the JXA version.

### Content Extraction

Source guide content is found by scanning all `<div>` elements for the largest one containing "来源指南" text. UI chrome is stripped using a skip-list of known sidebar patterns (button labels, icon names, navigation elements).

**Metadata extraction** (run in-page via `page.evaluate()`):
- **Source name**: 3-level fallback — `aria-label` on `.source-stretched-button` → text after `collapse_content` marker → `<h1>` text
- **Source type**: Page text regex → source name pattern fallback (e.g., `粘贴` in name → `text_snippet`, `.pdf` → `drive_pdf`)
- **Author**: Regex match on `作者`/`Author`/`by` patterns
- **Published date**: First `YYYY年M月D日` or `YYYY-MM-DD` pattern
- **Description**: First substantial non-UI paragraph (>30 chars)

### Content Cleaning

`clean_content()` strips NotebookLM UI chrome:
- Skip-list prefixes: `group`, `add`, `PRO`, `collapse`, `arrow_drop`, `share`, `settings`, etc.
- Removes the standard NotebookLM disclaimer footer
- Preserves only the actual source guide content

### Incremental Export

Before processing each source, the script checks if the output `.md` file already exists in `raw/notebooklm/<笔记本名>/<来源名>.md`. If it does, the source is skipped. Safe to re-run — only new sources are processed.

## Discovery Mode

Without UUID arguments, the script lists all visible notebooks with import status:

```
🔍 扫描 NotebookLM 笔记本...

找到 37 个笔记本：

  🆕 未导入: 6  |  📥 部分导入: 5  |  ✅ 已完成: 26

  [1] 🆕 The Atlantic 来自 The Atlantic 的进步故事 (71 sources)
      UUID: 61ac4bed-64b9-4ef2-83a4-6c4fefb07b2a

  [2] ✅ 健身 (22 sources)
      UUID: 9845f031-976e-4657-b428-382597a22c63

  [3] 📥 科赛-塞弗体系 (28 sources)
      已导入: 27/28
      UUID: 5cbc85db-3e24-482c-a244-6ed9be437f20

用法：python3 export_notebooklm_pw.py <uuid> [uuid2 ...]
      python3 export_notebooklm_pw.py --dry-run <uuid>   # 试跑不保存
```

**Import status indicators:**
- 🆕 `new` — no files in vault yet
- 📥 `partial` / `near` — some sources imported, some missing
- ✅ `complete` / `empty` — all sources imported (or notebook has 0 sources)

## Troubleshooting

### "无法连接 Chrome"

Chrome isn't running with the debug port. Start it with:
```bash
chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-devtools-profile
```

Or close all Chrome windows first, then re-launch with the flag.

### "0 sources found"

The source panel isn't expanded. The script clicks the "来源" tab, but if the DOM structure differs:
1. Manually verify the notebook has sources
2. Check that clicking "来源" actually expands the panel
3. Some featured notebooks have a different layout

### Click failures on specific sources

Source names with special characters (`（`, `）`, `#`, emoji) can cause string matching failures in the JavaScript template literal. The script escapes quotes and backslashes, but ~5-10% failure rate is possible. The retry + recovery mechanism handles most cases.

### Port 9222 already in use

```bash
# Find the process
lsof -i :9222

# Kill it, then re-launch Chrome
```

## Performance

- ~4-5 seconds per source (navigation + click + extract + save)
- ~100-120 sources per 10 minutes
- A notebook with 25 sources takes ~2 minutes
- Full 30-notebook export with ~360 sources: ~25-30 minutes
- **Unlike JXA version**: Chrome doesn't need to be frontmost — you can use your computer during export

## Limitations

1. **Not 100% click-reliable**: ~3-5% of sources may fail to click due to special characters in names; the retry + recovery mechanism handles most cases
2. **Content extraction is heuristic**: Uses "largest div with 来源指南" — may miss content if NotebookLM DOM changes significantly
3. **Author extraction is best-effort**: Depends on regex patterns (`作者`, `Author`, `by`); many NotebookLM sources lack explicit author metadata
4. **Source type detection**: Page text regex first, then source name pattern fallback — covers most cases but edge cases exist
5. **Incremental export**: Already-exported sources are skipped by filename check — safe to re-run as many times as needed
6. **Source types handled**: Articles, PDFs, YouTube videos, text snippets, web links, and pasted text
7. **Single session**: All notebooks must be accessible from the same Google account in the connected Chrome
8. **Featured/public notebooks**: Discovery mode lists ALL visible notebooks including NotebookLM's featured suggestions; filter by UUID for your own

## Files

- `export_notebooklm_pw.py` — The Playwright automation script (self-contained, single file)
- `notebooklm_auto_v3.py` — Original JXA version (preserved as fallback)
- This `SKILL.md` — Documentation
