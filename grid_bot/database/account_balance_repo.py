from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod

class AccountBalanceRepo(ABC):
    @abstractmethod
    def insert_balance(self, data: Dict[str, Any]) -> int: 
        """
        Insert balance data into storage (DB, API, etc.)
        :param data: dictionary containing balance info
        :return: integer (e.g. new record ID or affected row count)
        """
        pass