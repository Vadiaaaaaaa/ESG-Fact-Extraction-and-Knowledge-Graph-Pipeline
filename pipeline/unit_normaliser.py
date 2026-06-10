from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_HERE), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)


import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from normalizer_guardrails import extract_primary_numeric


UNIT_MAP: dict[str, tuple[str, float]] = {
    "%": ("%", 1.0),
    "percent": ("%", 1.0),
    "percentage": ("%", 1.0),
    "pct": ("%", 1.0),
    "basis points": ("%", 0.01),
    "basis point": ("%", 0.01),
    "bps": ("%", 0.01),
    "bp": ("%", 0.01),
    "percentage points": ("%", 1.0),
    "pp": ("%", 1.0),
    "ppt": ("%", 1.0),
    "number": ("count", 1.0),
    "numbers": ("count", 1.0),
    "count": ("count", 1.0),
    "counts": ("count", 1.0),
    "nos": ("count", 1.0),
    "no": ("count", 1.0),
    "no.": ("count", 1.0),
    "unit": ("count", 1.0),
    "units": ("count", 1.0),
    "stores": ("count", 1.0),
    "store": ("count", 1.0),
    "outlets": ("count", 1.0),
    "outlet": ("count", 1.0),
    "factories": ("count", 1.0),
    "factory": ("count", 1.0),
    "facilities": ("count", 1.0),
    "facility": ("count", 1.0),
    "sites": ("count", 1.0),
    "site": ("count", 1.0),
    "warehouses": ("count", 1.0),
    "warehouse": ("count", 1.0),
    "plants": ("count", 1.0),
    "plant": ("count", 1.0),
    "production lines": ("count", 1.0),
    "lines": ("count", 1.0),
    "line": ("count", 1.0),
    "people": ("count", 1.0),
    "employees": ("count", 1.0),
    "employee": ("count", 1.0),
    "workers": ("count", 1.0),
    "worker": ("count", 1.0),
    "beneficiaries": ("count", 1.0),
    "patents": ("count", 1.0),
    "hours": ("hours", 1.0),
    "hour": ("hours", 1.0),
    "hrs": ("hours", 1.0),
    "hr": ("hours", 1.0),
    "man-hours": ("hours", 1.0),
    "man hours": ("hours", 1.0),
    "days": ("days", 1.0),
    "day": ("days", 1.0),
    "number of days": ("days", 1.0),
    # Safety frequency rates
    "per one million person hours worked": ("per_million_hours", 1.0),
    "per one million-person hours worked": ("per_million_hours", 1.0),
    "per million person hours": ("per_million_hours", 1.0),
    "per million-person hours": ("per_million_hours", 1.0),
    "per million hours worked": ("per_million_hours", 1.0),
    "ltifr": ("per_million_hours", 1.0),
    # Air pollutant equivalents
    "kgsoxe": ("kg", 1.0),
    "kg soxe": ("kg", 1.0),
    "kgnoxe": ("kg", 1.0),
    "kg noxe": ("kg", 1.0),
    "kgno2e": ("kg", 1.0),
    "kg no2e": ("kg", 1.0),
    "years": ("years", 1.0),
    "year": ("years", 1.0),
    "minutes": ("minutes", 1.0),
    "minute": ("minutes", 1.0),
    "mins": ("minutes", 1.0),
    "min": ("minutes", 1.0),
    "seconds": ("seconds", 1.0),
    "second": ("seconds", 1.0),
    "sec": ("seconds", 1.0),
    "l": ("L", 1.0),
    "litre": ("L", 1.0),
    "litres": ("L", 1.0),
    "liter": ("L", 1.0),
    "liters": ("L", 1.0),
    "mn litres": ("L", 1_000_000.0),
    "million litres": ("L", 1_000_000.0),
    "million liters": ("L", 1_000_000.0),
    "mn l": ("L", 1_000_000.0),
    "mliters": ("L", 1_000_000.0),
    "kl": ("L", 1_000.0),
    "kilolitre": ("L", 1_000.0),
    "kilolitres": ("L", 1_000.0),
    "kiloliter": ("L", 1_000.0),
    "kiloliters": ("L", 1_000.0),
    "000 kl": ("L", 1_000_000.0),
    "mn kl": ("L", 1_000_000_000.0),
    "m3": ("L", 1_000.0),
    "m^3": ("L", 1_000.0),
    "cubic metre": ("L", 1_000.0),
    "cubic metres": ("L", 1_000.0),
    "cubic meter": ("L", 1_000.0),
    "cubic meters": ("L", 1_000.0),
    "gallon": ("L", 3.78541),
    "gallons": ("L", 3.78541),
    "kg": ("kg", 1.0),
    "kilogram": ("kg", 1.0),
    "kilograms": ("kg", 1.0),
    "g": ("kg", 0.001),
    "gram": ("kg", 0.001),
    "grams": ("kg", 0.001),
    "mt": ("kg", 1_000.0),
    "metric ton": ("kg", 1_000.0),
    "metric tons": ("kg", 1_000.0),
    "metric tonne": ("kg", 1_000.0),
    "metric tonnes": ("kg", 1_000.0),
    "tonne": ("kg", 1_000.0),
    "tonnes": ("kg", 1_000.0),
    "ton": ("kg", 1_000.0),
    "tons": ("kg", 1_000.0),
    "kt": ("kg", 1_000_000.0),
    "ktonnes": ("kg", 1_000_000.0),
    "kilo tonnes": ("kg", 1_000_000.0),
    "kilo tonne": ("kg", 1_000_000.0),
    "ktonne": ("kg", 1_000_000.0),
    "gj": ("GJ", 1.0),
    "gigajoule": ("GJ", 1.0),
    "gigajoules": ("GJ", 1.0),
    "mj": ("GJ", 0.001),
    "megajoule": ("GJ", 0.001),
    "megajoules": ("GJ", 0.001),
    "kj": ("GJ", 0.000001),
    "kwh": ("GJ", 0.0036),
    "mwh": ("GJ", 3.6),
    "gwh": ("GJ", 3600.0),
    "kwhr": ("GJ", 0.0036),
    "mmbtu": ("GJ", 1.055056),
    "gj/tonne": ("GJ/tonne", 1.0),
    "gj per tonne": ("GJ/tonne", 1.0),
    "gj/ton": ("GJ/tonne", 1.0),
    "gj per ton": ("GJ/tonne", 1.0),
    "kl/tonne": ("kL/tonne", 1.0),
    "kl per tonne": ("kL/tonne", 1.0),
    "kl/ton": ("kL/tonne", 1.0),
    "l/tonne": ("L/tonne", 1.0),
    "litres/tonne": ("L/tonne", 1.0),
    "liters/tonne": ("L/tonne", 1.0),
    "l/kg": ("L/kg", 1.0),
    "liters/kg": ("L/kg", 1.0),
    "litres/kg": ("L/kg", 1.0),
    "cases/person": ("cases/person", 1.0),
    "tco2e": ("tCO2e", 1.0),
    "t co2e": ("tCO2e", 1.0),
    "metric ton of co2 equivalent": ("tCO2e", 1.0),
    "metric tonnes of co2 equivalent": ("tCO2e", 1.0),
    "metric tons of co2 equivalent": ("tCO2e", 1.0),
    "metric tons of co2 equivalant": ("tCO2e", 1.0),
    "mt co2 equivalent": ("tCO2e", 1.0),  # Indian BRSR: MT = metric tonne, not megatonne
    "metric tonnes co2e": ("tCO2e", 1.0),
    "metric tons co2e": ("tCO2e", 1.0),
    "tonnes co2e": ("tCO2e", 1.0),
    "tonnes co2 eq": ("tCO2e", 1.0),
    "tons co2": ("tCO2e", 1.0),
    "ton co2": ("tCO2e", 1.0),
    "tons of co2": ("tCO2e", 1.0),
    "tonnes of co2": ("tCO2e", 1.0),
    "tons co2e": ("tCO2e", 1.0),
    "metric tonnes co2e": ("tCO2e", 1.0),
    "mt co2e": ("tCO2e", 1.0),  # Indian BRSR: MT = metric tonne, not megatonne
    "mtco2e": ("tCO2e", 1.0),   # Indian BRSR: MT = metric tonne, not megatonne
    "mt co2": ("tCO2e", 1.0),   # Indian BRSR: MT = metric tonne, not megatonne
    "kt co2e": ("tCO2e", 1_000.0),
    "kt co2": ("tCO2e", 1_000.0),
    "ktco2e": ("tCO2e", 1_000.0),
    "kilo tonnes co2e": ("tCO2e", 1_000.0),
    "kilo tonne co2e": ("tCO2e", 1_000.0),
    "kilo tonnes of co2 equivalent": ("tCO2e", 1_000.0),
    "kilo tonne of co2 equivalent": ("tCO2e", 1_000.0),
    "kg co2e": ("tCO2e", 0.001),
    "kgco2e": ("tCO2e", 0.001),
    "kgco2e/t": ("tCO2e/tonne", 0.001),
    "kgco2e/tonne": ("tCO2e/tonne", 0.001),
    "kgco2e/ton": ("tCO2e/tonne", 0.001),
    "tco2e/tonne": ("tCO2e/tonne", 1.0),
    "metric tons of co2 equivalent/metric ton of production": ("tCO2e/tonne", 1.0),
    "tonnes of co2 equivalent/tonne of production": ("tCO2e/tonne", 1.0),
    "tco2e/inr crore": ("tCO2e/MINR", 10.0),
    "tco2e/crore inr": ("tCO2e/MINR", 10.0),
    "metric tons of co2 equivalent/ turnover in crores": ("tCO2e/MINR", 0.1),
    "metric tonnes of co2 equivalent/turnover in crores": ("tCO2e/MINR", 0.1),
    "tonnes of co2 equivalent/crore inr": ("tCO2e/MINR", 0.1),
    "tonnes of co2 equivalent/ million usd": ("tCO2e/MUSD", 1.0),
    "tonnes of co2 equivalent/million usd": ("tCO2e/MUSD", 1.0),
    "metric tons of co2 equivalent / revenue from operations adjusted for ppp": ("tCO2e/MPPP", 1.0),
    "metric tonnes of co2 equivalant/revenue from operations adjusted for ppp": ("tCO2e/MPPP", 1.0),
    "metric tonnes of co2 equivalent/metric tonne of production": ("tCO2e/tonne", 1.0),
    "kgco2e/million inr": ("tCO2e/MINR", 0.001),
    "kgco2e/million nr": ("tCO2e/MINR", 0.001),
    "kgco2e/million usd": ("tCO2e/MUSD", 0.001),
    "inr": ("INR", 1.0),
    "rs": ("INR", 1.0),
    "rs.": ("INR", 1.0),
    "rupees": ("INR", 1.0),
    "inr crore": ("INR", 10_000_000.0),
    "crore": ("INR", 10_000_000.0),
    "crores": ("INR", 10_000_000.0),
    "cr": ("INR", 10_000_000.0),
    "inr lakh": ("INR", 100_000.0),
    "lakh": ("INR", 100_000.0),
    "lakhs": ("INR", 100_000.0),
    "lac": ("count", 100_000.0),
    "lacs": ("count", 100_000.0),
    "million": ("count", 1_000_000.0),
    "mn": ("count", 1_000_000.0),
    "tj": ("GJ", 1_000.0),
    "terra joules": ("GJ", 1_000.0),
    "terra joule": ("GJ", 1_000.0),
    "terajoules": ("GJ", 1_000.0),
    "terajoule": ("GJ", 1_000.0),
    "tj/year": ("GJ", 1_000.0),
    "kg noxe":         ("kg", 1.0),
    "kg sox":          ("kg", 1.0),
    "kgsox":           ("kg", 1.0),
    "kgnox":           ("kg", 1.0),
    "kgnoxe":          ("kg", 1.0),
    "kg so2":          ("kg", 1.0),
    "kg no2":          ("kg", 1.0),
    "kgsoxe":          ("kg", 1.0),
    "kg soxe":         ("kg", 1.0),
    "kgso2e":          ("kg", 1.0),
    "kg so2e":         ("kg", 1.0),
    "kgno2e":          ("kg", 1.0),
    "kg no2e":         ("kg", 1.0),
    "kgpme":           ("kg", 1.0),
    "kg pme":          ("kg", 1.0),
    "metric tons nox": ("tonne", 1.0),
    "metric tons sox": ("tonne", 1.0),
    "tonnes nox":      ("tonne", 1.0),
    "tonnes sox":      ("tonne", 1.0),
    "mw": ("MW", 1.0),
    "mwp": ("MWp", 1.0),
    "60kva": ("kVA", 60.0),
    "kwp": ("kWp", 1.0),
    "kva": ("kVA", 1.0),
    "hectare": ("hectare", 1.0),
    "hectares": ("hectare", 1.0),
    "acre": ("acre", 1.0),
    "acres": ("acre", 1.0),
    "shares": ("count", 1.0),
    "ordinary shares": ("count", 1.0),
    "mt/day": ("tonne/day", 1.0),
    "gj/mt": ("GJ/tonne", 1.0),
    "gj/tonne of production": ("GJ/tonne", 1.0),
    "kiloliters/ton": ("kL/tonne", 1.0),
    "kilolitres/ton": ("kL/tonne", 1.0),
    "kilolitres/tonne of production": ("kL/tonne", 1.0),
    "kiloliters/tonne": ("kL/tonne", 1.0),
    "kilolitres/tonne": ("kL/tonne", 1.0),
    "m3/tonne": ("kL/tonne", 1.0),
    "m3/ton": ("kL/tonne", 1.0),
    "m3 per tonne": ("kL/tonne", 1.0),
    "kiloliters/million inr": ("kL/MINR", 1.0),
    "kilolitres/million inr": ("kL/MINR", 1.0),
    "kilolitres/crore inr": ("kL/MINR", 0.1),
    "kilolitre/crore inr": ("kL/MINR", 0.1),
    "kl/crore inr": ("kL/MINR", 0.1),
    "kl/inr crore": ("kL/MINR", 0.1),
    "kiloliters/million usd": ("kL/MUSD", 1.0),
    "kilolitres/million usd": ("kL/MUSD", 1.0),
    "kilolitres/rupee": ("L/INR", 1000.0),
    "gj/million inr": ("GJ/MINR", 1.0),
    "gj/crore inr": ("GJ/MINR", 0.1),
    "giga joules/crore inr": ("GJ/MINR", 0.1),
    "gj/rupee turnover": ("GJ/INR", 1.0),
    "gj/million usd": ("GJ/MUSD", 1.0),
    "mt/crore inr": ("tonne/MINR", 0.0001),
    "mt/million us": ("tonne/MUSD", 0.001),
    "mt/million usd": ("tonne/MUSD", 0.001),
    "kg/million inr": ("kg/MINR", 1.0),
    "kg/million usd": ("kg/MUSD", 1.0),
    "kg/inr": ("kg/INR", 1.0),
    "kg/ton": ("kg/tonne", 1.0),
    "kg/m2": ("kg/sqm", 1.0),
    "kg of co2 equivalent/m2 built up area": ("kgCO2e/sqm", 1.0),
    "litres/m2 built up area": ("L/sqm", 1.0),
    "mj/m2 built up area": ("MJ/sqm", 1.0),
    "kwh/sq ft": ("kWh/sqft", 1.0),
    "kwh/sqft": ("kWh/sqft", 1.0),
    "gj/sq m": ("GJ/sqm", 1.0),
    "gj/sqm": ("GJ/sqm", 1.0),
    "kwh/ year": ("kWh/year", 1.0),
    "per month": ("count/month", 1.0),
    "per year": ("count/year", 1.0),
    "lakhs per month": ("count/month", 100000.0),
    "fiscal year": ("years", 1.0),
    "states/union territories": ("count", 1.0),
    "consumers": ("count", 1.0),
    "certifications": ("count", 1.0),
    "directors": ("count", 1.0),
    "year olds": ("years", 1.0),
    "locations": ("count", 1.0),
    "location": ("count", 1.0),
    "factories": ("count", 1.0),
    "factory": ("count", 1.0),
    "plants": ("count", 1.0),
    "plant": ("count", 1.0),
    "facilities": ("count", 1.0),
    "facility": ("count", 1.0),
    # BRSR energy reporting format — companies report in GJ
    "joules or multiples": ("GJ", 1.0),
    "mj or multiples": ("GJ", 0.001),
    "gj or multiples": ("GJ", 1.0),
    "gigajoules or multiples": ("GJ", 1.0),
}

