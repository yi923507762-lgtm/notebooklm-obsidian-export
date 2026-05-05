#!/usr/bin/env python3
"""
NotebookLM → Obsidian · Playwright版
连接你已打开的 Chrome（9222端口），操控它导出所有来源指南。

用法:
  python3 export_notebooklm_pw.py                    # 列出所有笔记本，让你选
  python3 export_notebooklm_pw.py <uuid1> <uuid2>    # 导出指定笔记本
  python3 export_notebooklm_pw.py --dry-run <uuid>    # 试跑：只扫描不保存

前提：Chrome 已通过 remote-debugging-port=9222 启动，且已登录 NotebookLM。
"""

import asyncio, re, os, sys, time, json
from datetime import datetime
from pathlib import Path

VAULT_DIR = "/Users/mac/Documents/Obsidian Vault/raw/notebooklm"
CDP_URL = "http://127.0.0.1:9222"
SLEEP_AFTER_CLICK = 2.5
SLEEP_AFTER_NAV = 4


# ─── browser connection ──────────────────────────────────────────────
async def connect_browser():
    """Connect to existing Chrome via CDP. Fails cleanly if Chrome isn't open."""
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        print(f"✅ 已连接 Chrome（{len(browser.contexts)} 个上下文，{len(browser.contexts[0].pages) if browser.contexts else 0} 个页面）")
        return pw, browser
    except Exception as e:
        await pw.stop()
        print(f"❌ 无法连接 Chrome。请确保 Chrome 已通过以下方式启动：")
        print(f"   chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-devtools-profile")
        print(f"   错误：{e}")
        sys.exit(1)


async def get_page(browser):
    """Return a NotebookLM page, the first page, or create a new one."""
    contexts = browser.contexts
    if contexts:
        # Prefer a page already on notebooklm
        for page in contexts[0].pages:
            try:
                if 'notebooklm' in page.url:
                    return page
            except Exception:
                pass
        # Fall back to first available page
        if contexts[0].pages:
            return contexts[0].pages[0]
        return await contexts[0].new_page()
    raise RuntimeError("No browser context found")


# ─── vault import status ─────────────────────────────────────────────
def check_import_status(notebook_title, source_count):
    """Return (already_imported_count, status_label) for a notebook."""
    safe_nb = notebook_title.replace('/', '-')
    nb_dir = os.path.join(VAULT_DIR, safe_nb)
    if not os.path.isdir(nb_dir):
        return 0, 'new'
    existing = [f for f in os.listdir(nb_dir) if f.endswith('.md')]
    imported = len(existing)
    if imported == 0:
        return 0, 'empty'
    if imported >= source_count:
        return imported, 'complete'
    ratio = imported / max(source_count, 1)
    if ratio > 0.8:
        return imported, f'near ({imported}/{source_count})'
    return imported, f'partial ({imported}/{source_count})'


def _clean_listing_title(raw_text):
    """Extract a clean notebook name from the scraped card text.
    Input like: '\\U0001f577️more_vert CLI 爬取测试 2026年5月5日·1 个来源'
    Output like: 'CLI 爬取测试'

    Uses a multi-pass loop to handle interleaved emoji and keywords:
    'group🫧more_vert 马来西亚SIMC植物泡泡染' → '马来西亚SIMC植物泡泡染'
    """
    import re as _re
    t = raw_text
    # Known prefix words to strip (material icon names + NotebookLM markers)
    prefix_words = r'more_vert|person|public|group|arrow_\w+|dock_\w+|photo_\w+|audio_\w+|sticky_\w+|auto_\w+|stacked_\w+|chevron_\w+'
    # Multi-pass: keep stripping emoji + prefix words until stable
    for _ in range(5):
        prev = t
        t = _re.sub(r'^[^a-zA-Z一-鿿぀-ゟ゠-ヿ가-힯\d]+', '', t)
        t = _re.sub(rf'^({prefix_words})\s*', '', t, flags=_re.IGNORECASE)
        if t == prev:
            break
    # Remove trailing date + source count
    t = _re.sub(r'\s+\d{4}年\d{1,2}月\d{1,2}日.*$', '', t)
    t = _re.sub(r'\s+\d{4}-\d{2}-\d{2}.*$', '', t)
    # Remove trailing "·N 个来源"
    t = _re.sub(r'\s*·\s*\d+\s*个来源\s*$', '', t)
    t = t.strip()
    return t


