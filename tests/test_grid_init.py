import unittest

from grid_bot.strategy import Strategy as strategy

class TestGridInit(unittest.TestCase):
    
    def setUp(self):
        # Setup code before each test method
        self.strategy = strategy(
            symbol='None',
            atr_period=14,
            atr_mean_window=100        
        )
        self.spacing_size = 0.5
        self.grid_levels = 5
        self.center_price = 2000.0

    def tearDown(self):
        self.strategy.grid_db.delete_all_states()
        pass

    def test_grid_init_normal(self):

        grid_id = self.strategy.initialize_grid(
            symbol="None",
            base_price=self.center_price,
            spacing=self.spacing_size,
            levels=self.grid_levels
        )
        # An example test case
        self.assertTrue(grid_id is not None)