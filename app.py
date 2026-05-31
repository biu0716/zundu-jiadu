"""P3 Web 服务：核查引擎结果 → 长辈友好卡片 + 「说给谁听」对象切换。
复用 verifier.py，不改核查逻辑。事实（判定/真相/来源）锁死，对象切换只改"给家人的那段话"。

运行：
    pip install flask
    export LLM_API_KEY=你的key
    python app.py        →  http://127.0.0.1:5000
"""
import json
import re
from flask import Flask, request, jsonify
from verifier import FactVerifier

# ============ 改这一行就能换产品名（输入页标题 + 卡片落款，都不含"辟谣"二字）============
PRODUCT_NAME = "尊嘟假嘟"   # ← 产品名
# ====================================================================================

app = Flask(__name__)
verifier = FactVerifier()

VERDICT_STYLE = {
    "谣言":     {"icon": "❌", "color": "#e84a3c", "label": "不可信"},
    "误导性":   {"icon": "⚠️", "color": "#e8920c", "label": "有误导"},
    "部分属实": {"icon": "◐", "color": "#e8920c", "label": "半真半假"},
    "属实":     {"icon": "✅", "color": "#07a852", "label": "是真的"},
    "缺乏证据": {"icon": "❓", "color": "#888888", "label": "暂存疑"},
}

# 「说给谁听」：同一真相，不同对象，不同沟通策略（只改语气，不改事实）
AUDIENCES = {
    "通用":   {"label": "通用",         "emoji": "👪", "strategy": "最简短直接，一两句把真相说清就行，不绕弯、不铺垫，像随手发个消息"},
    "爱面子": {"label": "给爱面子的长辈", "emoji": "🎩", "strategy": "绝不能让他觉得自己被纠正或转错了。要顺着他、捧着他，比如'您见识广，肯定也听过…'，把真相说成是和他一起印证的，给足台阶和面子"},
    "易焦虑": {"label": "给容易焦虑的家人", "emoji": "🫶", "strategy": "开头先用一句话安抚情绪（如'别担心啊''没事的'），整段不出现任何致癌、中毒、死亡等吓人字眼，反复强调放心、不用慌，语气特别软"},
    "固执":   {"label": "给固执的老人",   "emoji": "🧓", "strategy": "必须搬出他会信服的权威背书（医生、央视、国家卫健委、专家），用'XX都说了…''新闻里讲过…'这种句式压住，语气尊重但底气足，让他没法反驳"},
}

with open("seed_data.json", encoding="utf-8") as f:
    TACTIC_PLAIN = json.load(f).get("tactic_plain", {})
with open("card_template.html", encoding="utf-8") as f:
    CARD_TEMPLATE = f.read()
with open("index.html", encoding="utf-8") as f:
    INDEX_HTML = f.read()


@app.route("/")
def index():
    return INDEX_HTML.replace("{{PRODUCT_NAME}}", PRODUCT_NAME)


@app.route("/verify", methods=["POST"])
def do_verify():
    text = (request.json or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "请输入要核查的内容"}), 400
    result = verifier.verify(text)
    style = VERDICT_STYLE.get(result["verdict"], VERDICT_STYLE["缺乏证据"])
    message = compose_message(result, "通用")   # 首次默认"通用"版话术
    return jsonify({
        "result": result,
        "style": style,
        "steps": friendly_steps(result),
        "message": message,
        "audiences": [{"key": k, "label": v["label"], "emoji": v["emoji"]} for k, v in AUDIENCES.items()],
        "card_html": render_card(result, style, message),
    })


@app.route("/rephrase", methods=["POST"])
def rephrase():
    """对象切换：只重写"给家人的话"，事实不动。"""
    body = request.json or {}
    result = body.get("result") or {}
    audience = body.get("audience", "通用")
    return jsonify({"message": compose_message(result, audience), "audience": audience})


# ---------------- 「说给谁听」核心：把真相改写成发给某位家人的话 ----------------
def compose_message(result, audience_key):
    aud = AUDIENCES.get(audience_key, AUDIENCES["通用"])
    if not verifier.llm.available:
        return _fallback_message(result, audience_key)
    system = (
        "你在帮一位年轻人，把一条已核实的真相，改写成发到家庭群里、爸妈愿意看愿意信的一段话。"
        "你很懂怎么跟爸妈说话：像真实的子女在微信上跟爸妈唠嗑，亲切、口语、带点撒娇或调侃的暖意，"
        "可以适当用点轻松的口气和小幽默，但不油腻、不冒犯。绝不像官方通告或科普文章。"
    )
    user = f"""把下面的真相，按指定对象改写成一段能直接发家庭群的话。
要求：
- 像子女平时给爸妈发微信那样说话，口语、亲切、自然，可以带一点点幽默或撒娇感。
- **不要带任何称呼开头（不要"爸""妈""爷爷""家人们"这种），直接说事**，让谁看了都能用。
- 2-4 句，别太长；绝不出现"谣言/辟谣/经核查"这种生硬字眼。
- 若有安全提示，自然地融进去，别说教。
- **严格按照下面的「沟通策略」来写，让这一版和别的对象明显不一样**——策略是这一版的灵魂，必须照做。
- 只输出这段话本身，不要引号、不要解释。

【真相】{result.get('truth', '')}
【安全提示】{result.get('safety_note') or '无'}
【这一版写给】{aud['label']}
【必须遵守的沟通策略】{aud['strategy']}"""
    try:
        msg = verifier.llm.chat(system, user, temperature=0.6).strip()
        return msg.strip('"“”').strip()
    except Exception:
        return _fallback_message(result, audience_key)