COUNT_HINT_RE = re.compile(
    r"\b(count|number of|no\.? of|stores?|outlets?|employees?|workers?|sites?|plants?|"
    r"factories?|facilities?|warehouses?|lines?|beneficiaries?|patents?|suppliers?)\b",
    re.I,
)
RATIO_UNIT_RE = re.compile(r"[/]|per\s+", re.I)
UNIT_TOKEN_RE = re.compile(r"[^a-z0-9%/+]+")
COUNT_UNIT_WORD_RE = re.compile(r"^[a-z ]+$")
SCALE_PREFIXES = {
    "million": 1_000_000.0,
    "mn": 1_000_000.0,
    "lakh": 100_000.0,
    "lakhs": 100_000.0,
    "lac": 100_000.0,
    "lacs": 100_000.0,
    "crore": 10_000_000.0,
    "crores": 10_000_000.0,
    "kilo": 1_000.0,
}


def normalize_unit_key(raw_unit: Any) -> str:
    text = str(raw_unit or "").strip().lower()
    text = text.replace("₹", "inr ")
    text = text.replace("`", "")
    text = text.replace("×", "x")
    text = re.sub(r"\bmetric\s+tons?\b", "metric tonnes", text)
    text = re.sub(r"\bkiloliters?\b", "kilolitres", text)
    text = re.sub(r"\bliters?\b", "litres", text)
    text = re.sub(r"\bhrs?\b", "hours", text)
    text = re.sub(r"\bnos?\b", "nos", text)
    text = UNIT_TOKEN_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def infer_unit_mapping(raw_unit: Any, raw_name: Any = "", source_sentence: Any = "") -> tuple[str, float, str]:
    normalized = normalize_unit_key(raw_unit)
    if not normalized and str(raw_unit or "").strip() == "":
        context = " ".join(str(value or "") for value in (raw_name, source_sentence))
        if COUNT_HINT_RE.search(context):
            return "count", 1.0, "inferred"
        return "", 1.0, "needs_context"
    if normalized in UNIT_MAP:
        symbol, factor = UNIT_MAP[normalized]
        return symbol, factor, "exact"

    compact = normalized.replace(" ", "")
    if compact in UNIT_MAP:
        symbol, factor = UNIT_MAP[compact]
        return symbol, factor, "inferred"

    compound = _scaled_compound_mapping(normalized)
    if compound is not None:
        return compound[0], compound[1], "inferred"

    if normalized.endswith(" per tonne"):
        prefix = normalized[: -len(" per tonne")].strip()
        if prefix in UNIT_MAP:
            base_symbol, _factor = UNIT_MAP[prefix]
            # Do not apply scale factor — intensity ratios stay at reported scale
            return f"{base_symbol}/tonne", 1.0, "inferred"
    if normalized.endswith("/tonne"):
        prefix = normalized[: -len("/tonne")].strip()
        if prefix in UNIT_MAP:
            base_symbol, _factor = UNIT_MAP[prefix]
            return f"{base_symbol}/tonne", 1.0, "inferred"

    context = " ".join(str(value or "") for value in (raw_unit, raw_name, source_sentence))
    if "%" in context or re.search(r"\b(percent|percentage)\b", context, re.I):
        return "%", 1.0, "inferred"
    if re.search(r"\b(bps|basis points?)\b", context, re.I):
        return "%", 0.01, "inferred"
    if not normalized and COUNT_HINT_RE.search(context):
        return "count", 1.0, "inferred"
    if normalized and COUNT_UNIT_WORD_RE.fullmatch(normalized) and not RATIO_UNIT_RE.search(normalized):
        return "count", 1.0, "inferred"
    if normalized.startswith("kgco2e/") and "million inr" in normalized:
        return "tCO2e/MINR", 0.001, "inferred"
    if normalized.startswith("kgco2e/") and "million nr" in normalized:
        return "tCO2e/MINR", 0.001, "inferred"
    if normalized.startswith("kgco2e/") and "million usd" in normalized:
        return "tCO2e/MUSD", 0.001, "inferred"
    if "revenue from operations adjusted for ppp" in normalized:
        if "co2" in normalized:
            return "tCO2e/MPPP", 1.0, "inferred"
        return "GJ/MPPP", 1.0, "inferred"
    return str(raw_unit or ""), 1.0, "failed"


