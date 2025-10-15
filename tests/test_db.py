import os
import sqlite3
import tempfile
import unittest
from database.grid_states_db import GridStateDB

class TestGridStateDB(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(self.db_fd)
        self.db = GridStateDB(self.db_path)

    def tearDown(self):
        os.remove(self.db_path)

    def test_save_and_load_state(self):
        self.assertEqual(self.db.load_state(), {})
        state = {1.0: False, 2.5: True}
        self.db.save_state(state)
        self.assertEqual(self.db.load_state(), state)

if __name__ == '__main__':
    unittest.main()