def _fallback_message(result, audience_key):
    """无大模型时的兜底话术（保证离线 demo 也能演对象切换）。不带称呼，直接说事。"""
    truth = result.get("truth", "")
    note = result.get("safety_note")
    prefix = {
        "通用": "我帮你核实了一下：",
        "爱面子": "这个我也挺好奇，特意去查了查：",
        "易焦虑": "别担心啊，我查清楚了，没事的：",
        "固执": "我看了医生和权威平台的说法：",
    }.get(audience_key, "我帮你核实了一下：")
    msg = prefix + truth
    if note:
        msg += " " + note
    return msg


def friendly_steps(r):
    sp = r.get("source_path", "")
    if r.get("kb_hit"):
        step2 = "在权威资料库里找到了对应结论"
    elif "联网" in sp:
        step2 = "权威库里没有，已实时联网核查权威网页"
    elif "模型" in sp:
        step2 = "权威库里没有，已用 AI 结合权威常识核查"
    else:
        step2 = "暂时没找到可靠依据"
    tail = "并附上可查的权威来源" if r.get("sources") else "（基于权威常识）"
    return [
        {"name": "看清在说什么", "text": "把这条消息的核心说法拎出来"},
        {"name": "比对权威资料", "text": step2},
        {"name": "判断真假", "text": "看它哪里对、哪里在误导你"},
        {"name": "给出结论", "text": f"判定为「{r['verdict']}」{tail}"},
    ]


def _linkify(text):
    return re.sub(r"(https?://[^\s]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', text)


def render_card(r, style, message):
    # 四格看穿（漫画式）：谣言登场 → 它这样唬你 → 真相打脸 → 记住这点
    comic = r.get("comic") or {}
    if comic.get("truth") or comic.get("panic"):
        equation_html = ""
        if comic.get("equation"):
            equation_html = f'<div class="comic-eq">{comic["equation"]}</div>'
        emo = comic.get("emoji") or {}
        panels = [
            (emo.get("panic", "😱"), "谣言登场", comic.get("panic", r.get("input", "")), "p-panic"),
            (emo.get("trick", "🎭"), "它这样唬你", comic.get("trick", ""), "p-trick"),
            (emo.get("truth", "💡"), "真相打脸", comic.get("truth", r.get("truth", "")), "p-truth"),
            (emo.get("tip", "😌"), "记住这点", comic.get("tip", ""), "p-tip"),
        ]
        cells = "".join(
            f'<div class="panel {cls}"><div class="p-emoji">{emo}</div>'
            f'<div class="p-label">{i+1} · {lab}</div>'
            f'<div class="p-text">{txt}</div></div>'
            for i, (emo, lab, txt, cls) in enumerate(panels) if txt
        )
        comic_html = f'{equation_html}<div class="comic">{cells}</div>'
    else:
        # 兜底：没有 comic 时退回旧的话术文字版
        items = []
        for i, term in enumerate(r.get("tactics", [])):
            plain = TACTIC_PLAIN.get(term, term)
            items.append(
                f'<div class="trick-item"><b>{i+1}</b>'
                f'<div class="t-box"><div class="t-plain">{plain}</div>'
                f'<div class="t-term">{term}</div></div></div>'
            )
        comic_html = f'<div class="trick">{"".join(items) or "—"}</div>'

    safety_html = ""
    if r.get("high_risk") and r.get("safety_note"):
        safety_html = f'<div class="safety"><span>⚠️</span><span>{r["safety_note"]}</span></div>'

    analogy_html = ""
    if r.get("analogy"):
        analogy_html = (
            f'<div class="analogy">🔢 {r["analogy"]["text"]}'
            f'<div class="analogy-src">（出处：{_linkify(r["analogy"]["source"])}）</div></div>'
        )

    sources_html = ""
    if r.get("sources"):
        lis = ""
        for s in r["sources"]:
            m = re.match(r"^(.*?)[\s:：]+(https?://\S+)\s*$", s)
            if m:
                name, url = m.group(1).strip(), m.group(2).strip()
                lis += (f'<li><span class="src-name">{name}</span>'
                        f'<a class="src-url" href="{url}" target="_blank" rel="noopener"> {url}</a></li>')
            else:
                lis += f"<li>{s}</li>"
        sources_html = ('<div class="source card-sec" data-sec="src">'
                        '<div class="s-title">🏛️ 权威来源<span class="screen-only">（可点开查看）</span></div>'
                        f'<ul>{lis}</ul></div>')

    return (CARD_TEMPLATE
            .replace("{{COLOR}}", style["color"])
            .replace("{{VERDICT_ICON}}", style["icon"])
            .replace("{{VERDICT_LABEL}}", style["label"])
            .replace("{{TITLE}}", _make_title(r))
            .replace("{{TRUTH}}", r.get("truth", ""))
            .replace("{{COMIC}}", comic_html)
            .replace("{{SAFETY}}", safety_html)
            .replace("{{ANALOGY}}", analogy_html)
            .replace("{{SOURCES}}", sources_html)
            .replace("{{MESSAGE}}", message)
            .replace("{{PRODUCT_NAME}}", PRODUCT_NAME))


def _make_title(r):
    v = r["verdict"]
    if v == "属实":
        return "这条是真的，可以照着做"
    if v == "缺乏证据":
        return "这条暂时存疑，先别急着信"
    return "家人别担心，这条不用慌——真相在这"


if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("RENDER") is None   # 线上关闭 debug
    print(f"打开浏览器访问 http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
