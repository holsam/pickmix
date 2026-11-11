'''
pickmix: run kind validation over the picks of a kind
'''

# Import external dependencies
import numpy as np
from collections.abc import Callable
from dataclasses import dataclass

# Import internal pickmix objects
from pickmix.average import box_images
from pickmix.estimates import EstimateService
from pickmix.items import items
from pickmix.model import Session
from pickmix.validation import low_scores, score_images

# ValidationSummary: what validating one kind found; skipped picks had no current fit to cut a box at
@dataclass(frozen=True)
class ValidationSummary:
    kind: str
    scored: int
    flagged: int
    skipped: int
    median: float

# validate_kind: score the picks of a kind that have a current fit against the average of the kind, store the scores and which are low; ValueError if the kind has too few picks, or picks of more than one pixel size
def validate_kind(name: str, session: Session, service: EstimateService, *, log: Callable[[str], None] = lambda _: None) -> ValidationSummary:
    config = session.project.config
    got = items(session, service, name)
    pairs, _ = box_images(name, config.kinds[name], got, session.project.tomos, config, log=log)
    try:
        scores = score_images(np.stack([img for _, img in pairs]), config.validation)
    except ValueError as e:
        raise ValueError(f'kind {name!r}: {e}') from None
    low = low_scores(scores, config.validation)
    service.validation.put_kind(name, [(p, float(s), bool(flag)) for (p, _), s, flag in zip(pairs, scores, low, strict=True)])
    return ValidationSummary(name, len(pairs), int(low.sum()), session.store.total(name) - len(pairs), float(np.median(scores)))
