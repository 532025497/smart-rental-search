---
name: rental-selection-system
description: 智能租房选择系统。输入工作地点+通勤时间，基于高德地图API计算地铁可达可行域、检索周边小区、扫描居住体验配套并按线路分类，再用多Agent Loop(规划师→开发→评判器)从豆瓣/小红书采集房源并经LLM提取结构化租金。当用户需要"按通勤找房""地铁沿线租房""小区居住体验对比""租房筛选系统"时使用。
version: 1.1.0
---

# 租房选择系统

输入工作地址与通勤上限，自动算出"地铁可达的居住区域"，检索周边小区、评估居住体验配套、按地铁线路分类，并可进一步从社交平台采集真实房源、用 LLM 提取结构化租金，输出"通勤 + 居住体验 + 租金"一体化筛选结果。

## 一、核心认知（接手前必读）

这些是反复验证后的结论，能省去大量试错：

1. **高德地图 API 只提供"位置/通勤"，不提供租金。** 它能地理编码、周边检索小区（POI types=120300）、算公交地铁通勤时间（direction/transit），但**没有任何租金、户型、独卫、短租数据**。

2. **贝壳 / 安居客 / 链家都没有面向个人的公开官方 API。** 网上（阿里云社区/CSDN）那些"贝壳API""安居客API"教程，实测都是逆向或编造的：安居客 `api.anjuke.com/property/v1/detail` 返回 **404**（假接口），真后端 `/mobile/v5/property/detail` 返回 **401「签名错误」**（要逆向签名算法，等同爬虫，不可正规接入）。**不要再去验证这类教程，直接按"无官方API"处理。**

3. **真实分户型租金没有"免费+合法+实时"的官方源。** 北京政府开放数据平台（data.beijing.gov.cn）搜"租金/住房租赁/房价"均为 0 结果，无小区租金接口（深圳 opendata.sz.gov.cn 有"小区租赁参考价格"，但是政府指导价、非实时）。拿真实租金的现实途径只有一条：**社交平台采集 + LLM 提取**（本质是采集，与"纯官方API"原则冲突，需用户知情同意）。

4. **高德免费 Key 有 QPS 限制。** 高并发请求会触发限流（infocode 10004），`src/gaode.py` 的 `_get()` 已内置退避重试（RETRYABLE_INFOCODES）。**并发不要超过 6**，否则会大量静默失败。

5. **门口站会被误判不可达。** 离工作地很近的站（如国贸），高德只返回步行方案、不给公交方案，transit 返回 None。`src/feasible_domain.py` 的 `_check_station()` 已加步行兜底（walk_min = 直线距离 / 0.078）。

## 二、环境与依赖

- Python 3.9+（跨平台：Windows / macOS / Linux 均已验证）。
- **核心功能（可行域 / 小区检索 / 居住体验 / LLM）仅用标准库**（urllib），无需安装任何包。
- 可选依赖（按需）：

```
requests          # 豆瓣/小红书采集器
beautifulsoup4    # 豆瓣HTML解析
flask             # Web UI (app.py)
```

**macOS / Linux 快速 setup：**
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt   # 可选依赖
cp .env.example .env              # 填入 API Key
./run.sh                          # 一键启动 Web UI
```

**Windows：**
```cmd
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

- 编码：所有脚本已内置 `sys.stdout.reconfigure(encoding="utf-8")`（跨平台 try/except），无需手动设 `PYTHONIOENCODING`。
- 本项目**不依赖** Streamlit/pyarrow，Web 界面用 Flask + 原生 HTML/JS + Leaflet CDN。

## 三、配置

编辑 `config.py` 或设环境变量：

- `GAODE_API_KEY`（必填）：高德 Web 服务 Key，请通过环境变量或 `.env` 配置自己的 Key。
- `LLM_API_KEY` / `DEEPSEEK_API_KEY`（可选）：OpenAI 兼容 API，用于房源提取。推荐 DeepSeek。不配置则 `run.py` 自动跳过 LLM 提取（`--no-llm`）。
- `LLM_BASE_URL` / `LLM_MODEL`：默认 `https://api.deepseek.com/v1` + `deepseek-chat`。
- 通勤估算参数：`TRANSIT_SPEED_KMH=22`、`ROUTE_FACTOR=1.3`、`PREFILTER_MULTIPLIER=1.5`、`MAX_CONCURRENT`（建议 ≤6）。

## 四、快速开始（三个入口）

```bash
# 入口1: 只算可行域(可达地铁站)，纯标准库，最快
python3 cli.py --city 北京 --work "正大中心" --commute 40    # macOS/Linux
python cli.py --city 北京 --work "正大中心" --commute 40      # Windows

# 入口2: 完整多Agent Loop(规划→采集→LLM提取→验证→排序)
python3 run.py --city 北京 --work "正大中心" --commute 40 --budget 3000-6000
python3 run.py --no-llm        # 不配LLM Key时，只看规划+采集

# 入口3: Flask Web UI (需 flask)，浏览器交互+Leaflet地图
python3 app.py                 # 访问 http://127.0.0.1:5050

# macOS/Linux 一键脚本 (自动创建venv+安装依赖):
chmod +x run.sh && ./run.sh          # Web UI
./run.sh cli --work "正大中心"       # 可行域
./run.sh demo                        # 演示流水线
```

## 五、能力演示流水线（推荐按顺序跑）

