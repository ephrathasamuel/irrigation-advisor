"""Plain-language explanation of a computed plan, written by Claude.

The model only explains numbers the app has already calculated; it is told
not to produce new figures of its own.
"""

import json
import os

import anthropic

MODEL = "claude-opus-5-5"
LANGUAGES = {"en": "English", "am": "Amharic", "om": "Afaan Oromo"}

SYSTEM_PROMPT = """You explain irrigation plans to smallholder farmers and agricultural extension officers in Ethiopia and East Africa.

You receive a plan that has already been calculated with the FAO-56 method from real weather data. Your job is to explain it, not to recalculate it.

Rules:
- Use only the numbers in the plan. Do not invent, estimate or round to new figures. If a number you would like is not in the plan, say it is not available.
- Write for someone who is not a scientist: short sentences, everyday words, no formulas. Explain "mm of water" once in practical terms (1 mm over one hectare is 10,000 litres).
- Structure the answer with these headings, each on its own line ending with a colon: "This week:", "When to water:", "Why:", "Practical tips:", "Check in the field:".
- Under each heading write two to four short lines starting with "- ".
- "Practical tips" should be practical for the crop, growth stage, soil and irrigation method in the plan (for example timing of watering in the day, avoiding waterlogging on clay, mulching).
- "Check in the field" must remind the reader that this is an estimate from weather data and tell them how to check soil moisture by hand.
- Mention any warnings in the plan.
- Plain text only: no markdown symbols other than the "- " at the start of lines."""


def ai_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


class AdvisorError(Exception):
    pass


def _plan_for_model(plan):
    """The parts of the plan the explanation needs, without chart-only fields."""
    keep = ("date", "forecast", "stage", "et0", "rain", "effective_rain", "kc", "etc",
            "depletion", "raw", "taw", "ks", "irrigation_net", "irrigation_gross")
    return {
        "inputs": plan["inputs"],
        "summary": plan["summary"],
        "balance_start": plan["balance_start"],
        "days": [{k: r.get(k) for k in keep} for r in plan["days"]],
        "climate_this_month": (plan.get("climate") or {}).get("this_month"),
        "warnings": plan["warnings"],
    }


def explain(plan, language="en", client=None):
    if language not in LANGUAGES:
        language = "en"
    client = client or anthropic.Anthropic()
    user = (
        f"Write the explanation in {LANGUAGES[language]}.\n\n"
        "Irrigation plan (JSON):\n"
        + json.dumps(_plan_for_model(plan), ensure_ascii=False, indent=1)
    )
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "medium"},
            # If the model declines, the API retries on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise AdvisorError("The AI key in .env was rejected. Check ANTHROPIC_API_KEY.") from exc
    except anthropic.RateLimitError as exc:
        raise AdvisorError("The AI service is busy (rate limit). Try again in a minute.") from exc
    except anthropic.APIConnectionError as exc:
        raise AdvisorError("Could not reach the AI service. Check the connection.") from exc
    except anthropic.APIStatusError as exc:
        raise AdvisorError(f"The AI service returned an error ({exc.status_code}).") from exc

    if response.stop_reason == "refusal":
        raise AdvisorError("The AI declined to explain this plan. The calculated plan above is still valid.")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise AdvisorError("The AI returned an empty explanation. Try again.")
    return {"text": text, "model": response.model, "language": LANGUAGES[language]}
