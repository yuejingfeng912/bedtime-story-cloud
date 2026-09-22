# -*- coding: utf-8 -*-
"""PushPlus 推送到微信 + 故事 HTML 渲染。"""
import html
import json
import urllib.parse
import urllib.request

COLORS = {
    "child": "E8F5E9", "young_female": "FFF3E0", "young_male": "E3F2FD",
    "old_female": "F3E5F5", "old_male": "E0E0E0",
}
TYPE_OF = {
    "zh-CN-XiaoxiaoNeural": None,
}


def build_html(story_name, date_str, segments, roles):
    """把 segments 渲染成带角色底色的 HTML 正文。"""
    type_by_role = {k: (v or {}).get("type") for k, v in (roles or {}).items()}
    out = ['<div style="font-family:-apple-system,微软雅黑,sans-serif;font-size:16px;'
           'line-height:1.9;color:#333">']
    out.append(f'<h2 style="text-align:center;margin:4px 0 2px;">{html.escape(story_name)}</h2>')
    out.append(f'<p style="text-align:center;color:#888;font-size:12px;">'
               f'{int(date_str[4:6])}月{int(date_str[6:8])}日　·　适合 3-6 岁</p>')
    for seg in segments:
        t = html.escape(seg["text"])
        c = COLORS.get(type_by_role.get(seg["role"]))
        if c:
            out.append(f'<p style="margin:6px 0;background:#{c};padding:4px 8px;'
                       f'border-radius:5px;">{t}</p>')
        else:
            out.append(f'<p style="margin:6px 0;">{t}</p>')
    out.append("</div>")
    return "".join(out)


def push(token, title, content):
    url = "http://www.pushplus.plus/send"
    data = {"token": token, "title": title, "content": content, "type": "html"}
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("code") == 200, result
    except Exception as e:  # noqa: BLE001
        return False, str(e)
