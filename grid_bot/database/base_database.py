# grid_bot/database/base_repo.py
import os
from dotenv import load_dotenv
from typing import Any, Dict
from mysql.connector import pooling

load_dotenv()  # reads .env file from current or parent dir

class BaseMySQLRepo:
    """
    Base class providing pooled MySQL connections with config from .env
    """
    _pool = None

    def __init__(self, **db_kwargs):
        # Load defaults from .env
        env_config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", ""),
            "database": os.getenv("DB_NAME", "grid_bot"),
            "port": int(os.getenv("DB_PORT", 3306)),
        }

        # Allow kwargs override (for tests or dynamic config)
        env_config.update(db_kwargs)
        self.config = env_config

        # Initialize connection pool once (shared)
        if not BaseMySQLRepo._pool:
            BaseMySQLRepo._pool = pooling.MySQLConnectionPool(
                pool_name="gridbot_pool",
                pool_size=int(os.getenv("DB_POOL_SIZE", 5)),
                pool_reset_session=True,
                **self.config
            )

    def _get_conn(self):
        """ Get pooled connection """
        return BaseMySQLRepo._pool.get_connection()
