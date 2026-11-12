# A股量化个人研究台 V1.3

个人研究用途；**非证券投资建议，不连接券商账户，不执行真实交易**。

## 当前内容
- 手机 PWA：每日筛选、个股分析、自选股、模拟持仓、单股模拟回测。
- 自选股和模拟持仓仅使用当前设备浏览器 `localStorage`，不上传仓库，清理浏览器数据会丢失，请自行备份。
- V1.3 短线信号：收盘后筛选次日买入观察（MA5/MA10趋势、5日均量1.2倍、RSI14 45–68、接近前20日高点、ATR波动率<=6%）；信号仅下一交易日有效。
- 本机模拟持仓显示卖出观察：成本价±ATR止盈止损、MA5/MA10趋势转弱、3个交易日时间退出；录入买入日期后检查A股T+1限制。
- V1.3回测按同一套买卖规则模拟，固定100股、次日开盘在观察区间内才入场，含佣金、印花税和滑点假设。
- `data/screen.json` 是盘后研究结果，不是实时买卖建议。
- `quote-feed` 分支提供最近一次盘中行情快照，采集时间不等于交易所逐笔报价。
- 页面会明确显示行情日期和数据过期提醒，无真实数据时显示「未初始化」，**不会伪造任何实时价格或选股结果**。

## 启用 GitHub Pages
1. 打开仓库 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**。
2. 打开 **Actions → AShare source tests and GitHub Pages → Run workflow**，并确认所有检查成功。
   - 也可以通过 `main` 分支的新提交触发部署；GitHub Pages 刚启用后，之前失败的工作流**不会自动变为成功**。
3. 网址：`https://gritechomepm-art.github.io/ashare-quant-personal/`，成功发布后才能访问。
4. **Actions → AShare daily EOD screening → Run workflow**：北京时间交易日收盘15:15以后才能运行。首次分批收集历史K线，每次最多300只；覆盖不足会明确标注。
5. **AShare best-effort intraday snapshots** 仅在A股工作日交易时段自动尝试更新，计划约5分钟一次，但 GitHub 调度和免费行情源可能延迟、被限流或失败。

## GitHub 工作流
- `.github/workflows/site.yml`：源码测试和静态网站部署。
- `.github/workflows/daily.yml`：交易日北京时间16:35盘后更新并重部署。
- `.github/workflows/quotes.yml`：交易时段以「独立 quote-feed 单提交分支」更新压缩公开行情，不每次上传 Pages Artifact；防止主分支高频行情文件历史膨胀。

## 已知限制
- 不保证行情为实时数据；数据源 AKShare / 东方财富可能不可用。
- 尚未验证GitHub Actions环境的真实历史数据抓取与全市场覆盖率。
- 买卖信号是可解释的研究观察信号，不是自动委托或投资建议；策略参数尚需用完整历史样本做样本外验证。
- 策略历史回测未完整模拟停牌、涨跌停、历史退市股、分红除权及组合级资金占用；不可用于直接自动交易。
- 页面公开访问，持仓仅本机存储；建议定期导出本机记录，且不要把私有备份提交到仓库。
