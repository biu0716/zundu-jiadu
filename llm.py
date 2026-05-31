"""大模型客户端：OpenAI 兼容接口，DeepSeek / 360 智脑 通用。
没有配置 API key 时 available=False，上层会自动走离线（知识库）路径。"""
import json
import config

try:
    import requests
except ImportError:
    requests = None


class LLMClient:
    def __init__(self):
        self.api_key = config.LLM_API_KEY
        self.base_url = config.LLM_BASE_URL.rstrip("/")
        self.model = config.LLM_MODEL
        self.auth_prefix = config.LLM_AUTH_PREFIX

    @property
    def available(self) -> bool:
        return bool(self.api_key) and requests is not None

    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        """返回模型输出的纯文本。"""
        if not self.available:
            raise RuntimeError("LLM 未配置（缺 API key 或 requests 库）")
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"{self.auth_prefix}{self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def chat_json(self, system: str, user: str) -> dict:
        """要求模型只返回 JSON，并安全解析（自动去掉 ```json 围栏）。"""
        raw = self.chat(system, user)
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # 兜底：截取第一个 { 到最后一个 }
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start != -1 and end != -1:
                return json.loads(cleaned[start:end + 1])
            raise