def validate_and_merge(
    llm_unit: str,
    llm_confidence: str,
    raw_unit: str,
    raw_name: str = "",
    source_sentence: str = "",
) -> tuple[str, float, str]:
    """
    Use LLM-provided normalised_unit_symbol as primary signal; fall back to
    dictionary when LLM confidence is 'failed'. Returns (symbol, factor, confidence).

    Priority:
      1. If llm_confidence == 'failed': fall back to dictionary via infer_unit_mapping.
      2. If dictionary has an entry that disagrees with LLM: trust LLM, tag 'llm_override'.
      3. Otherwise: return LLM result.
    """
    if not llm_unit or llm_confidence == "failed":
        return infer_unit_mapping(raw_unit, raw_name, source_sentence)

    dict_symbol, dict_factor, _dict_conf = infer_unit_mapping(raw_unit, raw_name, source_sentence)

    if dict_symbol and dict_symbol != llm_unit and _dict_conf != "failed":
        # Disagreement — trust LLM but record that the dictionary disagreed
        return llm_unit, 1.0, "llm_override"

    return llm_unit, 1.0, llm_confidence


def _scaled_compound_mapping(normalized_unit: str) -> tuple[str, float] | None:
    parts = normalized_unit.split()
    if not parts:
        return None
    prefix = parts[0]
    remainder = " ".join(parts[1:]).strip()
    if prefix not in SCALE_PREFIXES or not remainder:
        return None
    if remainder in UNIT_MAP:
        symbol, factor = UNIT_MAP[remainder]
        return symbol, factor * SCALE_PREFIXES[prefix]
    if remainder.endswith(" of co2 equivalent"):
        return "tCO2e", SCALE_PREFIXES[prefix]
    if remainder in {
        "people",
        "households",
        "farmers",
        "women farmers",
        "outlets",
        "units",
        "acres",
        "litres",
        "kilo litres",
        "kilolitres",
        "tonnes",
    }:
        base_symbol, base_factor, _ = infer_unit_mapping(remainder, "", "")
        if base_symbol:
            return base_symbol, base_factor * SCALE_PREFIXES[prefix]
    return None