这几个 demo 构成一条链，后一个读取前一个的输出。改脚本里的 `work` 变量即可换地点：

```bash
# 1) 按真实地铁通勤时间算可行域(会调用transit, 含QPS重试)
#    输出 data/feasible_zhengda_*.json (含各站通勤时间+周边小区)
python demo_zhengda_transit.py

# 2) 对舒适通勤圈(<=30min)各站扫描周边1km生活配套并打分排序
#    读取上一步的 feasible_zhengda_*.json
python demo_livability.py

# 3) 按地铁线路(1/10/14号线)整理各站居住体验
python demo_livability_byline.py

# 4) 把可行域+小区+通勤生成 Markdown 整理文档
python gen_zhengda_doc.py
```

**居住体验打分法**（`demo_livability.py`）：对每站周边 1km 检索 购物中心(060101)/超市(060400)/公园(110101)/医院(090100)/学校(141200)，按 `公园×4 + 商业×3 + 医疗×2 + 教育×2 + log(总数)×2` 加权。**关键经验：总分高≠居住体验好**——纯商业密度会拉高分（如国贸CBD），但公园绿地才是舒适居住的分水岭，解读时要分开看"繁华便利型"vs"均衡宜居型"。

## 六、架构

多 Agent **Loop**（非线性流水线），三方协作 + 反馈循环：

```
规划师 Planner ── 算可行域(FeasibleDomain) + 生成采集计划(站名/小区名关键词)
   │
评判器 Evaluator ── 先定义验收标准(预算/通勤/独卫/短租规则)
   │
开发 Developer ── 采集(collectors) → LLM提取(extract)
   │                                    │
   └──── 评判器验证(validate) ←─────────┘
              │ FAIL → 反馈写回帖子 → 重新提取(最多N轮)
              │ PASS → 入库
   最后排序输出(rank)
```

核心数据模型（`src/models.py`，均 dataclass）：
`UserRequirement`（需求）、`ViableStation`（可行站）、`CollectionTask`/`CollectionPlan`（采集计划）、`RawPost`（原始帖子）、`Listing`（结构化房源）、`AcceptanceCriteria`（验收标准）、`ValidationResult`（验证结果）、`Platform`（平台枚举）。

关键模块：
- `src/gaode.py` — 高德客户端（geocode / search_metro_stations / search_xiaoqu / transit_duration），内置 QPS 退避重试。
- `src/feasible_domain.py` — 可行域计算（直线预筛 → 并发精确通勤 → 步行兜底 → 排序）。
- `src/metro_data.py` — 地铁站数据本地缓存（`data/metro_stations_北京.json`，已含225站，避免重复抓取）。
- `src/agents/` — planner / developer / evaluator 三个 Agent。
- `src/collectors/` — douban（stub+real 双模式）、xiaohongshu（需 cookie）。
- `src/llm.py` — OpenAI 兼容 LLM 客户端（纯 urllib）。
- `src/loop.py` — 主循环协调器。

## 七、关键坑（务必注意）

- **高德 QPS**：并发 ≤6，依赖 `_get()` 的退避重试；切勿用线程池猛打 transit。
- **豆瓣反爬**：关键词组数 **<10**（22组×3-5s 仍触发 429）；随机延迟 1-2s；触发 429/403 后需冷却 30min+；小区名精确匹配几乎 0 命中（帖子标题只写站名），要用站名模糊匹配 + 全量列表 fallback。
- **小红书**：API 需 cookie + X-s/X-t 签名；无 cookie 返回"无登录信息"，账号异常返回"请切换账号"。**真实爬取必须保守（≤5帖+延迟），失败立即停止，用户极担心封号。** 无 cookie 时用 stub 模式。
- **建成年代**：高德 POI 详情对小区不返回 build_year，只能靠小区名关键词推测（宿舍/家园=老，府/苑/国际=新）。
- **租金估算**：demo 里的租金数字是按"CBD基准+距地铁+小区档次"的**粗估，非真实挂牌价**，不可当真；真租金必须采集。
- **跨平台编码**：所有入口脚本已内置 `try: sys.stdout.reconfigure(encoding="utf-8")` 兜底，Windows/macOS/Linux 均可直接运行。若在 Windows 用 subprocess 调外部命令，仍需 `capture_output=True` + `decode('utf-8','replace')`。

## 八、扩展指引

- **换城市**：`cli.py --city 上海 ...`；首次会拉取该城市地铁站缓存到 `data/metro_stations_上海.json`。
- **加采集器**：继承 `src/collectors/base.py` 的 `BaseCollector`，实现 `collect()` 返回 `list[RawPost]`，在 `run.py`/`app.py` 里 `developer.register_collector(Platform.XXX, collector)`。
- **调通勤口径**：改 `config.py` 的 `TRANSIT_SPEED_KMH`/`ROUTE_FACTOR`/`PREFILTER_MULTIPLIER`，或直接改 `FeasibleDomain` 构造参数。
- **加居住体验维度**：在 `demo_livability.py` 的 `TYPES`/`WEIGHT` 里增删 POI 类型与权重。

## 九、验证

跑通标志：
- `python cli.py --work "正大中心" --commute 40` 输出约 20 个可行站（国贸/大望路/呼家楼/十里河/宋家庄…），API 调用 ~150 次无报错。
- `python demo_livability.py` 输出 12 站配套排名（国贸分最高但属繁华型，十里堡/青年路/呼家楼/东大桥为均衡宜居型）。
