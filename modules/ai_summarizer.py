"""AI summary helpers for CashCanvas monthly spending reports."""

from __future__ import annotations

import os
import re
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors


# Load environment variables once so the Gemini API key can come from a .env file.
load_dotenv()


# Cache the discovered model order for the lifetime of the Python process.
_CACHED_TEXT_MODELS: list[str] | None = None


def compute_month_stats(df: pd.DataFrame, month_year: str) -> dict[str, Any]:
    """Compute plain Python stats for one month of transaction data."""

    if df is None or df.empty:
        return {
            "month_year": month_year,
            "month_label": month_year,
            "total_spend": 0.0,
            "top_categories": [],
            "pct_change_vs_previous_month": None,
            "previous_month_spend": None,
            "highest_transaction": None,
            "comparison_text": "No spending data was available for this month.",
        }

    frame = df.copy()
    frame["txn_date"] = pd.to_datetime(frame["txn_date"])

    current_period = pd.Period(month_year, freq="M")
    previous_period = current_period - 1

    # Total spend is the base monthly summary statistic.
    current_month_mask = frame["txn_date"].dt.to_period("M") == current_period
    current_month_df = frame.loc[current_month_mask].copy()
    total_spend = float(current_month_df["amount"].sum())

    # Top categories come from grouping and summing category spend.
    category_totals = (
        current_month_df.groupby("category", dropna=False)["amount"]
        .sum()
        .sort_values(ascending=False)
        .head(3)
    )
    top_categories = [
        {"category": str(category), "amount": float(amount)}
        for category, amount in category_totals.items()
    ]

    # Find the single largest transaction so the final summary can mention the biggest item.
    highest_transaction = None
    if not current_month_df.empty:
        top_row = current_month_df.sort_values("amount", ascending=False).iloc[0]
        highest_transaction = {
            "amount": float(top_row["amount"]),
            "category": str(top_row.get("category", "Uncategorized")),
            "description": str(top_row.get("description", "")),
            "txn_date": pd.to_datetime(top_row["txn_date"]).strftime("%Y-%m-%d"),
        }

    # Compare the current month against the previous month using the same transaction data.
    previous_month_mask = frame["txn_date"].dt.to_period("M") == previous_period
    previous_month_spend = float(frame.loc[previous_month_mask, "amount"].sum())

    if previous_month_spend > 0:
        pct_change_vs_previous_month = ((total_spend - previous_month_spend) / previous_month_spend) * 100.0
        if pct_change_vs_previous_month > 0:
            comparison_text = (
                f"Spending went up by {pct_change_vs_previous_month:.1f}% compared with last month."
            )
        elif pct_change_vs_previous_month < 0:
            comparison_text = (
                f"Spending went down by {abs(pct_change_vs_previous_month):.1f}% compared with last month."
            )
        else:
            comparison_text = "Spending was unchanged compared with last month."
    else:
        pct_change_vs_previous_month = None
        comparison_text = "A month-over-month comparison was not available in the provided data."

    return {
        "month_year": month_year,
        "month_label": current_period.strftime("%B %Y"),
        "total_spend": total_spend,
        "top_categories": top_categories,
        "pct_change_vs_previous_month": pct_change_vs_previous_month,
        "previous_month_spend": previous_month_spend if previous_month_spend > 0 else None,
        "highest_transaction": highest_transaction,
        "comparison_text": comparison_text,
    }


def build_ai_prompt(stats: dict[str, Any]) -> str:
    """Build a prompt that asks Gemini to narrate the computed stats without doing math."""

    top_categories = stats.get("top_categories", [])
    category_lines = []
    for item in top_categories:
        category_lines.append(f"- {item['category']}: {item['amount']:.2f}")

    highest_transaction = stats.get("highest_transaction")
    if highest_transaction:
        highest_text = (
            f"Highest transaction: {highest_transaction['amount']:.2f} in {highest_transaction['category']} "
            f"on {highest_transaction['txn_date']} ({highest_transaction['description']})."
        )
    else:
        highest_text = "Highest transaction: not available."

    comparison_text = stats.get("comparison_text", "")

    prompt = (
        f"You are writing a short, friendly monthly spending summary for CashCanvas. "
        f"Write 3-4 sentences only. Use the facts below exactly as given. Do not do any arithmetic or introduce new numbers. "
        f"Mention the top category and clearly say whether spending went up or down vs last month if that comparison is available. "
        f"If the comparison is unavailable, say that gently.\n\n"
        f"Month: {stats.get('month_label', stats.get('month_year', 'Unknown month'))}\n"
        f"Total spend: {stats.get('total_spend', 0.0):.2f}\n"
        f"Top categories:\n{chr(10).join(category_lines) if category_lines else '- No category data available.'}\n"
        f"{highest_text}\n"
        f"Month-over-month note: {comparison_text}\n\n"
        f"Return only the paragraph."
    )
    return prompt


