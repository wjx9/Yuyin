#!/usr/bin/env python
"""批量回归（client-server 版）—— 对标根目录 run_cases.py，逐条跑全部 demo case。

与单机版唯一的差别：不再本地 build_dispatcher()，而是把每条 prompt 发给 serve.py。
判定标准、用例集、闲聊记忆的"按序共享上下文"都与单机版保持一致：
  - 命中意图 == 期望意图（intent_ok）
  - 标了 expect_contains 则输出需至少包含其一（content_ok，校验闲聊记忆）
  - 期望意图未在服务端启用（对应 key 缺失）→ 记 SKIP，不计入 FAIL
闲聊记忆三条共用同一个 session_id，按序执行以在服务端复现多轮上下文。

运行（先在 PC 上 `python serve.py`）：
    python -m client_py.run_cases
    python client_py/run_cases.py --server http://192.168.1.5:8000
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

# 允许直接 `python client_py/run_cases.py` 运行
if __package__ in (None, ""):
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from client_py.client import ServerClient, ServerError
    from client_py.config import ClientConfig
else:
    from .client import ServerClient, ServerError
    from .config import ClientConfig

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


@dataclass
class Case:
    name: str
    prompt: str
    expect_intent: str
    expect_contains: tuple[str, ...] = field(default_factory=tuple)


# 与根目录 run_cases.py 完全一致的用例集（闲聊记忆三条必须按序执行）
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="client_py.run_cases", description="CS 版批量回归")
    parser.add_argument("--server", metavar="URL", help="服务端地址（默认 env SERVER_URL 或 127.0.0.1:8000）")
    parser.add_argument("--token", metavar="TOKEN", help="Bearer 鉴权密钥（默认 env SERVER_AUTH_TOKEN）")
    parser.add_argument("--location", metavar="经度,纬度", help="位置坐标，供高德用（默认深圳南山）")
    args = parser.parse_args(argv)

    config = ClientConfig.from_env(
        server_url=args.server, auth_token=args.token, location=args.location
    )
    client = ServerClient(config)

    try:
        health = client.health()
    except ServerError as e:
        print(f"无法连接服务端 {config.server_url}：{e}", file=sys.stderr)
        print("请先在 PC 上运行 `python serve.py`。", file=sys.stderr)
        return 1

    enabled = set(health.capabilities)
    print(f"服务端：{config.server_url}")
    print(f"已启用意图：{', '.join(health.capabilities)}")
    print(f"会话：{config.session_id}（全程共享，验证闲聊记忆）\n")

    results: list[tuple[str, str, str, str]] = []  # (name, status, expect, got)

    for i, c in enumerate(CASES, 1):
        print("=" * 72)
        print(f"[{i}/{len(CASES)}] {c.name}")
        print(f"输入  : {c.prompt}")

        if c.expect_intent not in enabled:
            print(f"命中  : -（期望意图 {c.expect_intent} 未启用，跳过）\n")
            results.append((c.name, "SKIP", c.expect_intent, "-"))
            continue

        try:
            reply = client.chat(c.prompt)
        except ServerError as e:
            print(f"命中  : -（请求失败：{e}）")
            print("判定  : FAIL  ← 请求失败\n")
            results.append((c.name, "FAIL", c.expect_intent, "ERROR"))
            continue

        print(f"命中  : {reply.intent}（期望 {c.expect_intent}）")
        print(f"输出  : {reply.text}")

        intent_ok = reply.intent == c.expect_intent
        content_ok = (not c.expect_contains) or any(s in reply.text for s in c.expect_contains)
        passed = intent_ok and content_ok
        status = "PASS" if passed else "FAIL"

        reasons = []
        if not intent_ok:
            reasons.append(f"意图不符(得到 {reply.intent})")
        if not content_ok:
            reasons.append(f"未包含期望内容 {c.expect_contains}")
        print(f"判定  : {status}" + (("  ← " + "; ".join(reasons)) if reasons else ""))
        print()
        results.append((c.name, status, c.expect_intent, reply.intent))

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
