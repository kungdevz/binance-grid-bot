from typing import Dict, Any
from grid_bot.database.account_balance_repo import AccountBalanceRepo


class AccountBalance(AccountBalanceRepo):
    """Production repo that saves via GridStateDB."""
    def __init__(self, db_path: str):
        self._db = AccountBalanceRepo(db_path=db_path)

    def save(self, items: Dict[str, Any]) -> None:
        self._db.insert_balance(items)