def normalise_fact_value(fact: dict[str, Any]) -> dict[str, Any]:
    raw = fact.get("raw") if isinstance(fact.get("raw"), dict) else {}
    raw_value = raw.get("raw_value", fact.get("value"))
    raw_unit = raw.get("raw_unit", fact.get("unit", ""))
    raw_name = raw.get("raw_name", fact.get("metric", ""))
    source_sentence = raw.get("source_sentence", fact.get("evidence", ""))

    numeric_value, _ = extract_primary_numeric(raw_value, source_sentence)
    symbol, factor, confidence = infer_unit_mapping(raw_unit, raw_name, source_sentence)

    normalised_value = None
    if numeric_value is not None and confidence in {"exact", "inferred"}:
        normalised_value = numeric_value * factor
    if "%" == symbol and numeric_value is not None and confidence in {"exact", "inferred"}:
        normalised_value = numeric_value

    final_confidence = confidence
    if confidence == "failed":
        normalised_value = None
    elif confidence == "needs_context":
        normalised_value = None
    elif numeric_value is None and confidence in {"exact", "inferred"}:
        normalised_value = None
        final_confidence = "needs_context"

    return {
        "raw_value": raw_value,
        "raw_unit": raw_unit,
        "normalised_value": normalised_value,
        "normalised_unit_symbol": symbol,
        "normalisation_confidence": final_confidence,
    }