def _extract_source_count(raw_text):
    """Extract the source count from card text like '...22 个来源' or '...·1 个来源'."""
    import re as _re
    m = _re.search(r'(\d+)\s*个来源', raw_text)
    return int(m.group(1)) if m else 0


# ─── notebook discovery ──────────────────────────────────────────────
async def list_notebooks(page):
    """Scrape the NotebookLM home page for all visible notebook UUIDs + titles.
    Also checks vault import status for each notebook."""
    await page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(2)

    notebooks = await page.evaluate("""
    (() => {
        const results = [];
        const links = document.querySelectorAll('a[href*="/notebook/"]');
        const seen = new Set();
        links.forEach(a => {
            const href = a.getAttribute('href');
            const match = href.match(/notebook\\/([a-f0-9-]+)/);
            if (match && !seen.has(match[1])) {
                seen.add(match[1]);
                // NotebookLM Angular: title text is in parent <mat-card>, not in <a>
                let title = '';
                const card = a.closest('mat-card') || a.parentElement;
                if (card) {
                    title = card.textContent.trim().substring(0, 150);
                }
                if (!title) title = href;
                results.push({uuid: match[1], title: title});
            }
        });
        return results;
    })()
    """)

    if not notebooks:
        print("⚠️  在首页未找到笔记本链接。请确认 Chrome 已登录 NotebookLM。")
        return notebooks

    # Enrich with import status
    for nb in notebooks:
        nb['clean_title'] = _clean_listing_title(nb['title'])
        nb['source_count'] = _extract_source_count(nb['title'])
        imported, status = check_import_status(nb['clean_title'], nb['source_count'])
        nb['imported'] = imported
        nb['status'] = status

    return notebooks


