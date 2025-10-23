import unittest


class TestOnCandle(unittest.TestCase):

    def test_on_candle_calls_process_tick(self, mocker, strategy_instance):
        # Arrange
        mock_process_tick = mocker.patch.object(strategy_instance, '_process_tick')
        timestamp = 1622548800000  # Example timestamp
        open_price = 100.0
        high_price = 110.0
        low_price = 90.0
        close_price = 105.0
        volume = 1000.0

        # Act
        strategy_instance.on_candle(timestamp, open_price, high_price, low_price, close_price, volume)

        # Assert
        mock_process_tick.assert_called_once()
        called_arg = mock_process_tick.call_args[0][0]
        assert called_arg['timestamp'] == timestamp
        assert called_arg['Close'] == close_price