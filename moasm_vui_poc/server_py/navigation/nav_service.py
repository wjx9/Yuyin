"""导航服务：生成 AmapLinkClient 可执行的导航控制指令。

架构定位（真正导航模式）：
  服务端（本模块）  →  生成 NavCommand（含 cmd/requestId/data）
  手机端（Android）  →  收到 NavCommand 后调用 AmapLinkClient.execute(json)
  高德地图 App       →  通过 IPC 接收指令，执行真正的导航（启动/停止/切换路线等）

服务端不直接执行导航，只负责：
  1. 维护导航会话状态（是否在导航中、当前目的地）—— 用于对话引擎多轮判断
  2. 生成符合 AmapLinkClient 协议的 NavCommand —— 放入 response.data 下发手机端
  3. 手机端执行结果通过后续请求回传（简化版：服务端假设指令已执行，本地同步状态）

AmapLinkClient 指令协议（cmd）：
  1 = 切换路线      data: {"pathID": "123"}
  2 = 停止导航      data: {}
  3 = 添加途经点    data: {"lon","lat","name","poiid","entranceList"}
  4 = 设置/变更终点 data: {"lon","lat","name","poiid"}
  5 = 查询导航结构化信息 data: {}
  6 = 切换播报方式  data: {"mode": 2} 或 {"value": "1"}
  7 = 触发导航关键信息刷新 data: {}
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .models import NavCommand, Poi

_log = logging.getLogger("navigation.nav_service")


def _next_request_id() -> int:
    """生成请求 ID（毫秒级时间戳，AmapLinkClient 协议用 int）。"""
    return int(time.time() * 1000)


def _parse_location(location: str | None) -> tuple[float | None, float | None]:
    """解析 "经度,纬度" 字符串。"""
    if not location:
        return None, None
    parts = location.split(",")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None, None


@dataclass
class NavigationResult:
    """导航操作结果。

    包含需要手机端执行的 NavCommand；服务端本地同步导航状态。
    """

    success: bool
    command: NavCommand | None = None   # 手机端需执行的指令
    route_id: str | None = None          # 本地会话标识（非高德 route_id，仅服务端用）
    error: str | None = None


class NavigationService:
    """导航服务：生成 AmapLinkClient 指令，维护本地导航状态。

    注意：本服务不直接调用高德导航 SDK，真正的导航执行在手机端通过
    AmapLinkClient 与高德地图 App IPC 通信完成。
    """

    def __init__(self):
        self._is_in_navigation: bool = False
        self._current_poi: Poi | None = None
        self._nav_start_time: float | None = None
        self._session_seq: int = 0  # 本地会话序号

    @property
    def is_in_navigation(self) -> bool:
        return self._is_in_navigation

    @property
    def current_poi(self) -> Poi | None:
        return self._current_poi

    def start_navigation(self, poi: Poi) -> NavigationResult:
        """启动导航：生成 cmd=4（设置终点）指令，手机端执行后高德地图 App 开始导航。

        Args:
            poi: 用户选中的 POI（需包含 name 和 location="经度,纬度"）

        Returns:
            NavigationResult，含 cmd=4 的 NavCommand
        """
        if not poi or not poi.name:
            return NavigationResult(success=False, error="无效的目的地")

        lon, lat = _parse_location(poi.location)
        if lon is None or lat is None:
            _log.warning("POI 缺少经纬度，导航指令仍生成但高德可能无法定位: %s", poi.name)

        # 生成 cmd=4 指令：设置/变更终点
        # 高德地图 App 收到后会规划路线并自动开始导航
        cmd_data: dict = {
            "name": poi.name,
        }
        if lon is not None and lat is not None:
            cmd_data["lon"] = lon
            cmd_data["lat"] = lat
        if poi.raw.get("id"):
            cmd_data["poiid"] = poi.raw["id"]

        command = NavCommand(
            cmd=4,
            request_id=_next_request_id(),
            data=cmd_data,
            description=f"设置终点并启动导航: {poi.name}",
        )

        # 服务端本地同步状态（假设手机端会成功执行；手机端执行失败时通过后续请求回传修正）
        self._session_seq += 1
        self._is_in_navigation = True
        self._current_poi = poi
        self._nav_start_time = time.time()
        route_id = f"nav_session_{self._session_seq}"

        _log.info(
            "导航指令已生成: cmd=4, 目的地=%s, 经纬度=(%s,%s), requestId=%d",
            poi.name, lon, lat, command.request_id,
        )

        return NavigationResult(
            success=True,
            command=command,
            route_id=route_id,
        )

    def stop_navigation(self) -> NavigationResult:
        """停止导航：生成 cmd=2 指令，手机端执行后高德地图 App 结束导航。

        Returns:
            NavigationResult，含 cmd=2 的 NavCommand
        """
        if not self._is_in_navigation:
            _log.warning("停止导航：当前不在导航中")
            # 即使不在导航中也生成停止指令（兜底，确保高德地图 App 不会残留导航状态）
            command = NavCommand(
                cmd=2,
                request_id=_next_request_id(),
                data={},
                description="停止导航（兜底）",
            )
            return NavigationResult(success=False, command=command, error="当前不在导航中")

        poi_name = self._current_poi.name if self._current_poi else "未知"

        command = NavCommand(
            cmd=2,
            request_id=_next_request_id(),
            data={},
            description=f"停止导航: {poi_name}",
        )

        # 服务端本地同步状态
        self._is_in_navigation = False
        self._current_poi = None
        self._nav_start_time = None

        _log.info("停止导航指令已生成: cmd=2, 原目的地=%s", poi_name)

        return NavigationResult(success=True, command=command)

    def reroute(self, poi: Poi) -> NavigationResult:
        """重新导航到新目的地：生成 cmd=4（变更终点）指令。

        与 start_navigation 相同的指令码，但语义是"变更当前导航的终点"。
        高德地图 App 收到后会重新规划路线。

        Args:
            poi: 新目的地 POI

        Returns:
            NavigationResult，含 cmd=4 的 NavCommand
        """
        result = self.start_navigation(poi)
        if result.success and result.command:
            result.command.description = f"变更终点并重新导航: {poi.name}"
        return result

    def switch_route(self, path_id: str) -> NavigationResult:
        """切换路线：生成 cmd=1 指令。

        Args:
            path_id: 备选路线 ID

        Returns:
            NavigationResult，含 cmd=1 的 NavCommand
        """
        if not self._is_in_navigation:
            return NavigationResult(success=False, error="当前不在导航中，无法切换路线")

        command = NavCommand(
            cmd=1,
            request_id=_next_request_id(),
            data={"pathID": path_id},
            description=f"切换路线: pathID={path_id}",
        )

        _log.info("切换路线指令已生成: cmd=1, pathID=%s", path_id)
        return NavigationResult(success=True, command=command)

    def set_broadcast_mode(self, mode: int) -> NavigationResult:
        """切换播报方式：生成 cmd=6 指令（驾车模式）。

        Args:
            mode: 0=静音, 1=简洁播报, 2=详细播报, 6=极简播报, 7=智能播报

        Returns:
            NavigationResult，含 cmd=6 的 NavCommand
        """
        command = NavCommand(
            cmd=6,
            request_id=_next_request_id(),
            data={"mode": mode},
            description=f"切换播报方式: mode={mode}",
        )
        return NavigationResult(success=True, command=command)

    def get_nav_status(self) -> dict:
        """获取当前导航状态（服务端本地视图）。"""
        return {
            "is_in_navigation": self._is_in_navigation,
            "destination": self._current_poi.name if self._current_poi else None,
            "nav_start_time": self._nav_start_time,
            "elapsed_seconds": (
                int(time.time() - self._nav_start_time)
                if self._nav_start_time else None
            ),
        }
