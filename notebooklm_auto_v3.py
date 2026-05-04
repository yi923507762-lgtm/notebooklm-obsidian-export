#!/usr/bin/env python3
"""
NotebookLM → Obsidian V3 Automation
Fixed: clicks "来源" tab to expand source panel before extracting.
"""

import subprocess, base64, json, re, os, sys, time
from datetime import datetime

VAULT_DIR = "/Users/mac/Documents/Obsidian Vault/raw/notebooklm"
SLEEP_AFTER_CLICK = 2.5
SLEEP_AFTER_NAV = 4

def jxa_exec(js_code):
    b64 = base64.b64encode(js_code.encode()).decode()
    jxa = f'''
ObjC.import('Foundation');
var app = Application("Google Chrome");
var tab = app.windows[0].tabs[0];
var b64 = "{b64}";
var data = $.NSData.alloc.initWithBase64EncodedStringOptions(b64, 0);
var js = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding).js;
var result = tab.execute({{javascript: js}});
result;
'''
    with open('/tmp/jxa_v3.js', 'w') as f:
        f.write(jxa)
    r = subprocess.run(['osascript', '-l', 'JavaScript', '/tmp/jxa_v3.js'],
                      capture_output=True, text=True, timeout=30)
    return r.stdout.strip()

def navigate_to(uuid):
    jxa_exec(f"window.location.href = '/notebook/{uuid}'; 'ok';")
    time.sleep(SLEEP_AFTER_NAV)

def ensure_source_panel_open():
    """Click the '来源' tab/button to ensure source panel is visible"""
    js = """
(function() {
    // Try to find and click the "来源" or "Sources" tab
    var allEls = document.querySelectorAll('button, [role="tab"], [role="radio"], a, div[tabindex]');
    for (var i = 0; i < allEls.length; i++) {
        var text = allEls[i].textContent.trim();
        if (text === '来源' || text === 'Sources' || text === 'sources') {
            allEls[i].click();
            return JSON.stringify({clicked: '来源'});
        }
    }
    return JSON.stringify({clicked: false, found: allEls.length + ' elements checked'});
})()
"""
    result = json.loads(jxa_exec(js))
    if result.get('clicked'):
        time.sleep(1.5)
    return result.get('clicked') == '来源'

def get_notebook_info():
    """Get notebook title and all source names"""
    js = """
(function() {
    var sources = [];
    var containers = document.querySelectorAll('.single-source-container');
    containers.forEach(function(c) {
        var btn = c.querySelector('.source-stretched-button');
        if (!btn) return;
        var name = btn.getAttribute('aria-label');
        if (name && name.trim() && name !== '更多') {
            sources.push(name.trim());
        }
    });
    return JSON.stringify({
        title: document.title.replace(' - NotebookLM', '').trim(),
        uuid: (window.location.href.match(/notebook\\/([a-f0-9-]+)/) || [])[1] || '',
        total: sources.length,
        sources: sources
    });
})()
"""
    return json.loads(jxa_exec(js))

def click_source_by_name(name):
    escaped = name.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"')
    js = f"""
(function() {{
    var containers = document.querySelectorAll('.single-source-container');
    for (var i = 0; i < containers.length; i++) {{
        var btn = containers[i].querySelector('.source-stretched-button');
        if (btn && btn.getAttribute('aria-label') === "{escaped}") {{
            btn.click();
            return JSON.stringify({{clicked: true, name: "{escaped}"}});
        }}
    }}
    return JSON.stringify({{clicked: false, name: "{escaped}"}});
}})()
"""
    result = json.loads(jxa_exec(js))
    if result.get('clicked'):
        time.sleep(SLEEP_AFTER_CLICK)
        return True
    return False

def extract_content():
    js = """
(function() {
    var result = {};
    result.title = document.title.replace(' - NotebookLM', '').trim();
    result.url = window.location.href;

    var fullText = document.body.innerText;
    var lines = fullText.split('\\n');
    for (var i = 0; i < lines.length; i++) {
        if (lines[i].trim() === 'collapse_content' && i + 1 < lines.length) {
            result.sourceName = lines[i + 1].trim();
            break;
        }
    }

    var allDivs = document.querySelectorAll('div');
    var bestText = '';
    allDivs.forEach(function(div) {
        var text = div.innerText || '';
        if (text.length > bestText.length && text.length < 50000 && text.indexOf('来源指南') > -1) {
            bestText = text;
        }
    });

    result.rawContent = bestText || fullText;
    result.sourceType = 'unknown';
    // Detect source type from content
    for (var key of ['article', 'drive_pdf', 'video_youtube', 'text_snippet', 'web_link']) {
        if (fullText.substring(0, 300).indexOf(key) > -1) {
            result.sourceType = key;
            break;
        }
    }

    return JSON.stringify(result);
})()
"""
    return json.loads(jxa_exec(js))

