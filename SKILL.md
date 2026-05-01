---
name: notebooklm-export
description: Export ALL NotebookLM source guides to Obsidian Markdown. Extracts AI-generated source guide content from every source in every notebook and saves clean, frontmatter-rich .md files to the vault. Use when the user wants to bulk export NotebookLM notes, migrate from NotebookLM, or back up NotebookLM content to local Obsidian vault.
---

# NotebookLM → Obsidian Export

Exports every source guide from every NotebookLM notebook into the vault as clean Markdown files with YAML frontmatter.

## What It Does

1. Opens each notebook (personal, shared, or featured)
2. Clicks the "来源" (Sources) tab to reveal the source panel
3. For each source: clicks it, waits for the source guide to load, extracts the AI-generated analysis
4. Saves as a formatted `.md` file with frontmatter, saved under `notebooklm/<笔记本名>/<来源名>.md`

## Prerequisites

- **Chrome** must be open and logged into the Google account that has NotebookLM access
- **"Allow JavaScript from Apple Events"** must be enabled in Chrome (菜单栏 → 显示 → 开发者)
- **cliclick** must be installed: `brew install cliclick` (used as fallback for coordinate clicks)
- **Obsidian** should be running (not strictly required, but the vault is the target)

## How to Use

### 1. Confirm Chrome is ready

Chrome must be open with the NotebookLM Google account logged in. The script uses the first tab of the first window.

### 2. Discover notebooks

Ask the user which notebooks to export, or discover them automatically:

```
Navigate Chrome to https://notebooklm.google.com/
Click through tabs: "我的笔记本", "与我共享", "精选笔记本"
Extract all UUIDs by reading the page DOM
```

### 3. Choose which to export

NotebookLM has three sections:
- **我的笔记本** (My notebooks) — user-created
- **与我共享** (Shared with me) — shared by others
- **精选笔记本** (Featured) — pre-made by Google

Ask the user which sections to export. Personal and shared are usually the priority.

### 4. Run the export

Use the automation script at `notebooklm_auto_v3.py` (in this skill folder):

```bash
python3 notebooklm_auto_v3.py <uuid1> <uuid2> ...
```

The script:
- Navigates to each notebook
- Clicks "来源" to expand the source panel
- Clicks each source via `.source-stretched-button.click()`
- Extracts the source guide content
- Saves to `notebooklm/<笔记本名>/<来源名>.md`

### 5. Output format

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

# 4-12.docx

> 📄 文档 · 来自 NotebookLM 笔记本「钟老师-TK顶级内容思维」
>
> 来源指南 · AI 生成的内容分析

---

<AI-generated source guide content>

---

*由 NotebookLM 来源指南自动导入 · 2026-05-01*
```

## Technical Architecture

### Core Mechanism

The automation uses **JXA (JavaScript for Automation)** to execute JavaScript in Chrome's existing tabs via Apple Events. This avoids:

- Opening new browser instances
- Re-authenticating
- Cookie injection problems
- CORS issues

### Click Strategy

1. **Primary**: `.source-stretched-button.click()` — directly invokes Angular's click handler
2. **Fallback**: `cliclick` at screen coordinates (calculated from viewport + window position + toolbar)

**Key insight**: Angular Material's event delegation ignores `dispatchEvent()` and synthetic clicks. Only native `.click()` on the correct element (`.source-stretched-button` inside `.single-source-container`) triggers the source navigation.

### Content Extraction

Source guide content is found by scanning all `<div>` elements for the largest one containing "来源指南" text. UI chrome is stripped using a skip-list of known sidebar patterns.

### Base64 Bridge

JavaScript payloads are base64-encoded in Python, decoded via ObjC bridge in JXA, and executed in Chrome. This avoids multi-level string escaping hell:

```
Python → base64 encode → JXA → ObjC.NSData decode → tab.execute(js)
```

## Troubleshooting

### "0 sources found"

The source panel isn't expanded. The script clicks the "来源" tab, but if the DOM structure differs:
1. Manually verify the notebook has sources
2. Check that clicking "来源" actually expands the panel
3. Some featured notebooks have a different layout

### Click failures on specific sources

Source names with special characters (`（`, `）`, `#`, emoji) can cause string matching failures in the JavaScript template literal. The script escapes quotes and backslashes, but Unicode characters in attribute selectors can still fail. ~5-10% failure rate is expected.

### "Allow JavaScript from Apple Events" not enabled

The menu item is in Chinese Chrome: `显示 → 开发者 → 允许 Apple 事件中的 JavaScript`

To enable programmatically (as fallback):
```bash
osascript -e '
tell application "System Events"
    tell process "Google Chrome"
        tell menu bar 1
            tell menu bar item "显示"
                tell menu "显示"
                    click menu item "开发者"
                end tell
            end tell
        end tell
    end tell
end tell'
```

## Performance

- ~4-5 seconds per source (navigation + click + extract + save)
- ~100-120 sources per 10 minutes
- A notebook with 25 sources takes ~2 minutes
- Full 30-notebook export with ~360 sources: ~25-30 minutes

## Limitations

1. **Not 100% reliable**: ~5-10% of sources fail to click due to special characters in names
2. **Content extraction is heuristic**: Uses "largest div with 来源指南" — may miss content if the DOM structure changes
3. **Requires Chrome focus**: Chrome must be the frontmost window; don't use the computer during export
4. **No incremental updates**: Re-exports everything; no change detection
5. **Mac-only**: JXA is macOS-specific
6. **Source types**: Handles articles, PDFs, YouTube videos, text snippets, and web links

## Files

- `notebooklm_auto_v3.py` — The automation script (self-contained, single file)
- This `SKILL.md` — Documentation
