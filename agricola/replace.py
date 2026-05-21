"""Performance helper for frozen-dataclass field updates.

`fast_replace(obj, **changes)` is a drop-in faster equivalent of stdlib
`dataclasses.replace(obj, **changes)`. It skips per-call type checks, Field
descriptor iteration, the no-non-init-in-changes guard, and **kwargs
unpacking — by caching each class's init-field tuple at first use and
constructing the new instance positionally.

Expected speedup vs stdlib `dataclasses.replace`: ~2-3x for our typical
small-arity frozen dataclasses.

Limitations:
- `obj` must be a dataclass instance with all init=True fields. Every
  dataclass in the engine satisfies this today.
- Unknown field names in `changes` are silently ignored rather than
  raising (stdlib raises TypeError on the constructor). The 622-test
  suite catches any real-world miss; do not rely on `fast_replace` to
  validate field-name typos.

See CHANGES.md ("fast_replace") for the rationale.
"""
from __future__ import annotations

import dataclasses as _dc

_FIELDS_CACHE: dict[type, tuple[str, ...]] = {}


def fast_replace(obj, /, **changes):
    """Return a new instance of `type(obj)` with the given field changes.

    Behaviorally equivalent to `dataclasses.replace(obj, **changes)` for
    every dataclass shape used in the engine.

    Note on field discovery: we use `dataclasses.fields(cls)` rather than
    `cls.__dataclass_fields__` directly because the latter includes
    ClassVar entries (a CPython implementation detail). `dataclasses.fields()`
    is the canonical filter. The result is cached per class so the cost
    is paid once per class.
    """
    cls = type(obj)
    fields = _FIELDS_CACHE.get(cls)
    if fields is None:
        fields = tuple(f.name for f in _dc.fields(cls) if f.init)
        _FIELDS_CACHE[cls] = fields
    return cls(*(changes.get(f, getattr(obj, f)) for f in fields))
