#!/usr/bin/env python3
"""Render build/review.html: a grid of every candidate thumbnail for manual curation.

Click a tile to toggle "reject"; the textarea at the bottom holds the ids to paste into curation/rejects.txt.
Rejected ids already in curation/rejects.txt start out marked. Open the file in a browser (thumbs are hotlinked).

Usage: python3 tools/contact_sheet.py [build/candidates.json]
"""
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "candidates.json")
    items = json.load(open(src))
    rej_path = os.path.join(ROOT, "curation", "rejects.txt")
    rejects = set()
    if os.path.exists(rej_path):
        rejects = {ln.split("#")[0].strip() for ln in open(rej_path) if ln.split("#")[0].strip()}
    tiles = []
    for it in items:
        cls = "t rej" if it["id"] in rejects else "t"
        tip = html.escape(f'{it["title"]} — {it["artist"]} ({it["date"]}) [{it["theme"]}]')
        tiles.append(
            f'<div class="{cls}" data-id="{it["id"]}" title="{tip}">'
            f'<img loading="lazy" src="{html.escape(it["thumb"])}">'
            f'<span>{it["theme"]} · {html.escape(it["id"])}</span></div>'
        )
    page = f"""<!doctype html><meta charset="utf-8"><title>Frame Art library review</title>
<style>
body{{font:13px system-ui;margin:12px;background:#111;color:#ddd}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px}}
.t{{position:relative;cursor:pointer;background:#222;border-radius:6px;overflow:hidden}}
.t img{{width:100%;height:150px;object-fit:cover;display:block}}
.t span{{display:block;padding:3px 5px;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.rej{{outline:4px solid #e33}} .rej img{{opacity:.25}}
textarea{{width:100%;height:120px;margin-top:12px;background:#000;color:#8f8}}
</style>
<p>{len(items)} candidates. Click to toggle reject. Paste the list below into <code>curation/rejects.txt</code>.</p>
<div class="g">{"".join(tiles)}</div>
<textarea id="out" readonly></textarea>
<script>
const out=document.getElementById('out');
const sync=()=>out.value=[...document.querySelectorAll('.rej')].map(e=>e.dataset.id).join('\\n');
document.querySelectorAll('.t').forEach(t=>t.onclick=()=>{{t.classList.toggle('rej');sync();}});
sync();
</script>"""
    out = os.path.join(ROOT, "build", "review.html")
    with open(out, "w") as f:
        f.write(page)
    print(out)


if __name__ == "__main__":
    main()
