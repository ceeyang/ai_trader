"""
定投策略单元测试
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.ai_trader.strategies.dca.dca_strategy import DCAStrategy


class TestDCAStrategy:
    """定投策略测试类"""
    
    def setup_method(self):
        """测试前准备"""
        self.symbol = "BTCUSDT"
        self.invest_amount = 200.0
        self.invest_day = 10
        self.start_date = datetime(2024, 1, 1)
        self.end_date = datetime(2024, 12, 31)
        
        self.strategy = DCAStrategy(
            symbol=self.symbol,
            invest_amount=self.invest_amount,
            invest_day=self.invest_day,
            start_date=self.start_date,
            end_date=self.end_date
        )
    
    def test_initialization(self):
        """测试初始化"""
        assert self.strategy.symbol == self.symbol
        assert self.strategy.invest_amount == self.invest_amount
        assert self.strategy.invest_day == self.invest_day
        assert self.strategy.start_date == self.start_date
        assert self.strategy.end_date == self.end_date
        assert self.strategy.name == f"DCA_{self.symbol}"
    
    def test_calculate_position_size(self):
        """测试仓位大小计算"""
        signal = {"action": "buy", "price": 50000.0}
        position_size = self.strategy.calculate_position_size(signal, 50000.0)
        
        expected_size = self.invest_amount / 50000.0
        assert position_size == expected_size
    
    @patch('src.ai_trader.strategies.dca.dca_strategy.BinanceDataSource')
    def test_execute_dca_success(self, mock_data_source_class):
        """测试定投执行成功"""
        # 模拟数据源
        mock_data_source = Mock()
        mock_data_source.connect.return_value = True
        mock_data_source.get_current_price.return_value = 60000.0
        mock_data_source.get_dca_investment_dates.return_value = [
            {
                'date': '2024-01-10',
                'datetime': datetime(2024, 1, 10),
                'close': 50000.0
            },
            {
                'date': '2024-02-10',
                'datetime': datetime(2024, 2, 10),
                'close': 55000.0
            }
        ]
        mock_data_source_class.return_value = mock_data_source
        
        # 执行定投
        result = self.strategy.execute_dca()
        
        # 验证结果
        assert result['symbol'] == self.symbol
        assert result['total_invested'] == 400.0  # 2次投资
        assert result['total_coins'] == (200.0/50000.0 + 200.0/55000.0)
        assert result['current_price'] == 60000.0
        assert result['investment_count'] == 2
        assert len(result['records']) == 2
    
    @patch('src.ai_trader.strategies.dca.dca_strategy.BinanceDataSource')
    def test_execute_dca_connection_failure(self, mock_data_source_class):
        """测试定投执行连接失败"""
        # 模拟数据源连接失败
        mock_data_source = Mock()
        mock_data_source.connect.return_value = False
        mock_data_source_class.return_value = mock_data_source
        
        # 执行定投应该抛出异常
        with pytest.raises(ConnectionError):
            self.strategy.execute_dca()
    
    def test_get_investment_summary(self):
        """测试获取投资摘要"""
        summary = self.strategy.get_investment_summary()
        
        assert summary['strategy_name'] == f"DCA_{self.symbol}"
        assert summary['symbol'] == self.symbol
        assert summary['invest_amount'] == self.invest_amount
        assert summary['invest_day'] == self.invest_day
        assert summary['start_date'] == self.start_date.strftime('%Y-%m-%d')
        assert summary['end_date'] == self.end_date.strftime('%Y-%m-%d')