def clean_content(raw_text):
    lines = raw_text.split('\n')
    clean_lines = []
    found_content = False
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
    ]
    for line in lines:
        stripped = line.strip()
        if not found_content:
            is_ui = any(stripped.startswith(p) and len(stripped) < 60 for p in skip_starts)
            if not is_ui and len(stripped) > 20:
                found_content = True
                clean_lines.append(line)
        else:
            if stripped:
                clean_lines.append(line)
    cleaned = '\n'.join(clean_lines)
    cleaned = re.sub(r'NotebookLM 提供的内容未必准确[^。]*。', '', cleaned)
    return cleaned.strip()

def save_markdown(notebook_title, source_name, source_type, content, url):
    today = datetime.now().strftime('%Y-%m-%d')
    type_map = {
        'article': '📄 文档', 'drive_pdf': '📕 PDF',
        'video_youtube': '🎬 YouTube', 'text_snippet': '📝 文本',
        'web_link': '🌐 网页'
    }
    type_label = type_map.get(source_type, '📎 来源')
    md = f"""---
type: notebooklm-clip
notebook: "{notebook_title}"
source: "{source_name}"
source_type: "{source_type}"
date_clipped: {today}
url: {url}
tags: [notebooklm, {source_type}]
---

# {source_name}

> {type_label} · 来自 NotebookLM 笔记本「{notebook_title}」
>
> 来源指南 · AI 生成的内容分析

---

{content}

---

*由 NotebookLM 来源指南自动导入 · {today}*
"""
    nb_dir = os.path.join(VAULT_DIR, notebook_title.replace('/', '-'))
    os.makedirs(nb_dir, exist_ok=True)
    safe_name = source_name.replace('/', '-').replace(':', '：')[:80]
    filepath = os.path.join(nb_dir, f"{safe_name}.md")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    return filepath

def process_notebook(uuid):
    navigate_to(uuid)

    # Click "来源" tab to reveal source panel
    ensure_source_panel_open()

    info = get_notebook_info()
    print(f"\n{'='*50}")
    print(f"📓 {info['title']}")
    print(f"   {info['total']} sources")

    if info['total'] == 0:
        print("   ⚠️ No sources found even after clicking 来源")
        return 0

    processed = 0
    skipped = 0
    for i, source_name in enumerate(info['sources']):
        # Dedup: skip if output file already exists
        safe_name = source_name.replace('/', '-').replace(':', '：')[:80]
        nb_dir = os.path.join(VAULT_DIR, info['title'].replace('/', '-'))
        output_path = os.path.join(nb_dir, f"{safe_name}.md")
        if os.path.exists(output_path):
            print(f"  [{i+1}/{info['total']}] {source_name[:60]}... ⏭️ already exists")
            skipped += 1
            continue

        print(f"  [{i+1}/{info['total']}] {source_name[:60]}...", end=' ')

        # Ensure source panel is visible (re-click if needed)
        if not click_source_by_name(source_name):
            ensure_source_panel_open()
            time.sleep(1)
            if not click_source_by_name(source_name):
                print("❌ click failed")
                navigate_to(uuid)
                ensure_source_panel_open()
                continue

        content_data = extract_content()
        if not content_data.get('rawContent'):
            print("❌ no content")
            navigate_to(uuid)
            ensure_source_panel_open()
            continue

        cleaned = clean_content(content_data['rawContent'])
        filepath = save_markdown(
            info['title'],
            content_data.get('sourceName') or source_name,
            content_data.get('sourceType', 'unknown'),
            cleaned,
            content_data.get('url', '')
        )
        print(f"✅ {len(cleaned)} chars")
        processed += 1
        navigate_to(uuid)
        ensure_source_panel_open()

    summary = f"  Done: {processed} processed"
    if skipped:
        summary += f", {skipped} skipped (already exist)"
    summary += f" / {info['total']} total"
    print(summary)
    return processed

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 notebooklm_auto_v3.py <uuid> [uuid2 ...]")
        sys.exit(1)
    total = 0
    for uuid in sys.argv[1:]:
        total += process_notebook(uuid)
    print(f"\n🎉 Total processed: {total} sources")
