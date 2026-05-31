"""核查引擎：调查记者四步链
  1) 溯源        提取核心断言
  2) 交叉验证     先查知识库；未命中再走实时联网（360 接口预留）
  3) 逻辑推演     模型基于证据推理，给出判定/真相/话术
  4) 证据链呈现   汇总成结构化结果（供公众号卡片消费）

设计要点：
  - 知识库强命中 → 走"数据复用"快路径，不调模型（即技术架构里的记忆/复用，且离线可演示）。
  - 未命中 → 有模型则推演，无模型则判"缺乏证据"并提示接入。
  - live_search() 是 360 的预留位，P2 填上即可。
"""
import config
from datetime import date
from knowledge_base import KnowledgeBase
from llm import LLMClient

VERDICTS = ["谣言", "误导性", "部分属实", "属实", "缺乏证据"]

REASON_SYSTEM = (
    "你是一名严谨的事实核查员，像调查记者一样工作。"
    "优先依据给到的【权威证据】判断；若没有外部证据，则依据你自身可靠的科学、医学、常识知识来判断，"
    "不要因为没有外部证据就拒绝下结论或退回『缺乏证据』。只有当问题本身太模糊、确实无从判断时才用『缺乏证据』。"
    "绝不编造具体的来源链接或数据；但应指出这类信息应以哪个权威机构/平台为准（只给机构名，不要编网址）。"
    "只输出 JSON，不要任何多余文字。"
)
REASON_USER_TMPL = """请核查下面这条信息，并严格按 JSON 输出。

【今天的真实日期】{today}（涉及"今天/明天/最近"等时间时，以此为准，绝不要自己臆造日期）

【待核查信息】
{claim}

【检索到的权威证据】（可能为空）
{evidence}

【话术标签可选值】
诉诸恐惧, 嫁接恐慌词, 诉诸情绪, 伪科学包装, 偷换概念, 倒果为因, 以偏概全, 脱离剂量谈毒性, 妖魔化中性词, 淡化风险, 绝对化承诺, 制造对立, 旧闻翻新, 信源不可查, 流量动机驱动, 歪曲事实

【判定档位含义】（选最贴切的一个）
- 谣言：内容与事实明显不符、纯属虚假
- 误导性：基于部分事实但以偏概全/断章取义，整体让人误解
- 部分属实：一半对一半错
- 属实：与事实相符、是该相信的正确信息
- 缺乏证据：你确实无法判断真假（信息太模糊或无任何可依据事实）。注意：只要你能写出明确的真相，就不要选"缺乏证据"。

【时效性/预测类信息规则】（重要）若这条信息的真假取决于"实时、未来或会随时变化的事实"——例如明天天气、近期股价、突发事件最新进展、某地是否停水等——你**没有实时数据，不要硬编一个答案或臆造日期**。这种情况 verdict 填"缺乏证据"，truth 写明"这属于时效性/预测类信息，真假取决于实时官方发布，无法据此核查，请以官方实时信息为准"，并在 authority 里给出对应的官方渠道（如：中国天气网/当地气象台、官方公告等）。

【high_risk 规则】仅当涉及"擅自停药、用药禁忌、可能危及人身安全"才填 true；普通食品、常识、社会传闻类一律 false。

【authority 规则】指出这类信息应以哪个权威机构/平台核实为准（只给机构名，例如：国家食品安全风险评估中心 / 国家药品监督管理局 / 国家卫健委 / 中国互联网联合辟谣平台 / 中国天气网 / 三甲医院）。绝不要编造网址。

【四格看穿 comic 规则】（这是给老人看的，不是给年轻人上课。务必遵守下面每一条）
1. 每格只说一句话，**最多 15 个字**，能更短就更短。像跟老人唠嗑，不像写说明。
2. 绝不用专业术语、绝不用"建议你""您应该""请注意""先想想"这种说教口气。
   语气要像年轻人发朋友圈/跟爸妈唠嗑：亲切、口语、可以带点小幽默和调侃，让人会心一笑（例：truth 写"得一口气炫上千只虾才中毒，你胃先投降了"）。但不冒犯、不轻浮。
3. 要具体、生动、有画面感，能用数字/比喻/大白话就用（例：与其说"剂量很低"，不如说"得吃下上千只虾才中毒"）。
   - **truth 这一格尤其要给具体的量**：把"适量/过量/微量"换成老人能感知的具体数字或画面。例如不要说"适量喝没事"，要说"一天三四杯以内都没事"；不要说"过量才有害"，要说"得一天灌下十几杯才可能有风险"。
   - 数字只用公认的常识值（如咖啡因每天 400mg 以内安全≈3~4 杯咖啡），并加"约""相当于"。**拿不准就用"远超正常人能吃/喝的量"这类定性说法，绝不编造精确数字。**
4. 四格内容固定为：
   - panic：用老人转发时的口气复述这条谣言（一句）
   - trick：它靠什么唬人，大白话（例："靠'砒霜'俩字吓你"）
   - truth：一句话戳破，越具体越好（例："得吃上千只虾才中毒"）
   - tip：**不要教方法**，而是给老人一句定心话或大白话提醒（例："放心吃，没事"／"别被吓到就行"）
5. emoji：为每格各挑 1 个最贴切的 emoji（panic 用 😱 类，truth 用 💡/✅ 类，tip 用 😌/🛡️ 类）。

【四格示范】（"维C和虾一起吃会中毒"）
panic:"听说维C配虾，吃了等于服毒？" trick:"靠'砒霜'俩字吓你" truth:"得一口气吃上千只虾才可能中毒，正常人吃不到" tip:"放心吃，没那回事"
【四格示范】（"喝咖啡导致骨质疏松"）
panic:"喝咖啡会得骨质疏松，太吓人了！" trick:"只说有害，不说要喝多少" truth:"一天三四杯内都安全，得天天灌十几杯才有风险" tip:"别怕，少喝几杯没事"

【输出 JSON 格式】
{{
  "verdict": "谣言/误导性/部分属实/属实/缺乏证据 之一",
  "high_risk": true/false,
  "safety_note": "若 high_risk 为 true，写一句给长辈的安全提示；否则填空字符串\"\"",
  "truth": "用通俗的话写清真相，1-2 句",
  "tactics": ["从上面标签里选 2-3 个"],
  "authority": "建议核实的权威机构名（不带网址）",
  "comic": {{"panic": "…", "trick": "…", "truth": "…", "tip": "…", "emoji": {{"panic":"😱","trick":"🎭","truth":"💡","tip":"😌"}}}},
  "confidence": 0.0-1.0
}}"""


