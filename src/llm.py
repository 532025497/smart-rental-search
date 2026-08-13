# -*- coding: utf-8 -*-
"""LLM客户端 — OpenAI兼容API (DeepSeek/Qwen/OpenAI/Ollama均可)

使用urllib，无需安装第三方依赖。
"""
import json
import urllib.request
import urllib.error


class LLMClient:
    """OpenAI兼容的LLM客户端"""

    def __init__(self, api_key: str, base_url: str,
                 model: str, timeout: int = 30):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._call_count = 0
        self._total_tokens = 0

    @property
    def call_count(self):
        return self._call_count

    @property
    def total_tokens(self):
        return self._total_tokens

    def chat(self, messages: list, temperature: float = 0.1,
             json_mode: bool = False) -> str:
        """发送聊天请求

        Args:
            messages: [{"role": "system"/"user"/"assistant", "content": "..."}]
            temperature: 0-1, 越低越确定性
            json_mode: 强制返回JSON格式

        Returns:
            LLM的文本回复
        """
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        data = json.dumps(body).encode("utf-8")
        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        })

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            self._call_count += 1
            self._total_tokens += result.get("usage", {}).get("total_tokens", 0)
            return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise Exception(f"LLM API错误({e.code}): {err_body[:200]}")
        except urllib.error.URLError as e:
            raise Exception(f"LLM网络请求失败: {e}")
        except (KeyError, json.JSONDecodeError) as e:
            raise Exception(f"LLM响应解析失败: {e}")

    def chat_json(self, messages: list, temperature: float = 0.1) -> dict:
        """发送聊天请求并解析JSON响应

        自动添加"请以JSON格式回复"的指令。
        """
        # 在system message中追加JSON要求
        msgs = messages.copy()
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] += "\n\n请以合法的JSON格式回复，不要包含```json```标记。"
        else:
            msgs.insert(0, {"role": "system",
                            "content": "请以合法的JSON格式回复，不要包含```json```标记。"})

        text = self.chat(msgs, temperature=temperature, json_mode=True)
        # 清理可能的markdown标记
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        return json.loads(text)