def _iter_facts(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        return [fact for fact in payload.get("facts", []) if isinstance(fact, dict)]
    if isinstance(payload, list):
        return [fact for fact in payload if isinstance(fact, dict)]
    return []


def _default_input_paths(workdir: Path) -> list[Path]:
    candidates = [
        workdir / "workspace_test_outputs" / "tata_consumer_pass1_edc.json",
        workdir / "workspace_test_outputs" / "gcpl_pass1_edc.json",
        workdir / "workspace_test_outputs" / "nestle_india_pass1_edc.json",
        workdir / "workspace_test_outputs" / "itc_pass1_edc.json",
    ]
    return [path for path in candidates if path.exists()]


def build_report(input_paths: list[Path]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_facts": 0,
        "success_count": 0,
        "failed_count": 0,
        "inferred_count": 0,
        "needs_context_count": 0,
        "per_file": [],
        "failed_unit_strings": [],
    }
    failed_units: Counter[str] = Counter()

    for path in input_paths:
        file_total = 0
        file_success = 0
        file_failed = 0
        file_inferred = 0
        file_needs_context = 0
        for fact in _iter_facts(path):
            file_total += 1
            result = normalise_fact_value(fact)
            confidence = result["normalisation_confidence"]
            if confidence == "failed":
                file_failed += 1
                failed_units[str(result["raw_unit"] or "")] += 1
            elif confidence == "needs_context":
                file_needs_context += 1
            else:
                file_success += 1
                if confidence == "inferred":
                    file_inferred += 1
        summary["per_file"].append(
            {
                "file": str(path),
                "total_facts": file_total,
                "success_count": file_success,
                "failed_count": file_failed,
                "inferred_count": file_inferred,
                "needs_context_count": file_needs_context,
            }
        )
        summary["total_facts"] += file_total
        summary["success_count"] += file_success
        summary["failed_count"] += file_failed
        summary["inferred_count"] += file_inferred
        summary["needs_context_count"] += file_needs_context

    summary["failed_unit_strings"] = [
        {"raw_unit": unit, "count": count}
        for unit, count in sorted(failed_units.items(), key=lambda item: (-item[1], item[0]))
    ]
    return summary


def write_failed_units_csv(report: dict[str, Any], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["raw_unit", "count"])
        writer.writeheader()
        for row in report.get("failed_unit_strings", []):
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalise raw units across Pass 1 outputs.")
    parser.add_argument("--inputs", nargs="*", help="Pass 1 JSON files to scan.")
    parser.add_argument(
        "--report",
        default="unit_normalisation_report.json",
        help="Path for the JSON summary report.",
    )
    parser.add_argument(
        "--failed-units-csv",
        default="unit_normalisation_failed_units.csv",
        help="Path for the unmatched unit CSV.",
    )
    args = parser.parse_args()

    workdir = Path.cwd()
    input_paths = [Path(path) for path in args.inputs] if args.inputs else _default_input_paths(workdir)
    if not input_paths:
        raise SystemExit("No input Pass 1 files found for unit normalization.")

    report = build_report(input_paths)
    report_path = Path(args.report)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_failed_units_csv(report, Path(args.failed_units_csv))

    print(f"unit normalization total facts: {report['total_facts']}")
    print(f"unit normalization success count: {report['success_count']}")
    print(f"unit normalization inferred count: {report['inferred_count']}")
    print(f"unit normalization needs_context count: {report['needs_context_count']}")
    print(f"unit normalization failed count: {report['failed_count']}")
    print("failed unit strings:")
    for row in report["failed_unit_strings"]:
        print(f"- {row['raw_unit']!r}: {row['count']}")


if __name__ == "__main__":
    main()
