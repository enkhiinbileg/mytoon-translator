import numpy as np
from typing import Any
from .base import TraditionalTranslation
from ..utils.textblock import TextBlock

class NoneTranslation(TraditionalTranslation):
    """Translation engine that skips translation and keeps original text."""
    
    def initialize(self, settings: Any, source_lang: str, target_lang: str, **kwargs) -> None:
        pass

    def translate(self, blk_list: list[TextBlock]) -> list[TextBlock]:
        for blk in blk_list:
            # Populate translation with the original text (raw text bypass)
            blk.translation = blk.text
        return blk_list
