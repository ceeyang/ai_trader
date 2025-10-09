"""
系统配置管理

基于YAML的配置管理系统。
"""

import yaml
import os
from typing import Dict, Any, Optional
from pathlib import Path


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file: Optional[str] = None) -> None:
        """
        初始化配置管理器
        
        Args:
            config_file: 配置文件路径
        """
        if config_file is None:
            config_file = os.path.join(os.path.dirname(__file__), 'settings.yaml')
        
        self.config_file = config_file
        self.config: Dict[str, Any] = {}
        self.load_config()
    
    def load_config(self) -> None:
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = yaml.safe_load(f) or {}
            else:
                self.config = self._get_default_config()
                self.save_config()
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            self.config = self._get_default_config()
    
    def save_config(self) -> None:
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            print(f"保存配置文件失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键，支持点号分隔的嵌套键
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """
        设置配置值
        
        Args:
            key: 配置键，支持点号分隔的嵌套键
            value: 配置值
        """
        keys = key.split('.')
        config = self.config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'app': {
                'name': 'AI Trader',
                'version': '0.1.0',
                'debug': False,
            },
            'data_sources': {
                'binance': {
                    'base_url': 'https://api.binance.com/api/v3',
                    'timeout': 10,
                    'rate_limit_delay': 0.1,
                },
            },
            'trading': {
                'default_currency': 'USDT',
                'min_order_amount': 10.0,
                'max_order_amount': 10000.0,
            },
            'gui': {
                'window_size': [800, 600],
                'theme': 'default',
            },
            'logging': {
                'level': 'INFO',
                'file': 'logs/ai_trader.log',
                'max_size': '10MB',
                'backup_count': 5,
            },
        }


# 全局配置实例
config = ConfigManager()
