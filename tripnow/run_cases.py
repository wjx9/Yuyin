#!/usr/bin/env python
"""一口气跑完全部 demo case：逐轮打印 输入 / 命中意图 / 输出，最后给逐条与汇总 pass。

判定标准：
  - 命中意图 == 期望意图（intent_ok）
  - 若该 case 标了 expect_contains，则输出需至少包含其中一项（content_ok，主要用于校验闲聊记忆）
  - 期望意图未启用（对应 key 缺失）→ 记 SKIP，不计入 FAIL

闲聊记忆相关 case 共用同一个进程内 SessionHistory，按顺序执行以复现多轮上下文。

运行：python run_cases.py   （依赖 .env 里的各 key，会发起真实网络调用）
"""

from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

from dataclasses import dataclass, field

from routing import RouteContext, SessionHistory, build_dispatcher, setup_logging


@dataclass
class Case:
    name: str
    prompt: str
    expect_intent: str
    expect_contains: tuple[str, ...] = field(default_factory=tuple)


# 用例取自 demo prompts 表；闲聊记忆三条必须按序执行
CASES: list[Case] = [
    Case("能力查询", "你有哪些能力?", "chitchat"),
    Case("闲聊", "你好阿", "chitchat"),
    Case("闲聊记忆-铺垫", "1+1等于几?", "chitchat"),
    Case("闲聊记忆-回忆1", "我刚才问你什么来着?", "chitchat", ("1+1", "1 + 1", "等于几")),
    Case("闲聊记忆-回忆2", "我刚才问你什么来着? 你怎么回答的?", "chitchat", ("1+1", "2", "等于")),
    Case("查快递", "看下我的单号为 1234567890 的快递", "express_tracking"),
    Case("查公开行程信息", "深圳到北京怎么最舒服?", "tripnow_public"),
    Case("查个人交通信息", "看下我名下的机票,火车票", "tripnow_personal"),
    Case("附近商家推荐-1", "附近扫街榜单", "amap"),
    Case("附近商家推荐-2", "深圳南山国际E城附近的川菜馆 top5 推荐", "amap"),
    Case("天气-1", "看一下深圳的天气", "tencent_weather"),
    Case("天气-2", "看下 广州未来5天的天气", "tencent_weather"),
    Case("新闻-全国热点", "看下今天的新闻top5", "tencent_hot_news"),
    # 主题新闻搜索与流言核查已下线，改由闲聊联网检索覆盖
    Case("指定主题新闻-联网", "关于苹果公司最近有什么新闻", "chitchat"),
    Case("信息鉴真-联网", "每天喝八杯水对身体好吗", "chitchat"),
    Case("实时数值-联网", "看下 apple 公司的股价", "chitchat"),
]


def main() -> int:
    setup_logging(None)  # 安静模式，避免路由日志淹没结果
    dispatcher = build_dispatcher()
    enabled = set(dispatcher.intents)
    print(f"已启用意图：{', '.join(dispatcher.intents)}\n")

    history = SessionHistory(path=None)  # 进程内共享，验证闲聊记忆
    union_id = os.getenv("TRIPNOW_UNION_ID") or None
    location = os.getenv("DEMO_LOCATION") or "113.92,22.53"  # 默认深圳南山，供高德用

    results: list[tuple[str, str, str, str]] = []  # (name, status, expect, got)

    for i, c in enumerate(CASES, 1):
        print("=" * 72)
        print(f"[{i}/{len(CASES)}] {c.name}")
        print(f"输入  : {c.prompt}")

        if c.expect_intent not in enabled:
            print(f"命中  : -（期望意图 {c.expect_intent} 未启用，跳过）\n")
            results.append((c.name, "SKIP", c.expect_intent, "-"))
            continue

        ctx = RouteContext(union_id=union_id, location=location, history=history.turns)
        result = dispatcher.dispatch(c.prompt, ctx)
        history.append(c.prompt, result.text)

        print(f"命中  : {result.intent}（期望 {c.expect_intent}）")
        print(f"输出  : {result.text}")

        intent_ok = result.intent == c.expect_intent
        content_ok = (not c.expect_contains) or any(s in result.text for s in c.expect_contains)
        passed = intent_ok and content_ok
        status = "PASS" if passed else "FAIL"

        reasons = []
        if not intent_ok:
            reasons.append(f"意图不符(得到 {result.intent})")
        if not content_ok:
            reasons.append(f"未包含期望内容 {c.expect_contains}")
        print(f"判定  : {status}" + (("  ← " + "; ".join(reasons)) if reasons else ""))
        print()
        results.append((c.name, status, c.expect_intent, result.intent))

    # ---- 汇总 ----
    npass = sum(1 for r in results if r[1] == "PASS")
    nfail = sum(1 for r in results if r[1] == "FAIL")
    nskip = sum(1 for r in results if r[1] == "SKIP")

    print("#" * 72)
    print("逐条结果")
    print("#" * 72)
    for name, status, exp, got in results:
        print(f"  [{status:4}] {name:<16} 期望={exp:<20} 实际={got}")
    print("-" * 72)
    print(f"汇总: PASS {npass} / FAIL {nfail} / SKIP {nskip}  （共 {len(results)} 条）")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