def _normalize_model_name(model_name: Any) -> str:
    """Return a clean model name without the optional ``models/`` prefix."""

    normalized_name = str(model_name or "").strip()
    if normalized_name.startswith("models/"):
        normalized_name = normalized_name.removeprefix("models/")
    return normalized_name


def _supports_text_generation(model: Any) -> bool:
    """Check whether a listed model appears to support text generation."""

    model_name = _normalize_model_name(getattr(model, "name", "")).lower()
    display_name = _normalize_model_name(getattr(model, "display_name", "")).lower()
    combined_name = f"{model_name} {display_name}".strip()

    # Ignore model families that are clearly not text generation models.
    excluded_fragments = (
        "embed",
        "embedding",
        "imagen",
        "image",
        "veo",
        "video",
        "tts",
        "speech",
        "live",
        "realtime",
        "audio",
    )
    if any(fragment in combined_name for fragment in excluded_fragments):
        return False

    # Different SDK versions expose capabilities with slightly different names,
    # so we look for the generate-content action in any capability field that exists.
    capability_sources = (
        getattr(model, "supported_actions", None),
        getattr(model, "supported_generation_methods", None),
    )
    for source in capability_sources:
        if not source:
            continue

        if isinstance(source, (str, bytes)):
            capability_text = str(source).lower()
        else:
            capability_text = " ".join(str(item).lower() for item in source)

        if "generate_content" in capability_text or "generatecontent" in capability_text:
            return True

    # If the SDK does not expose a capability field, fall back to the model name.
    return "gemini" in combined_name or "tuned" in combined_name


def _model_stage_rank(model: Any) -> int:
    """Rank model stability so stable models sort ahead of preview and experimental ones."""

    status = getattr(model, "model_status", None)
    stage = getattr(status, "model_stage", None) or getattr(model, "model_stage", None)
    stage_text = str(stage or "").lower()

    if "stable" in stage_text:
        return 0
    if "preview" in stage_text:
        return 1
    if "experimental" in stage_text or "unstable" in stage_text:
        return 2
    if "legacy" in stage_text or "deprecated" in stage_text or "retired" in stage_text:
        return 3
    return 4


def _model_family_rank(model_name: str) -> int:
    """Prefer Flash models because this project only needs short text summaries."""

    lower_name = model_name.lower()
    if "flash" in lower_name:
        return 0
    if "pro" in lower_name:
        return 1
    return 2


def _model_version_score(model_name: str) -> float:
    """Extract a simple version score so newer models sort ahead of older ones."""

    match = re.search(r"gemini-(\d+(?:\.\d+)?)", model_name.lower())
    if match:
        return float(match.group(1))
    return 0.0


def _discover_text_models(client: genai.Client) -> list[str]:
    """Discover and cache compatible text-generation models for the current API key."""

    global _CACHED_TEXT_MODELS

    if _CACHED_TEXT_MODELS is not None:
        return _CACHED_TEXT_MODELS

    discovered_models: list[tuple[tuple[int, int, float, str], str]] = []

    try:
        for model in client.models.list():
            if not _supports_text_generation(model):
                continue

            normalized_name = _normalize_model_name(getattr(model, "name", ""))
            if not normalized_name:
                continue

            sort_key = (
                _model_stage_rank(model),
                _model_family_rank(normalized_name),
                -_model_version_score(normalized_name),
                normalized_name.lower(),
            )
            discovered_models.append((sort_key, normalized_name))
    except Exception as exc:
        raise RuntimeError("Unable to discover Gemini text-generation models.") from exc

    discovered_models.sort(key=lambda item: item[0])
    _CACHED_TEXT_MODELS = [model_name for _, model_name in discovered_models]
    return _CACHED_TEXT_MODELS


