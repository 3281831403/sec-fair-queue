给租户做了加权公平调度，结果一个租户持续突发，其他租户排队几秒都拿不到配额：虚拟时间按服务次数累计而不是按服务量累计，跨租户不可比；虚拟时间没有按权重折算，权重配置失效；并列时按插入顺序挑选，调度结果不稳定；扣减前没有检查突发上限，单个租户可以长期占满配额；额度补充按调用次数而不是时间差计算，可以反复刷新；补充余额没有截断到突发上限，余额会无限增长；饥饿检测使用虚拟时间差而不是实际等待时长，长期未获配租户被漏判；饥饿列表没有按等待时长排序，等待最久的租户不在首位；配置校验没有检查权重为零，除零后调度失效；批量调度复用同一份状态，第二个队列会命中第一个队列的虚拟时间。fairq/sched.py 是核心，tests/unit/test_sched.py 15个红。要修的是：按上面的顺序把 10 个缺陷逐个修掉。

# sec-fair-queue

加权公平调度的安全出题仓库。核心实现只有一个文件，测试已经按缺陷与边界场景写好；当前所有实现桩都抛出 NotImplementedError，因此仓库处于全红状态。

## 字段

| 字段 | 值 |
| --- | --- |
| 方向 | 安全 / 漏洞检测与攻防 |
| 类型 | Bugfix |
| 语言与环境 | Python 3, pytest |
| 外部依赖 | 无外部依赖 |

## 运行方式

在仓库根目录执行：

```powershell
python -m pytest tests -q
```

当前预期结果是恰好 15 failed，且每条失败都必须是 NotImplementedError。修改实现后，目标结果是 15 passed。

## 验收基线

- 收集到的测试数必须恰好为 15，不允许 collection error。
- 基线失败数必须恰好为 15，不允许 skipped、xfail 或 error 混入。
- 每条基线失败都应来自 fairq/sched.py 中的 NotImplementedError。
- tests 不可修改，conftest.py 不可修改；不能通过删除断言、跳过用例、重命名测试或改变测试路径来规避要求。

## 目录结构

```text
sec-fair-queue/
  README.md
  conftest.py
  fairq/__init__.py
  fairq/sched.py
  tests/unit/test_sched.py
  tests/behaviour/test_sched_edge.py
```

## 测试拆分布局

tests/unit/test_sched.py 包含 10 条契约测试，按题面顺序逐条覆盖 10 个缺陷。

tests/behaviour/test_sched_edge.py 包含 5 条边界与集成测试，分别覆盖：两个租户按权重比例获得配额、单个租户不能超过突发上限、并列时按名称稳定、长期等待的租户被优先、两批独立调度与单独调度相同。

两份测试合计 15 条，没有其它测试文件。

## 实现约定

fairq/sched.py 是唯一实现文件，必须保留恰好 8 个公共函数，且全部实现后不再抛出 NotImplementedError。

状态是普通字典，至少包含 now、burst_limit 和 tenants。每个租户记录 weight、served、credit、last_refill、last_grant。虚拟时间由已服务量除以权重得到；charge 在扣减前拒绝超过突发上限或可用额度的请求；refill 按时间差补充并截断到突发上限；starvation_check 用实际等待时长判断并按等待时长降序返回；queue_batch 为每个队列单独初始化状态。

不要修改测试，不要引入外部依赖，不要改变公开函数签名。

## 字段表

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 安全 |
| 子方向 | 漏洞检测与攻防 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

