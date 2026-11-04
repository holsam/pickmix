'''
pickmix: picks paired with their current fits, flagged when a parent is missing
'''

# Import internal pickmix objects
from pickmix.estimate.registry import Fit
from pickmix.estimates import EstimateService
from pickmix.export import Item
from pickmix.geometry import Parent, match_parents
from pickmix.model import Pick, Session

# matched: parent geometry for every pick of a kind, empty for a kind with no parent
def matched(session: Session, service: EstimateService, kind: str) -> dict[int, Parent]:
    return match_parents(kind, session.project.config, session.store, service.store, session.project.tomos)

# flagged: the fit with noparent added to its flags when the pick's kind has a parent and the pick found none
def flagged(session: Session, kind: str, pick: Pick, fit: Fit, parents: dict[int, Parent]) -> Fit:
    if session.project.config.kinds[kind].parent is None or pick.id in parents:
        return fit
    return fit.model_copy(update={'flag': ','.join(filter(None, [fit.flag, 'noparent']))})

# items: picks of a kind that have a current fit, each fit flagged where its parent is missing
def items(session: Session, service: EstimateService, kind: str) -> list[Item]:
    parents = matched(session, service, kind)
    out = []
    for pick in session.store.all(kind):
        fit = service.store.get(pick)
        if fit is not None:
            out.append((pick, flagged(session, kind, pick, fit, parents)))
    return out
