
import json
from pathlib import Path

from huggingface_hub import hf_hub_download
from llama_cpp import Llama

MODEL_DIR = Path(".model-cache")
MODEL_FILENAME = "Qwen_Qwen3-1.7B-Q4_K_M.gguf"
MODEL_REPO = "bartowski/Qwen_Qwen3-1.7B-GGUF"

_model = None

EXPECTED_FIELDS = {
    "Bezirk",
    "Anzahl der Zimmer",
    "Stockwerk",
    "Aufzug vorhanden",
    "Unbefristet",
    "Separate Küche",
}


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
Du klassifizierst österreichische Wohnungsanzeigen,
insbesondere Mietwohnungen in Wien.

Antworte ausschließlich mit einem JSON-Objekt mit genau
diesen sechs Feldern:

{
  "Bezirk": 3,
  "Anzahl der Zimmer": 2,
  "Stockwerk": 0,
  "Aufzug vorhanden": true,
  "Unbefristet": false,
  "Separate Küche": null
}

Erlaubte Werte:
- Bezirk: Ganzzahl von 1 bis 23 oder null.
- Anzahl der Zimmer: Ganzzahl >= 1 oder null.
- Stockwerk: Ganzzahl >= 0 oder null.
- Aufzug vorhanden: true, false oder null.
- Unbefristet: true, false oder null.
- Separate Küche: true, false oder null.

KLASSIFIKATIONSREGELN

1. Bezirk
- Ermittle den Wiener Gemeindebezirk der Wohnung.
- Verwende eine ausdrücklich angegebene Bezirksnummer
  oder einen eindeutig zuordenbaren Wiener Bezirksnamen.
- Wiener Adressen und Postleitzahlen können helfen:
  1010 = Bezirk 1, 1020 = Bezirk 2,
  1030 = Bezirk 3, ..., 1230 = Bezirk 23.
- Verwechsle die Postleitzahl nicht mit der Bezirksnummer.
- Bei Orten außerhalb Wiens oder unklaren Angaben: null.

2. Anzahl der Zimmer
- Erfasse die Anzahl der Haupträume der Wohnung.
- Bevorzuge die ausdrücklich angegebene Zimmeranzahl,
  beispielsweise "2 Zimmer" oder "3-Zimmer-Wohnung".
- Zähle Badezimmer, Toiletten, Flure, Vorräume,
  Abstellräume und kleine separate Küchenräume nicht mit.
- Eine Wohnküche zählt nicht zusätzlich als Zimmer,
  wenn die Anzeige die Zimmeranzahl bereits angibt.
- Leite die Anzahl nicht allein aus der Wohnfläche ab.
- Bei widersprüchlichen oder fehlenden Angaben: null.

3. Stockwerk
Gib das Stockwerk als nichtnegative Ganzzahl zurück:
- Erdgeschoss, EG, Parterre: 0
- Hochparterre: 0
- Mezzanin: 1
- 1. Stock, 1. OG: 1
- 2. Stock, 2. OG: 2
- 3. Stock, 3. OG: 3
- Entsprechend für höhere Stockwerke.
- Keller oder Souterrain nicht als negatives Stockwerk
  darstellen; wenn keine passende Zahl bestimmbar ist: null.
- Unterscheide die Anzahl der Stockwerke des Gebäudes
  vom Stockwerk, auf dem sich die Wohnung befindet.
- Bei fehlenden oder widersprüchlichen Angaben: null.

4. Aufzug vorhanden
- true: Ein Aufzug, Lift oder Personenaufzug ist
  ausdrücklich als vorhanden angegeben.
- false: Es wird ausdrücklich angegeben, dass kein
  Aufzug oder Lift vorhanden ist.
- null: Keine eindeutige Information.
- Nicht aus Gebäudealter, Stockwerk oder anderen Merkmalen
  auf das Vorhandensein eines Aufzugs schließen.

5. Unbefristet
- true: Die Miete wird ausdrücklich als unbefristet
  oder ohne zeitliche Befristung angegeben.
- false: Die Miete wird ausdrücklich als befristet,
  zeitlich begrenzt oder als Zwischenmiete angegeben.
- null: Keine eindeutige Information oder Widerspruch.
- Eine bloße Angabe zur Verfügbarkeit ist keine Aussage
  über die Mietdauer.

6. Separate Küche
- true: Die Küche ist ein eigener, räumlich getrennter Raum.
- false: Die Anzeige bezeichnet sie ausdrücklich als
  Wohnküche, offene Küche, offene Wohnküche oder Küche
  im Wohn- bzw. Essbereich.
- null: Keine eindeutige Information oder Widerspruch.
- Die bloße Erwähnung einer Küche beweist nicht,
  dass sie ein eigener Raum ist.

ALLGEMEINE REGELN
- Verwende ausschließlich Informationen aus der Anzeige.
- Nicht raten und keine fehlenden Informationen ergänzen.
- Verwende null, wenn eine Angabe nicht zuverlässig
  festgestellt werden kann.
- Gib keine Erklärungen außerhalb des JSON-Objekts aus.

BESCHREIBUNG:
""" + description[:10000]

    llm = get_model()

    response = llm.create_chat_completion(
        messages=[
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=250,
    )

    content = response["choices"][0]["message"]["content"]
    print("RAW MODEL OUTPUT:", repr(content), flush=True)
    
    if not content or not content.strip():
        raise ValueError("Model returned empty content")
    
    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Model returned invalid JSON: {content!r}"
        ) from e

    if not isinstance(result, dict) or set(result) != EXPECTED_FIELDS:
        raise ValueError(f"Unexpected model output: {content}")

    # Validate numeric fields.
    for key, minimum, maximum in [
        ("Bezirk", 1, 23),
        ("Anzahl der Zimmer", 1, None),
        ("Stockwerk", 0, None),
    ]:
        value = result[key]

        if value is None:
            continue

        if type(value) is not int:
            raise ValueError(f"{key} must be an integer or null")

        if value < minimum or (
            maximum is not None and value > maximum
        ):
            raise ValueError(f"Invalid value for {key}: {value}")

    # Validate Boolean fields.
    for key in [
        "Aufzug vorhanden",
        "Unbefristet",
        "Separate Küche",
    ]:
        value = result[key]

        if value is not None and type(value) is not bool:
            raise ValueError(f"Invalid value for {key}: {value}")

    return result
