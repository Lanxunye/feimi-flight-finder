# 飞觅 Crawl4AI 实时数据服务

此服务把 Crawl4AI 抓取结果规范化为 WebUI 使用的航班报价格式。Crawl4AI 采用 `AsyncWebCrawler`、`BrowserConfig` 与 `CrawlerRunConfig`，并对实时查询使用 `CacheMode.BYPASS`。

主报价来自飞猪 FlyAI、携程专用浏览器与去哪儿专用浏览器。各浏览器使用独立 Chrome 配置目录；需要时由用户人工登录或完成验证码，服务只通过本机 CDP 捕获航班搜索产生的结构化响应，不读取或输出账号、密码与 Cookie。各来源均连续查询两次，只保留航班号与起降时间完全一致的结果；两次价格无须相同，WebUI 会同时显示并允许用户人工选择。去哪儿响应内的原始价格带有页面混淆，适配器只采用去哪儿页面实际渲染的可见价格，并遍历全部结果分页。未指定转机地时，系统优先展示直飞；所有来源均无直飞后才展示不限转机点的单次转机方案。用户可启用“仅看通程航班”；该筛选只接受来源响应明确标注的“通程”行程或行李直挂、航变保障，不以同航司、普通联程或中转权益进行推断。所有转机方案至少预留 120 分钟且总行程不超过 16 小时，跨日方案默认折叠。应用层不限制方案数量，并按价格 55%、总时长 35%、转机次数 10% 综合排序。Crawl4AI 保留为未登录页面的辅助确认源。阿里云百炼 Qwen 联网能力只检查航班、机场和日期异常，不生成或修改票价。

> 航空公司和 OTA 页面会频繁变化，且可能有验证码或自动化访问限制。部署前请确认目标网站的 robots.txt、服务条款与数据授权，并在 `parse_page` 中维护对应解析规则。价格与余票始终以最终出票页面为准。

## 本地启动

```bash
python -m venv .venv
source .venv/bin/activate
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r crawler-service/requirements.txt
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001
```

启动前通过运行环境配置 `FLYAI_API_KEY` 与 `DASHSCOPE_API_KEY`。不要把密钥写入源码或提交到版本库。

本项目在 macOS 上复用已安装的 Google Chrome，因此无需额外下载 Crawl4AI 的 Chromium 浏览器包。

随后为 WebUI 设置：

```bash
FLIGHT_CRAWLER_URL=http://127.0.0.1:8001 npm run dev
```

未配置、实时服务暂不可用，或两次查询无法匹配同一航班时，WebUI 不展示价格。系统不会回退到算法生成的演示行情。

## macOS 后台部署

本机安装版位于 `~/Library/Application Support/Feimi`，由三个用户 LaunchAgent 管理：

- `com.feimi.crawler`：Crawl4AI 接口，监听 `127.0.0.1:8001`
- `com.feimi.web`：本地飞觅网页，监听 `127.0.0.1:3000`
- `com.feimi.ctrip-browser`：携程专用 Chrome，仅在 `127.0.0.1:9223` 开放调试连接，浏览器资料保存在权限为 700 的独立目录

桌面上的“飞觅机票”应用会检查并启动三个服务，然后打开本地页面。携程、去哪儿和美团登录入口均位于 WebUI 顶栏；首次使用需由用户人工完成登录和验证码。`scripts/feimi-stop.sh` 可停止后台服务；再次双击桌面应用即可恢复。

官方项目：[unclecode/crawl4ai](https://github.com/unclecode/crawl4ai)
