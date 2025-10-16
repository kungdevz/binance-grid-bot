from typing import Dict, Any
from grid_bot.database.account_balance_repo import AccountBalanceRepository

class AccountBalance(AccountBalanceRepository):
    """Production repo that saves account balance data to a database."""
    def __init__(self, db_path: str):
        self._db = AccountBalanceRepository(db_path=db_path)

    def save(self, items: Dict[str, Any]) -> None:
        self._db.insert_balance(items)