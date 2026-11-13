"""Deterministic single-identity numbering for shared competency graphs."""

from collections import deque
from collections.abc import Sequence

from app.models.curricula import Competency


def alphabetic(index: int, *, uppercase: bool = False) -> str:
    """Return a one-based alphabetic index, continuing after Z with AA."""
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("a") + remainder) + result
    return result.upper() if uppercase else result


def competency_codes(
    nodes: Sequence[Competency], edges: Sequence[tuple[int, int]]
) -> tuple[dict[int, str], list[int]]:
    """Assign one code per node using the first shortest path in stable sibling order.

    Parameters
    ----------
    nodes
        Subject-scoped competencies, ordered by position and identity.
    edges
        Existing acyclic parent-child relationships.

    Returns
    -------
    tuple[dict[int, str], list[int]]
        Derived codes and node identities in natural hierarchical code order.
    """
    order = {node.id: (node.position, node.id) for node in nodes}
    children: dict[int, list[int]] = {}
    parented = set()
    for parent, child in edges:
        children.setdefault(parent, []).append(child)
        parented.add(child)
    roots = sorted((node.id for node in nodes if node.id not in parented), key=order.__getitem__)
    codes = {identifier: alphabetic(i, uppercase=True) for i, identifier in enumerate(roots, 1)}
    paths = {identifier: (i,) for i, identifier in enumerate(roots, 1)}
    queue = deque(roots)
    while queue:
        parent = queue.popleft()
        index = 0
        for child in sorted(children.get(parent, []), key=order.__getitem__):
            if child in codes:
                continue
            index += 1
            depth = len(paths[parent])
            segment = str(index) if depth % 2 else alphabetic(index)
            codes[child] = f"{codes[parent]}.{segment}"
            paths[child] = (*paths[parent], index)
            queue.append(child)
    return codes, sorted(codes, key=paths.__getitem__)
