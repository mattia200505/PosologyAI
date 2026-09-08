from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Optional

import requests


@dataclass
class _Message:
    role: str
    content: str


@dataclass
class _Choice:
    index: int
    message: _Message
    finish_reason: Optional[str] = None


class _ChatEndpoint:
    def __init__(self, api_key: Optional[str]) -> None:
        self._api_key = api_key or os.getenv("MISTRAL_API_KEY")

    def complete(self, **kwargs: Any) -> Any:
        if not self._api_key:
            raise ValueError("MISTRAL_API_KEY is missing")

        payload: Dict[str, Any] = {
            "model": kwargs.get("model"),
            "messages": [self._normalize_message(message) for message in kwargs.get("messages", [])],
        }

        for key in ("temperature", "max_tokens", "top_p", "random_seed"):
            value = kwargs.get(key)
            if value is not None:
                payload[key] = value

        if "safe_mode" in kwargs:
            payload["safe_prompt"] = kwargs["safe_mode"]

        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        choices = [
            _Choice(
                index=choice.get("index", 0),
                message=_Message(
                    role=choice.get("message", {}).get("role", "assistant"),
                    content=choice.get("message", {}).get("content", ""),
                ),
                finish_reason=choice.get("finish_reason"),
            )
            for choice in data.get("choices", [])
        ]
        # La reponse brute porte deja une cle `choices` : on la retire avant
        # l'eclatage en attributs, sinon SimpleNamespace leve
        # « got multiple values for keyword argument 'choices' » et chaque
        # appel IA (recherche, chatbot, resumes) echouait.
        data = {key: value for key, value in data.items() if key != "choices"}
        result = SimpleNamespace(**data)
        result.choices = choices
        return result

    @staticmethod
    def _normalize_message(message: Any) -> Dict[str, Any]:
        if isinstance(message, dict):
            return {"role": message.get("role", "user"), "content": message.get("content", "")}
        return {
            "role": getattr(message, "role", "user"),
            "content": getattr(message, "content", ""),
        }


class Mistral:
    def __init__(self, api_key: Optional[str] = None, **_: Any) -> None:
        self.chat = _ChatEndpoint(api_key)


MistralClient = Mistral
