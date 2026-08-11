from dataclasses import dataclass
from collections.abc import Callable, Mapping

@dataclass(frozen=True, slots=True)
class ParamSchema:
    required: frozenset[str]
    optional: frozenset[str]
    validators: Mapping[str, Callable[[object], None]] = None  # type: ignore[assignment]

    @property
    def known(self) -> frozenset[str]:
        return self.required | self.optional