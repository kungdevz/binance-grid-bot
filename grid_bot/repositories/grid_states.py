from grid_bot.database import grid_states_repo
from grid_bot.database.grid_states_repo import GridStateRepository


class GridState(grid_states_repo):
    """Production repo that saves grid state data to a database."""
    def __init__(self, db_path: str):
        self._db = GridStateRepository(db_path=db_path)

    def loadDataWithflgs(self, use_flgs : str = 'Y') -> list[dict]:
        return self._db.load_state_with_use_flgs(use_flgs=use_flgs)
    
     