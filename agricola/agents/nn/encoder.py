"""Input-vector encoder for the first NN value function.

This module will host `encode_state(state, player_idx) -> torch.Tensor`
(the input-vector encoder for the NN value function) once the
architecture is locked in.

Today it contains only the version constant, which other code refers to
when stamping model checkpoints.

`ENCODING_VERSION` guards the encoder's output schema — the
input-vector shape and feature ordering baked into a trained model's
first layer. Bump whenever `encode_state(state)` would produce a
different output for the same input state: adding features, removing
features, reordering, changing normalization parameters, changing the
semantics of any existing feature. Pure refactors that preserve
numerical output do not bump. See FIRST_NN.md §10.4 for the full
bump policy.

This module has no PyTorch dependency yet — when the encoder lands,
PyTorch will be imported here but not in the rest of the NN package
that doesn't need it.
"""

from __future__ import annotations

ENCODING_VERSION: int = 1
"""Input-vector schema version. Stamped into model metadata sidecars
at training time. The encoder itself (`encode_state`) is not yet
implemented; see FIRST_NN.md §4 for the input-vector specification."""
