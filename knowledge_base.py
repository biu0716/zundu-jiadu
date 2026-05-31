"""知识库：冷启动加载种子数据 + 检索 + 写回（自动扩库 / 记忆机制）。

检索可降级：
  - 优先 FaissRetriever（sentence-transformers + FAISS，语义检索，效果好）
  - 装不上 / 模型下不来时，自动退回 SimpleRetriever（零依赖，字符 bigram 重合度）
这样黑客松当天即便 FAISS/向量模型没装好，也能先跑通。
"""
import json
import os
import config


# ---------------- 降级方案：零依赖检索 ----------------
class SimpleRetriever:
    """中文友好的轻量匹配：用字符 bigram 集合的 Jaccard 相似度，无需分词。"""
    def __init__(self, docs):
        self.docs = docs  # [(text, entry)]
        self.doc_grams = [self._bigrams(t) for t, _ in docs]

    @staticmethod
    def _bigrams(text):
        s = "".join(ch for ch in text if ch.strip())
        return set(s[i:i + 2] for i in range(len(s) - 1)) or {s}

    def search(self, query, k):
        q = self._bigrams(query)
        scored = []
        for (text, entry), grams in zip(self.docs, self.doc_grams):
            inter = len(q & grams)
            # 重合度（overlap coefficient）：交集 / 较短者长度。
            # 比 Jaccard 更适合"短查询 vs 长文档"——查询基本被文档包含即高分。
            denom = min(len(q), len(grams)) or 1
            scored.append((entry, inter / denom))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def add_doc(self, text, entry):
        """运行中新增一条，立即可被检索（记忆机制/数据复用的关键）。"""
        self.docs.append((text, entry))
        self.doc_grams.append(self._bigrams(text))


# ---------------- 首选方案：FAISS 语义检索 ----------------
class FaissRetriever:
    def __init__(self, docs):
        from sentence_transformers import SentenceTransformer  # 延迟导入
        import faiss
        import numpy as np
        self._np = np
        self.docs = docs
        self.model = SentenceTransformer(config.EMBED_MODEL)
        embs = self.model.encode([t for t, _ in docs], normalize_embeddings=True)
        embs = np.asarray(embs, dtype="float32")
        self.index = faiss.IndexFlatIP(embs.shape[1])  # 归一化后内积≈余弦
        self.index.add(embs)

    def search(self, query, k):
        q = self.model.encode([query], normalize_embeddings=True)
        q = self._np.asarray(q, dtype="float32")
        scores, idx = self.index.search(q, min(k, len(self.docs)))
        return [(self.docs[i][1], float(s)) for i, s in zip(idx[0], scores[0]) if i >= 0]

    def add_doc(self, text, entry):
        """运行中新增一条：当场编码并加入索引，立即可被检索。"""
        emb = self.model.encode([text], normalize_embeddings=True)
        emb = self._np.asarray(emb, dtype="float32")
        self.index.add(emb)
        self.docs.append((text, entry))


# ---------------- 知识库主类 ----------------
class KnowledgeBase:
    def __init__(self, prefer_faiss=True):
        self.entries = self._load()
        docs = [(self._searchable_text(e), e) for e in self.entries]
        self.backend_name = "simple"
        self.retriever = SimpleRetriever(docs)
        if prefer_faiss:
            try:
                self.retriever = FaissRetriever(docs)
                self.backend_name = "faiss"
            except Exception as e:
                print(f"[知识库] FAISS 不可用，已降级为关键词匹配（{type(e).__name__}）。")

    def _load(self):
        with open(config.SEED_PATH, encoding="utf-8") as f:
            entries = json.load(f)["entries"]
        # 叠加自动扩库缓存（数据复用）
        if os.path.exists(config.CACHE_PATH):
            with open(config.CACHE_PATH, encoding="utf-8") as f:
                entries += json.load(f)
        return entries

    @staticmethod
    def _searchable_text(e):
        return " ".join([e["claim"], *e.get("claim_variants", []), e.get("truth", "")])

    def search(self, query, k=None):
        return self.retriever.search(query, k or config.TOP_K)

    def add(self, entry):
        """记忆机制 / 自动扩库：把新核实的结果存起来，并立即加入检索索引，
        使下次再问同一谣言能秒级复用（数据复用）。返回是否真的新增。"""
        # 去重：同一条已在库里就不重复存
        if any(e.get("claim") == entry.get("claim") for e in self.entries):
            return False
        # 1) 持久化到缓存文件（重启后仍在）
        cache = []
        if os.path.exists(config.CACHE_PATH):
            with open(config.CACHE_PATH, encoding="utf-8") as f:
                cache = json.load(f)
        cache.append(entry)
        with open(config.CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        # 2) 热更新内存索引（关键：当场可检索，无需重启）
        self.entries.append(entry)
        self.retriever.add_doc(self._searchable_text(entry), entry)
        return True
