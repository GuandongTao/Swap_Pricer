from .base import CurveLoader, FixingLoader, TradeDef, TradeLoader
from .csv_trades import CsvTradeLoader
from .excel import ExcelCurveLoader, ExcelFixingLoader
from .yaml_trades import YamlTradeLoader

__all__ = [
    "CurveLoader",
    "FixingLoader",
    "TradeLoader",
    "TradeDef",
    "ExcelCurveLoader",
    "ExcelFixingLoader",
    "YamlTradeLoader",
    "CsvTradeLoader",
    "CombinedTradeLoader",
]


class CombinedTradeLoader(TradeLoader):
    """Concatenate trades from multiple TradeLoader sources (e.g. YAML + CSV)."""

    def __init__(self, *loaders: TradeLoader) -> None:
        self._loaders = loaders

    def load_all(self) -> list[TradeDef]:
        """Return all trades from every loader, raising on duplicate ``trade_id``."""
        seen: dict[str, TradeDef] = {}
        for l in self._loaders:
            for t in l.load_all():
                if t.trade_id in seen:
                    raise ValueError(f"Duplicate trade_id {t.trade_id!r} across loaders")
                seen[t.trade_id] = t
        return list(seen.values())

    def load(self, trade_id: str) -> TradeDef:
        """Return the single trade matching ``trade_id`` across all loaders. Raises ``KeyError`` if absent."""
        for t in self.load_all():
            if t.trade_id == trade_id:
                return t
        raise KeyError(f"Trade {trade_id!r} not found")
