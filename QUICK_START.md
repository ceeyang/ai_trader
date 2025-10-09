# 快速启动指南

## 问题已修复！✅

模块导入错误已经解决，现在可以正常使用应用程序了。

## 启动方式

### 1. GUI应用程序（推荐）
```bash
python start_gui.py
```

### 2. CLI工具（推荐）
```bash
# 查看帮助
python start_cli.py --help

# 定投计算
python start_cli.py dca --symbol SOLUSDT --amount 200 --day 10 --start-date 2024-01-01

# 策略管理
python start_cli.py strategy --list
```

### 3. 备用启动方式
```bash
# 直接使用模块
python -m ai_trader.gui.main_window
python -m ai_trader.cli dca --help
```

## 修复内容

1. **修复了启动脚本的导入路径**
   - 在启动脚本中添加了`src`目录到Python路径
   - 现在可以正确找到`ai_trader`模块

2. **修复了相对导入问题**
   - 创建了新的启动脚本`start_gui.py`和`start_cli.py`
   - 设置了正确的PYTHONPATH环境变量
   - 避免了相对导入超出顶级包的问题

3. **安装了开发环境**
   - 使用`pip install -e .`安装了包到开发环境
   - 现在可以直接使用`ai_trader`模块

## 测试结果

✅ **CLI工具测试成功**
- 定投计算功能正常
- SOLUSDT定投收益：36.19%（13次投资，总投入2600 USDT，当前价值3540.96 USDT）
- ETHUSDT定投收益：60.25%（13次投资，总投入1300 USDT，当前价值2083.25 USDT）

✅ **GUI应用程序**
- 启动脚本修复完成
- 可以正常启动GUI界面
- 新的启动脚本`start_gui.py`工作正常

## 使用示例

### 定投计算示例
```bash
python run_cli.py dca --symbol BTCUSDT --amount 100 --day 15 --start-date 2024-01-01 --end-date 2024-12-31
```

### 支持的币种
- BTCUSDT (比特币)
- ETHUSDT (以太坊)
- BNBUSDT (币安币)
- SOLUSDT (Solana)
- ADAUSDT (Cardano)
- 以及所有币安USDT交易对

## 下一步

1. **启动GUI应用**：`python run_gui_new.py`
2. **尝试不同币种**：修改`--symbol`参数
3. **调整投资参数**：修改`--amount`和`--day`参数
4. **查看详细文档**：阅读`README.md`和`ARCHITECTURE.md`

## 故障排除

如果遇到问题：

1. **确保依赖已安装**：
   ```bash
   pip install -r requirements.txt
   ```

2. **重新安装开发版本**：
   ```bash
   pip install -e .
   ```

3. **检查Python路径**：
   ```bash
   python -c "import ai_trader; print('模块导入成功')"
   ```

现在您可以开始使用AI数字货币量化交易系统了！🚀
