from app.features.historical_l2 import OrderBookReplayEngine
from app.features.microstructure import BookState


def test_replay_engine_applies_binance_depth_arrays_in_update_order():
    book = BookState({100.0: 2.0}, {101.0: 3.0}, 10)
    replay = OrderBookReplayEngine(book)
    replay.apply_chunk([
        {"event_time": "2025-01-01T00:00:00Z", "final_update_id": 11,
         "bids": [[100, 0], [99, 4]], "asks": [[101, 5]]},
        {"event_time": "2025-01-01T00:00:01Z", "final_update_id": 12,
         "bids": [[99, 6]], "asks": [[102, 2]]},
    ])
    assert book.last_update_id == 12
    assert book.bids == {99.0: 6.0}
    assert book.asks == {101.0: 5.0, 102.0: 2.0}
