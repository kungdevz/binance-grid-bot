
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class GridStateRepository(ABC):
    @abstractmethod
    def load_state_with_use_flgs(self, use_flgs : str = 'Y') -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def save_state(self, entry: dict) -> int:
        pass

    @abstractmethod
    def mark_filled(self, price: float) -> int:
        pass

    @abstractmethod
    def mark_open(self, price: float) -> int:
        pass

    @abstractmethod
    def cancel_all_open(self) -> int:
        pass