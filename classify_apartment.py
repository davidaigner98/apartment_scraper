
import json
import os
from pathlib import Path

from huggingface_hub import hf_hub_download
from llama_cpp import Llama

MODEL_DIR = Path(".model-cache")
MODEL_FILENAME = "Qwen_Qwen3-1.7B-Q4_K_M.gguf"
MODEL_REPO = "bartowski/Qwen_Qwen3-1.7B-GGUF"

_model = None


def get_model():
    global _model

    if _model is not None:
        return _model

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / MODEL_FILENAME

    if not model_path.exists():
        hf_hub_download(
            repo_id=MODEL_REPO,
            filename=MODEL_FILENAME,
            local_dir=str(MODEL_DIR),
        )

    _model = Llama(
        model_path=str(model_path),
        n_ctx=4096,
        n_threads=4,
        verbose=False,
    )

    return _model


def classify_apartment(description):
    prompt = """
Du klassifizierst österreichische Wohnungsanzeigen.

Antworte ausschließlich mit einem JSON-Objekt mit genau
diesen drei Feldern:
{
  "ground_floor": true,
  "limited_duration": null,
  "separate_kitchen": false
}

Erlaubte Werte sind true, false und null.

Definitionen:
- ground_floor: true bei Erdgeschoss, EG oder Parterre.
  false nur, wenn ein anderes Stockwerk ausdrücklich feststeht.
- limited_duration: true bei ausdrücklich befristeter Miete
  oder Zwischenmiete. false nur, wenn unbefristete Miete
  ausdrücklich angegeben ist.
- separate_kitchen: true bei einer eigenen, getrennten Küche.
  false bei ausdrücklich offener Küche oder Küche im Wohnbereich.
- null bei fehlenden, unklaren oder widersprüchlichen Angaben.

Nicht raten. Fehlende Informationen bedeuten null.

Beschreibung:
""" + description[:10000]

    llm = get_model()

    response = llm.create_chat_completion(
        messages=[
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=150,
    )

    content = response["choices"][0]["message"]["content"]
    result = json.loads(content)

    expected = {
        "ground_floor",
        "limited_duration",
        "separate_kitchen",
    }

    if not isinstance(result, dict) or set(result) != expected:
        raise ValueError(f"Unexpected model output: {content}")

    for key in expected:
        if result[key] is not None and type(result[key]) is not bool:
            raise ValueError(f"Invalid value for {key}")

    return result
