# cc-data-lab

CC_Codex 二期（26.11）**数据工程**主线基线：**采集任务控制台**（Flask 后端 + HTMX 前端页 + 站内 Mock 目录）。

## 领域

- **所属领域**：数据工程  
- **子方向**：数据采集、爬虫与 RPA  

## 技术栈

- Python 3.12+、Flask 3、SQLite  
- HTMX（CDN）+ Jinja 模板  
- pytest  

## 本地运行

```powershell
cd claude-workspace\cc-data-lab
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
python run.py
```

浏览器打开 http://127.0.0.1:5590 ，登录 **admin / 123456**。

流程：创建任务（选定种子 `/mock/catalog/alpha` 或 `beta` + 列映射版本）→ 详情页「运行采集」→ 查看落库与失败行（alpha 含重复编码与缺编码行，分别演示去重跳过与失败留痕）。

## 列映射版本与批次冻结

- 每个站内目录（alpha / beta）各自维护**列映射版本**：把目录页上的来源列对应到 **编码、标题、备注**。
- **每保存一次就产生一个新版本**（v1、v2…按目录递增）；**已存在的版本只读**，没有任何修改入口。
- **任务在创建时绑定一个版本，创建后不能改绑**；运行与重放按哪个版本解析，全部由服务端裁决。
- 每次运行/重放产生一个**批次**：
  - **未确认**：可整批换用**更新的版本**重新解析——先把本批从正式结果里**全部撤出**，再按新版本写入，同一编码不会同时留下新旧两行。
  - **已确认**：**冻结**，不能重新解析，也不能改标题（页面入口与服务端双重拒绝）。
- 来源里**缺少编码的行不入库**，计入失败行数，并在任务详情页列出（行号、原因、被丢弃的标题）。
- 同一次运行尚未结束时，不能再次触发运行或重放。

### 浏览器里怎样确认和重放

1. 登录后进入「列映射版本」页，为目录保存新版本（例如把 alpha 的标题列从 `name` 改成 `short`，保存为 v2；旧版本仍只读可查）。
2. 「任务」页创建任务并选定绑定版本 → 详情页「运行采集」。
3. 批次未确认时，详情页可二选一：
   - **确认**：点「确认批次（冻结）」，本批冻结，列表「批次确认」列变为已确认；
   - **重放**：在「换用更新版本」下拉里选更新版本，点「重新解析」——旧批次整批撤出（历史批次里标记「已撤出」），按新版本重新写入。
4. 已确认后，重放与改标题入口从页面消失，服务端同样拒绝。

## 自动化测试

`pytest` 共 10 组，核心六组覆盖：旧版本不能再改、未确认重放后同一编码不存在两份、已确认批次拒绝重放与改标题、缺编码计入失败且标题不入库、两个版本解析出的标题不一样、运行未结束时拒绝再次触发。

## Docker 一键启动（推荐用于快照前验收）

需已打开 **Docker Desktop**：

```powershell
cd claude-workspace\cc-data-lab
docker compose up -d --build
docker compose ps
```

- 页面：http://127.0.0.1:5590/login  
- Mock：http://127.0.0.1:5590/mock/catalog/alpha  
- 停止：`docker compose down`（保留库卷）· 清卷：`docker compose down -v`

`docker compose ps` 中 `STATUS` 含 **healthy** 表示服务可访问。线下表「环境可复现等级」可填 **已容器化，可一键起环境**。

## 前后端说明

| 层 | 说明 |
|----|------|
| 后端 | `app/` 路由、任务状态机、同步 runner、SQLite |
| 前端 | `templates/` + `static/`，浏览器可点操作 |
| Mock 源站 | `/mock/catalog/<id>` HTML，无需外网 |

## 初始快照

在首次 Claude 单轮跑题前 commit + push 本树（不含 `.venv/`、`instance/*.db`）。后续题目在同 repo 上叠加调度、RPA 步骤、增量水位等能力。

## 基线 vs 跑题目录

| 路径 | 角色 |
|------|------|
| `claude-workspace/cc-data-lab`（本目录） | **基线**：改功能、docker 验收 |
| `ccproject/cc-data-lab/data-XX` | **单题**：复制基线后挂容器、出快照 |

复制：`..\scripts\Copy-BaselineToQuestion.ps1 -QuestionId data-01`

## 跑题 Harness

见 `CCcodex/docs/ClaudeCode_Windows使用说明.md`（镜像 2.0）。容器挂载 **ccproject 下该题目录**，不是本基线路径。
