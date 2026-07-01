import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from ollama import Client
from pydantic import BaseModel, ValidationError

import config

logger = logging.getLogger("neet_adaptive.ollama_client")

T = TypeVar("T", bound=BaseModel)

_client = Client(
    host=config.OLLAMA_HOST,
    headers={"Authorization": f"Bearer {config.OLLAMA_API_KEY}"} if config.OLLAMA_API_KEY else None,
)


class AgentGenerationError(Exception):
    pass


def _log_call(system_prompt: str, user_prompt: str, raw_response: str, error: str | None = None) -> None:
    path = Path(config.LLM_CALL_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "raw_response": raw_response,
        "error": error,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def call_structured(
    system_prompt: str,
    user_prompt: str,
    schema_model: type[T],
    model: str | None = None,
    temperature: float = 0.2,
) -> T:
    """Calls Ollama with JSON-schema-constrained output, validates against schema_model,
    and retries once (with the validation error fed back to the model) before raising."""
    model = model or config.OLLAMA_MODEL
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    schema = schema_model.model_json_schema()

    last_error: Exception | None = None
    for attempt in range(2):
        response = _client.chat(
            model=model,
            messages=messages,
            format=schema,
            options={"temperature": temperature},
        )
        raw_content = response.message.content
        try:
            parsed = schema_model.model_validate_json(raw_content)
            _log_call(system_prompt, user_prompt, raw_content)
            return parsed
        except (ValidationError, ValueError) as e:
            last_error = e
            _log_call(system_prompt, user_prompt, raw_content, error=str(e))
            if attempt == 0:
                logger.warning("Structured call failed validation, retrying once: %s", e)
                messages.append({"role": "assistant", "content": raw_content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was invalid: {e}. "
                            "Return ONLY corrected JSON matching the required schema."
                        ),
                    }
                )

    raise AgentGenerationError(
        f"Failed to get a valid {schema_model.__name__} from {model} after retry: {last_error}"
    )