class FactVerifier:
    def __init__(self):
        self.kb = KnowledgeBase()
        self.llm = LLMClient()

    # 权威域名白名单（可增减；最多 20 个，博查 include 上限）
    AUTHORITY_DOMAINS = [
        "piyao.org.cn",        # 中国互联网联合辟谣平台
        "kepuchina.cn",        # 科普中国
        "nhc.gov.cn",          # 国家卫健委
        "nmpa.gov.cn",         # 国家药监局
        "cdc.cn", "chinacdc.cn",  # 中国疾控
        "dxy.com",             # 丁香园/丁香医生
        "vist.org.cn",
        "xinhuanet.com",       # 新华网
        "people.com.cn",       # 人民网
        "cnr.cn",              # 央广网
        "who.int",             # 世界卫生组织
    ]

    # ---- 第2步 实时联网核查：博查 Web Search API（优先权威源）----
    def live_search(self, query):
        """返回 (evidence_list, source_list, is_authoritative)。
        先只在权威域名内搜；搜不到再放宽到全网（并标记为非权威，仅供参考）。
        任何失败（无 key / 超时 / 报错）静默返回空，自动降级到模型凭常识判，demo 不崩。"""
        import os
        try:
            import requests
        except ImportError:
            return [], [], False
        api_key = os.getenv("BOCHA_API_KEY", "")
        if not api_key:
            return [], [], False

        def _search(include=None):
            body = {"query": query, "summary": True, "count": 5, "freshness": "noLimit"}
            if include:
                body["include"] = include   # 博查：多域名用 | 分隔，限定只在这些站搜
            try:
                resp = requests.post(
                    "https://api.bochaai.com/v1/web-search",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=body, timeout=6,
                )
                resp.raise_for_status()
                return (resp.json().get("data") or {}).get("webPages", {}).get("value", []) or []
            except Exception:
                return []

        # 第一轮：只搜权威域名
        pages = _search(include="|".join(self.AUTHORITY_DOMAINS))
        is_auth = True
        # 第二轮：权威站没收录这条 → 放宽到全网，标记为非权威
        if not pages:
            pages = _search(include=None)
            is_auth = False

        evidence, sources = [], []
        for p in pages[:5]:
            name = (p.get("name") or "").strip()
            snippet = (p.get("snippet") or "").strip()
            url = (p.get("url") or "").strip()
            site = (p.get("siteName") or "").strip()
            if not snippet:
                continue
            evidence.append(f"【{site}】{name}：{snippet}")
            if url:
                tag = "" if is_auth else "（非权威源，仅供参考）"
                sources.append(f"{site or name}：{url}{tag}")
        return evidence, sources, is_auth

    # ---- 第1步 溯源 ----
    def _trace(self, raw_text):
        claim = raw_text.strip()
        # MVP：直接把输入当核心断言；P2 可让模型抽取/规整。
        return claim

    # ---- 主流程 ----
    def verify(self, raw_text):
        trace = {}
        # 1 溯源
        claim = self._trace(raw_text)
        trace["溯源"] = f"核心断言：{claim}"

        # 2 交叉验证：先查知识库
        hits = self.kb.search(claim)
        top_entry, top_score = (hits[0] if hits else (None, 0.0))
        trace["交叉验证"] = (
            f"知识库检索（{self.kb.backend_name}）最高相似度 {top_score:.2f}"
            + (f"，命中：{top_entry['claim'][:20]}…" if top_entry else "，无命中")
        )

        # 2a 知识库强命中 → 数据复用快路径（离线可跑，无需模型）
        if top_entry and top_score >= config.KB_HIT_THRESHOLD:
            trace["逻辑推演"] = "命中知识库，直接复用已核实结论（数据复用路径，未调用大模型）。"
            # 置信度沿用入库时存下的值，保证"同一条谣言每次都一致"；种子数据没存则给定高值
            reuse_conf = top_entry.get("confidence", 0.95)
            return self._present(claim, top_entry, trace,
                                  source_path="知识库·数据复用",
                                  confidence=reuse_conf,
                                  kb_hit=True)

        # 2b 未命中 → 实时联网核查（博查，优先权威源）
        live_evidence, live_sources, is_auth = self.live_search(claim)
        if live_evidence:
            tag = "权威网页" if is_auth else "网页（非权威，仅供参考）"
            trace["交叉验证"] += f"；联网核查到 {len(live_evidence)} 条{tag}"
        evidence = "\n".join(live_evidence) if live_evidence else "（无外部检索结果——请依据你自身可靠的科学/医学常识判断）"

        # 3 逻辑推演
        if self.llm.available:
            result = self.llm.chat_json(REASON_SYSTEM, REASON_USER_TMPL.format(
                claim=claim, evidence=evidence, today=date.today().isoformat()))
            trace["逻辑推演"] = f"调用大模型（{self.llm.model}）基于证据推演。"
            high_risk = bool(result.get("high_risk", False))
            note = (result.get("safety_note") or "").strip()
            authority = (result.get("authority") or "").strip()
            # 优先用博查搜回来的真实链接当来源；没搜到才退回"权威机构指向"
            sources = list(live_sources) if live_sources else []
            if not sources and authority:
                sources = [f"建议以「{authority}」官方信息为准（本结论由 AI 核查，未附直接链接）"]
            entry = {
                "claim": claim,
                "verdict": result.get("verdict", "缺乏证据"),
                "high_risk": high_risk,
                "truth": result.get("truth", ""),
                "tactics": result.get("tactics", []),
                "analogy": None,
                "sources": sources,
                "safety_note": note if (high_risk and note) else None,
                "category": "未分类",
                "comic": result.get("comic") or None,
            }
            # 记忆机制：判定明确且较有把握时，存回知识库 → 同一谣言下次秒级复用
            conf = float(result.get("confidence", 0.5))
            if entry["verdict"] != "缺乏证据" and conf >= 0.7:
                store = dict(entry, confidence=conf, claim_variants=[claim], id="learned-" + str(abs(hash(claim)) % 10**8))
                if self.kb.add(store):
                    trace["逻辑推演"] += "　✅ 已存入知识库，下次再问将秒级复用（记忆机制）"
            return self._present(claim, entry, trace,
                                 source_path=("实时联网+模型" if live_evidence else "仅模型推理(未接实时核查)"),
                                 confidence=conf,
                                 kb_hit=False)

        # 3' 无模型且未命中 → 老实承认（给用户看的得体话术，不暴露技术细节）
        trace["逻辑推演"] = "暂未查到权威结论，建议以官方发布为准。"
        entry = {
            "claim": claim, "verdict": "缺乏证据", "high_risk": False,
            "truth": "这条暂时没查到权威说法，先别急着信、也别急着转。建议看看官方平台（如卫健委、辟谣平台）有没有相关说明，以官方发布为准。",
            "tactics": [], "analogy": None, "sources": [], "safety_note": None, "category": "未分类",
        }
        return self._present(claim, entry, trace, source_path="无证据", confidence=0.0, kb_hit=False)

    # ---- 第4步 证据链呈现：统一结构（公众号卡片就消费这个 dict）----
    def _present(self, claim, entry, trace, source_path, confidence, kb_hit):
        result = {
            "input": claim,
            "core_claim": claim,
            "category": entry.get("category", "未分类"),
            "verdict": entry.get("verdict", "缺乏证据"),
            "high_risk": entry.get("high_risk", False),
            "confidence": confidence,
            "truth": entry.get("truth", ""),
            "tactics": entry.get("tactics", []),
            "analogy": entry.get("analogy"),
            "sources": entry.get("sources", []),
            "safety_note": entry.get("safety_note"),
            "comic": entry.get("comic") or self._fallback_comic(entry, claim),
            "source_path": source_path,  # 结论来自：知识库复用 / 实时联网+模型 / ...
            "kb_hit": kb_hit,
            "trace": trace,
        }
        result["trace"]["证据链"] = (
            f"判定={result['verdict']} 置信度={confidence} "
            f"话术={result['tactics']} 来源数={len(result['sources'])}"
        )
        return result

    @staticmethod
    def _fallback_comic(entry, claim):
        """种子数据/历史条目没有 comic 字段时，用已有信息拼一个四格，保证卡片不空。"""
        if entry.get("verdict") in (None, "缺乏证据"):
            return None
        tactics = entry.get("tactics", [])
        trick = "、".join(tactics[:2]) if tactics else "用吓人的说法让你不敢细想"
        truth = entry.get("truth", "")
        analogy = entry.get("analogy") or {}
        truth_panel = analogy.get("text") or truth
        return {
            "panic": claim,
            "trick": trick,
            "truth": truth_panel,
            "tip": "遇到吓你、催你、让你转发的消息，先停一停、查一查。",
        }