def _build_model_candidates(client: genai.Client) -> list[str]:
    """Build the ordered model list, honoring GEMINI_MODEL as a first attempt."""

    discovered_models = _discover_text_models(client)
    requested_model = _normalize_model_name(os.getenv("GEMINI_MODEL", ""))

    candidates: list[str] = []
    if requested_model:
        candidates.append(requested_model)

    for model_name in discovered_models:
        if model_name not in candidates:
            candidates.append(model_name)

    return candidates


def select_available_model(client: genai.Client) -> str:
    """Return the preferred Gemini text-generation model for this app.

    The function caches the discovered model order so Streamlit reruns do not
    call ``client.models.list()`` every time.
    """

    candidates = _discover_text_models(client)
    if not candidates:
        raise RuntimeError("No compatible Gemini text-generation model is available.")

    return candidates[0]


def _is_retryable_model_error(exc: Exception) -> bool:
    """Return True when the current model can be skipped and the next one tried."""

    error_code = getattr(exc, "code", None)
    error_text = f"{type(exc).__name__}: {exc}".lower()

    if error_code in {401, 403, 429}:
        return False

    if any(keyword in error_text for keyword in ("unauthorized", "authentication", "quota", "rate limit", "too many requests", "api key")):
        return False

    if any(keyword in error_text for keyword in ("timeout", "connection", "network", "dns")):
        return False

    if error_code in {404, 400, 422, 501}:
        if any(keyword in error_text for keyword in ("model not found", "not found", "unsupported", "unsupported model", "model unavailable", "model is not available")):
            return True

    if any(keyword in error_text for keyword in ("model not found", "unsupported", "not found", "model unavailable", "not available")):
        return True

    return False


def _is_fatal_gemini_error(exc: Exception) -> bool:
    """Return True for errors that should immediately trigger the fallback summary."""

    error_code = getattr(exc, "code", None)
    error_text = f"{type(exc).__name__}: {exc}".lower()

    if error_code in {401, 403, 429}:
        return True

    if any(keyword in error_text for keyword in ("unauthorized", "authentication", "quota", "rate limit", "too many requests", "api key")):
        return True

    if any(keyword in error_text for keyword in ("timeout", "connection", "network", "dns")):
        return True

    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True

    if isinstance(exc, genai_errors.APIError) and error_code not in {400, 404, 422, 501}:
        return True

    return False


def _generate_with_gemini(client: genai.Client, prompt: str) -> str | None:
    """Send the prompt to Gemini and return the generated text, or None on failure."""

    try:
        candidates = _build_model_candidates(client)
    except RuntimeError:
        return None

    for model_name in candidates:
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            text = getattr(response, "text", None)
            if text:
                return str(text).strip()
        except Exception as exc:
            if _is_fatal_gemini_error(exc):
                return None

            if _is_retryable_model_error(exc):
                continue

            return None

    return None


def _build_fallback_summary(stats: dict[str, Any]) -> str:
    """Create a plain-text summary if the Gemini API is unavailable."""

    month_label = stats.get("month_label", stats.get("month_year", "this month"))
    total_spend = stats.get("total_spend", 0.0)
    top_categories = stats.get("top_categories", [])
    comparison_text = stats.get("comparison_text", "")
    highest_transaction = stats.get("highest_transaction")

    top_category_text = "no category data was available"
    if top_categories:
        top_category_text = f"{top_categories[0]['category']} was the highest category"

    highest_text = ""
    if highest_transaction:
        highest_text = (
            f" The single largest transaction was {highest_transaction['amount']:.2f} in "
            f"{highest_transaction['category']} on {highest_transaction['txn_date']}."
        )

    return (
        f"In {month_label}, total spending was {total_spend:.2f}. {top_category_text}. "
        f"{comparison_text}{highest_text}"
    ).strip()


def generate_monthly_summary(df: pd.DataFrame, month_year: str) -> str:
    """Generate a friendly monthly spending summary using Gemini, with a safe fallback."""

    stats = compute_month_stats(df, month_year)
    prompt = build_ai_prompt(stats)

    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key or api_key == "your_key_here":
        return _build_fallback_summary(stats)

    client = genai.Client(api_key=api_key)
    ai_summary = _generate_with_gemini(client, prompt)

    if ai_summary:
        return ai_summary

    return _build_fallback_summary(stats)
