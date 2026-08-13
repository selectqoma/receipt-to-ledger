from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any, Iterable

from .evaluation import EvaluationCase


def _cord_money(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    sign = -1 if text.startswith("-") else 1
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    return sign * int(digits) / 1.0


def _cord_quantity(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def cord_ground_truth_to_canonical(raw: dict[str, Any]) -> dict[str, Any]:
    gt = raw.get("gt_parse", raw)
    sub_total = gt.get("sub_total") or gt.get("subtotal") or {}
    total = gt.get("total") or {}
    menu = gt.get("menu") or []
    if isinstance(menu, dict):
        menu = [menu]

    lines: list[dict[str, Any]] = []
    for item in menu:
        if not isinstance(item, dict):
            continue
        description = item.get("nm")
        if not description:
            continue
        line: dict[str, Any] = {"description": str(description)}
        if item.get("cnt") is not None:
            line["quantity"] = _cord_quantity(item.get("cnt"))
        if item.get("unitprice") is not None:
            line["unit_price"] = _cord_money(item.get("unitprice"))
        if item.get("price") is not None:
            line["total"] = _cord_money(item.get("price"))
        lines.append(line)

    amounts: dict[str, Any] = {}
    if "subtotal_price" in sub_total:
        amounts["subtotal"] = _cord_money(sub_total.get("subtotal_price"))
    if "tax_price" in sub_total:
        amounts["tax"] = _cord_money(sub_total.get("tax_price"))
    if "total_price" in total:
        amounts["total"] = _cord_money(total.get("total_price"))

    return {
        "document_type": "receipt",
        "amounts": amounts,
        "lines": lines,
    }


def load_cord_cases(
    *,
    split: str = "validation",
    limit: int | None = None,
) -> Iterable[EvaluationCase]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError(
            'CORD evaluation requires the eval extras: pip install -e ".[eval]"'
        ) from exc

    dataset = load_dataset("naver-clova-ix/cord-v2", split=split, streaming=True)
    count = 0
    for row in dataset:
        if limit is not None and count >= limit:
            break
        image = row["image"]
        raw = json.loads(row["ground_truth"])
        meta = raw.get("meta") or {}
        image_id = meta.get("image_id", count)

        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=95)
        yield EvaluationCase(
            case_id=f"cord-{split}-{image_id}",
            payload=buffer.getvalue(),
            content_type="image/jpeg",
            ground_truth=cord_ground_truth_to_canonical(raw),
        )
        count += 1
