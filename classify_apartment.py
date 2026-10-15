
import json
import os
from pathlib import Path

from huggingface_hub import hf_hub_download
from llama_cpp import Llama

MODEL_DIR = Path(os.getenv("MODEL_DIR", ".model-cache"))
MODEL_PATH = MODEL_DIR / "Qwen3-1.7B-Q4_K_M.gguf"

def get_model():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    if not MODEL_PATH.exists():
        hf_hub_download(
            repo_id="bartowski/Qwen_Qwen3-1.7B-GGUF",
            filename="Qwen3-1.7B-Q4_K_M.gguf",
            local_dir=str(MODEL_DIR),
        )

    return Llama(
        model_path=str(MODEL_PATH),
        n_ctx=4096,
        n_threads=4,
        verbose=False,
    )

PROMPT = """
Du klassifizierst österreichische Wohnungsanzeigen.
Verwende ausschließlich den folgenden Beschreibungstext.

Gib ausschließlich ein JSON-Objekt zurück:
{
  "ground_floor": true | false | null,
  "limited_duration": true | false | null,
  "separate_kitchen": true | false | null
}

Regeln:
- ground_floor: true bei Erdgeschoss, EG oder Parterre.
  false nur, wenn ein anderes Stockwerk ausdrücklich feststeht.
- limited_duration: true bei ausdrücklich befristeter Miete
  oder Zwischenmiete. false nur, wenn unbefristete Miete
  ausdrücklich angegeben ist.
- separate_kitchen: true bei einer eigenen, getrennten Küche.
  false bei ausdrücklich offener Küche oder integrierter
  Wohnküche.
- null bei fehlenden, unklaren oder widersprüchlichen Angaben.
- Nicht raten. Fehlende Angaben sind nicht false.

Beschreibung:
"""

def classify_apartment(llm, description):
    response = llm.create_chat_completion(
        messages=[
            {
                "role": "user",
                "content": PROMPT + description[:10000],
            }
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=150,
    )

    raw = response["choices"][0]["message"]["content"]
    result = json.loads(raw)

    expected = {
        "ground_floor",
        "limited_duration",
        "separate_kitchen",
    }

    if set(result) != expected:
        raise ValueError("Unexpected classification fields")

    for key in expected:
        if result[key] not in (True, False, None):
            raise ValueError(f"Invalid value for {key}")

    return result