# ─── notebook operations ─────────────────────────────────────────────
async def navigate_to(page, uuid):
    await page.goto(f"https://notebooklm.google.com/notebook/{uuid}", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(SLEEP_AFTER_NAV)


async def ensure_source_panel_open(page):
    """Click the '来源' / 'Sources' tab to reveal the source panel."""
    clicked = await page.evaluate("""
    (() => {
        const all = document.querySelectorAll('button, [role="tab"], [role="radio"], a, div[tabindex]');
        for (const el of all) {
            const t = el.textContent.trim();
            if (t === '\\u6765\\u6e90' || t === 'Sources' || t === 'sources') {
                el.click();
                return true;
            }
        }
        return false;
    })()
    """)
    if clicked:
        await asyncio.sleep(1.5)
    return clicked


async def get_notebook_info(page):
    """Return {title, uuid, total, sources: [name, ...]}"""
    return await page.evaluate("""
    (() => {
        const sources = [];
        document.querySelectorAll('.single-source-container').forEach(c => {
            const btn = c.querySelector('.source-stretched-button');
            if (!btn) return;
            // Try aria-label first, then text content, then parent text
            let name = (btn.getAttribute('aria-label') || '').trim();
            if (!name || name === '\\u66f4\\u591a') {
                // Fallback: use the container's text, filtering out UI labels
                const text = c.textContent.trim().split('\\n')[0] || '';
                name = text.substring(0, 120).trim();
            }
            if (name && name !== '\\u66f4\\u591a') {
                sources.push(name);
            }
        });
        return {
            title: document.title.replace(' - NotebookLM', '').trim(),
            uuid: (window.location.href.match(/notebook\\/([a-f0-9-]+)/) || [])[1] || '',
            total: sources.length,
            sources: sources
        };
    })()
    """)


async def click_source_by_name(page, name):
    """Click a source by its aria-label. Returns True if clicked."""
    escaped = name.replace('\\', '\\\\').replace("'", "\\'")
    result = await page.evaluate(f"""
    (() => {{
        const containers = document.querySelectorAll('.single-source-container');
        for (const c of containers) {{
            const btn = c.querySelector('.source-stretched-button');
            if (btn && btn.getAttribute('aria-label') === '{escaped}') {{
                btn.click();
                return {{clicked: true}};
            }}
        }}
        return {{clicked: false}};
    }})()
    """)
    if result.get('clicked'):
        await asyncio.sleep(SLEEP_AFTER_CLICK)
        return True
    return False


async def extract_content(page):
    """Extract the source guide content and metadata from the current page."""
    return await page.evaluate("""
    (() => {
        const result = {};
        result.url = window.location.href;
        const fullText = document.body.innerText;

        // ── source name ────────────────────────────────────────────
        // Try aria-label on source-stretched-button first
        const btn = document.querySelector('.source-stretched-button');
        let sourceName = '';
        if (btn) {
            sourceName = (btn.getAttribute('aria-label') || '').trim();
        }
        // Fallback: scan for the source name after 'collapse_content'
        if (!sourceName) {
            const lines = fullText.split('\\n');
            for (let i = 0; i < lines.length; i++) {
                if (lines[i].trim() === 'collapse_content' && i + 1 < lines.length) {
                    sourceName = lines[i + 1].trim();
                    break;
                }
            }
        }
        // Fallback: try the first h1 or large heading near the top
        if (!sourceName) {
            const h1 = document.querySelector('h1');
            if (h1) sourceName = h1.textContent.trim();
        }
        result.sourceName = sourceName || 'unknown';

        // ── source type ─────────────────────────────────────────────
        result.sourceType = 'unknown';
        const head = fullText.substring(0, 500);
        const typePatterns = [
            ['drive_pdf', /\\b(PDF|pdf|Adobe|drive_pdf)\\b/],
            ['video_youtube', /\\b(YouTube|youtube|视频|video_youtube)\\b/],
            ['web_link', /\\b(web_link|网页|website|URL)\\b/],
            ['text_snippet', /\\b(text_snippet|粘贴的文字|pasted text|Pasted text)\\b/],
            ['article', /\\b(article|文档|docx|article|文章)\\b/],
        ];
        for (const [key, pattern] of typePatterns) {
            if (pattern.test(head)) { result.sourceType = key; break; }
        }
        // Fallback: check source name for type hints
        if (result.sourceType === 'unknown' && result.sourceName) {
            if (/粘贴|pasted/i.test(result.sourceName)) result.sourceType = 'text_snippet';
            else if (/\\.pdf$/i.test(result.sourceName)) result.sourceType = 'drive_pdf';
            else if (/youtube|视频/i.test(result.sourceName)) result.sourceType = 'video_youtube';
            else if (/\\.docx?$/i.test(result.sourceName)) result.sourceType = 'article';
        }

        // ── author ──────────────────────────────────────────────────
        result.author = '';
        const authorMatch = fullText.match(/(?:作者|Author|by|By)\\s*[:：]?\\s*([^\\n]{2,40}?)(?:\\n|$|·|\\||,)/);
        if (authorMatch) result.author = authorMatch[1].trim();

        // ── published date ──────────────────────────────────────────
        result.publishDate = '';
        const dateMatch = fullText.match(/(\\d{4}[-/年]\\d{1,2}[-/月]\\d{1,2}(?:日)?)/);
        if (dateMatch) result.publishDate = dateMatch[0];

        // ── description (first substantial paragraph of AI analysis) ──
        result.description = '';
        const lines = fullText.split('\\n');
        let inContent = false;
        const skipWords = [
            'add', 'PRO', '来源', 'collapse', 'button_magic', 'arrow_drop',
            'trending', 'share', 'settings', 'dock_to', 'search', 'language',
            'more_vert', 'person_text', 'copy_all', 'thumb_up', 'thumb_down',
            'chat_bubble', 'tune', 'photo_spark', '自定义', 'landscape_2',
            'keep', '保存到笔记', 'sticky_note_2', 'chevron_forward', 'close',
            'Studio', 'audio_magic_eraser', 'dock_to_left', 'tablet',
            'subscriptions', 'arrow_forward', 'edit_fix_auto', 'flowchart',
            'auto_tab_group', 'cards_star', 'quiz', 'stacked_bar_chart',
            'table_view', '试试看', '欢迎试用', '添加来源后', 'NotebookLM',
        ];
        for (const line of lines) {
            const s = line.trim();
            if (!s) continue;
            const isUI = skipWords.some(w => s.startsWith(w) && s.length < 60);
            if (isUI) continue;
            if (!inContent && s.length > 30) {
                inContent = true;
                result.description = s.substring(0, 200);
                break;
            }
        }

        // ── raw content (largest div with 来源指南) ──────────────────
        let bestText = '';
        document.querySelectorAll('div').forEach(div => {
            const text = div.innerText || '';
            if (text.length > bestText.length && text.length < 50000 && text.includes('\\u6765\\u6e90\\u6307\\u5357')) {
                bestText = text;
            }
        });
        result.rawContent = bestText || fullText;

        return result;
    })()
    """)


# ─── content cleaning ────────────────────────────────────────────────
def clean_content(raw_text):
    """Aggressively strip NotebookLM UI chrome from extracted content."""
    lines = raw_text.split('\n')
    clean_lines = []
    found_content = False

    # Comprehensive skip list: everything that's UI, not content
    skip_starts = [
        'group', 'add ', 'PRO', '来源', 'collapse', 'button_magic',
        'arrow_drop', 'trending', 'share', 'settings', 'dock_to',
        'search', 'language', 'Web', 'keyboard', 'search_spark',
        'Fast Research', '已分享', '创建笔记本', '选择所有来源',
        '分析', '分享', '设置', '来源指南', 'PRO', 'more_vert',
        'person_text', 'copy_all', 'thumb_up', 'thumb_down',
        'chat_bubble', 'docs', 'arrow_forward', 'studio',
        'photo_spark', '自定义', 'tune', 'dock_to_right',
        'NotebookLM 提供', 'link', 'notebooklm', 'landscape_2',
        'keep', '保存到笔记', 'sticky_note_2', '添加笔记',
        'audio_magic_eraser', '音频概览', 'chevron_forward',
        '演示文稿', '视频概览', '思维导图', '报告', '闪卡',
        '测验', '信息图', '数据表格', 'table_view', 'quiz',
        'cards_star', 'stacked_bar_chart', 'edit_fix_auto',
        'flowchart', 'auto_tab_group', 'subscriptions',
        'tablet', 'dock_to_left', 'close', '试试看',
        '添加来源后', 'Studio 输出将保存', '请为初学者',
        '在进行命令行', '如何评估和优化', 'Studio', 'Studio ',
    ]
    # Lines that should be skipped even in the middle of content
    skip_exact = {
        '对话', '🕷️', '🎉', '📷', '💪', '✨', '🎬', '⚙️',
        '🌿', '🏘️', '🤖', '🐻', '💇', 'person', 'person_text',
    }
    # Regex patterns to strip from individual lines
    skip_patterns = [
        re.compile(r'^\d+ 个来源$'),
        re.compile(r'^\d+年\d+月\d+日$'),
        re.compile(r'^·$'),
        re.compile(r'^欢迎试用.*$'),
        re.compile(r'^试试看$'),
    ]

    for line in lines:
        stripped = line.strip()

        # Always skip empty lines
        if not stripped:
            continue

        # Always skip lines matching skip_starts
        if any(stripped.startswith(p) and len(stripped) < 60 for p in skip_starts):
            continue

        # Always skip exact-match UI strings
        if stripped in skip_exact:
            continue

        # Always skip regex matches
        if any(p.match(stripped) for p in skip_patterns):
            continue

        # Transition: first substantial non-UI line triggers found_content
        if not found_content:
            if len(stripped) > 20:
                found_content = True
                clean_lines.append(line)
        else:
            # Post-transition: still filter short ASCII-only UI labels
            if len(stripped) < 5 and all(c < '一' for c in stripped):
                continue
            clean_lines.append(line)

    cleaned = '\n'.join(clean_lines)
    # Remove common NotebookLM disclaimers
    cleaned = re.sub(r'NotebookLM 提供的内容未必准确[^。]*。', '', cleaned)
    # Remove remaining emoji-only lines
    cleaned = re.sub(r'^\s*[^\w\s一-鿿]{1,3}\s*$', '', cleaned, flags=re.MULTILINE)
    # Collapse multiple blank lines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def save_markdown(notebook_title, source_name, source_type, content, url, author='', publish_date='', description='', dry_run=False):
    today = datetime.now().strftime('%Y-%m-%d')
    type_map = {
        'article': '📄 文档', 'drive_pdf': '📕 PDF',
        'video_youtube': '🎬 YouTube', 'text_snippet': '📝 文本',
        'web_link': '🌐 网页'
    }
    type_label = type_map.get(source_type, '📎 来源')

    # Build tags
    tags = ['notebooklm']
    if source_type != 'unknown':
        tags.append(source_type)

    # Build YAML frontmatter with Clipper-style properties
    yaml_lines = [
        '---',
        'type: notebooklm-clip',
        f'notebook: "{notebook_title}"',
        f'source: "{source_name}"',
        f'source_type: "{source_type}"',
        f'date_clipped: {today}',
        f'url: {url}',
    ]
    if author:
        yaml_lines.append(f'author: "{author}"')
    if publish_date:
        yaml_lines.append(f'published: "{publish_date}"')
    if description:
        # Escape quotes in description
        desc_escaped = description.replace('"', '\\"')
        yaml_lines.append(f'description: "{desc_escaped}"')
    yaml_lines.append(f'tags: [{", ".join(tags)}]')
    yaml_lines.append('---')
    yaml_block = '\n'.join(yaml_lines)

    md = f"""{yaml_block}

# {source_name}

> {type_label} · 来自 NotebookLM 笔记本「{notebook_title}」
>
> 来源指南 · AI 生成的内容分析

---

{content}

---

*由 NotebookLM 来源指南自动导入 · {today}*
"""
    if dry_run:
        return f"[DRY-RUN] Would save: {source_name}.md ({len(content)} chars)"

    nb_dir = os.path.join(VAULT_DIR, notebook_title.replace('/', '-'))
    os.makedirs(nb_dir, exist_ok=True)
    safe_name = source_name.replace('/', '-').replace(':', '：')[:80]
    filepath = os.path.join(nb_dir, f"{safe_name}.md")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    return filepath


# ─── main export loop ────────────────────────────────────────────────
async def process_notebook(page, uuid, dry_run=False):
    await navigate_to(page, uuid)
    await ensure_source_panel_open(page)

    info = await get_notebook_info(page)
    print(f"\n{'='*50}")
    print(f"📓 {info['title']}")
    print(f"   {info['total']} sources")

    if info['total'] == 0:
        print("   ⚠️  未找到来源。可能来源面板未展开或笔记本为空。")
        return 0

    processed = 0
    skipped = 0
    for i, source_name in enumerate(info['sources']):
        safe_name = source_name.replace('/', '-').replace(':', '：')[:80]
        nb_dir = os.path.join(VAULT_DIR, info['title'].replace('/', '-'))
        output_path = os.path.join(nb_dir, f"{safe_name}.md")

        if not dry_run and os.path.exists(output_path):
            print(f"  [{i+1}/{info['total']}] {source_name[:60]}... ⏭️ 已存在")
            skipped += 1
            continue

        print(f"  [{i+1}/{info['total']}] {source_name[:60]}...", end=' ', flush=True)

        # Try clicking; if it fails, re-open panel and retry
        ok = await click_source_by_name(page, source_name)
        if not ok:
            await ensure_source_panel_open(page)
            await asyncio.sleep(1)
            ok = await click_source_by_name(page, source_name)

        if not ok:
            print("❌ 点击失败")
            await navigate_to(page, uuid)
            await ensure_source_panel_open(page)
            continue

        content_data = await extract_content(page)
        if not content_data.get('rawContent'):
            print("❌ 无内容")
            await navigate_to(page, uuid)
            await ensure_source_panel_open(page)
            continue

        cleaned = clean_content(content_data['rawContent'])

        source_name_final = content_data.get('sourceName') or source_name
        source_type_final = content_data.get('sourceType', 'unknown')
        author = content_data.get('author', '')
        publish_date = content_data.get('publishDate', '')
        description = content_data.get('description', '')
        url_final = content_data.get('url', '')

        if dry_run:
            result = save_markdown(
                info['title'], source_name_final, source_type_final,
                cleaned, url_final,
                author=author, publish_date=publish_date,
                description=description, dry_run=True,
            )
            print(f"🔍 {result}")
        else:
            filepath = save_markdown(
                info['title'], source_name_final, source_type_final,
                cleaned, url_final,
                author=author, publish_date=publish_date,
                description=description,
            )
            print(f"✅ {len(cleaned)} 字 → {Path(filepath).name}")

        processed += 1
        await navigate_to(page, uuid)
        await ensure_source_panel_open(page)

    summary = f"  Done: {processed} processed"
    if skipped:
        summary += f", {skipped} skipped (already exist)"
    summary += f" / {info['total']} total"
    print(summary)
    return processed


# ─── CLI ──────────────────────────────────────────────────────────────
async def main():
    dry_run = '--dry-run' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--dry-run']

    pw, browser = await connect_browser()
    try:
        page = await get_page(browser)

        if not args:
            # Interactive mode: list notebooks, let user choose
            print("🔍 扫描 NotebookLM 笔记本...")
            notebooks = await list_notebooks(page)
            if not notebooks:
                print("未找到笔记本。请打开 https://notebooklm.google.com/ 确认已登录。")
                return

            print(f"\n找到 {len(notebooks)} 个笔记本：\n")
            new_count = sum(1 for nb in notebooks if nb['status'] == 'new')
            partial_count = sum(1 for nb in notebooks if nb['status'] not in ('new', 'complete', 'empty'))
            complete_count = sum(1 for nb in notebooks if nb['status'] == 'complete')
            print(f"  🆕 未导入: {new_count}  |  📥 部分导入: {partial_count}  |  ✅ 已完成: {complete_count}\n")
            for i, nb in enumerate(notebooks):
                status_icon = {'new': '🆕', 'complete': '✅', 'empty': '📭'}.get(nb['status'], '📥')
                count_info = f" ({nb['source_count']} sources)" if nb['source_count'] else ''
                print(f"  [{i+1}] {status_icon} {nb['clean_title'][:70]}{count_info}")
                if nb['status'] not in ('new', 'complete'):
                    print(f"      已导入: {nb['imported']}/{nb['source_count']}")
                print(f"      UUID: {nb['uuid']}\n")

            print("用法：python3 export_notebooklm_pw.py <uuid> [uuid2 ...]")
            print("      python3 export_notebooklm_pw.py --dry-run <uuid>   # 试跑不保存")
            return

        # Batch mode: process each UUID
        total = 0
        for uuid in args:
            total += await process_notebook(page, uuid, dry_run=dry_run)

        tag = "🔍 [DRY-RUN] " if dry_run else ""
        print(f"\n🎉 {tag}Total: {total} sources")
    finally:
        await pw.stop()


if __name__ == '__main__':
    asyncio.run(main())
