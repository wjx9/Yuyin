/// 导航数据模型：从 Android 端 EventChannel 接收的导航实时数据。

/// 导航事件类型。
enum NaviEventType {
  /// 导航信息更新（转向、距离、时间等）。
  naviInfo,

  /// 路线计算成功。
  routeCalcSuccess,

  /// 路线计算失败。
  routeCalcFailure,

  /// 开始导航。
  startNavi,

  /// 到达目的地。
  arrivedDestination,

  /// 导航结束（手动确认退出导航）。
  naviEnd,

  /// 导航播报文本。
  naviText,

  /// 错误。
  error,

  /// 未知事件。
  unknown,
}

/// 导航事件（从 Android 端推送）。
class NaviEvent {
  final NaviEventType type;
  final Map<String, dynamic> data;

  const NaviEvent({required this.type, required this.data});

  factory NaviEvent.fromMap(Map<String, dynamic> map) {
    final typeStr = map['type'] as String? ?? '';
    final type = _parseEventType(typeStr);
    return NaviEvent(type: type, data: map);
  }

  static NaviEventType _parseEventType(String typeStr) {
    switch (typeStr) {
      case 'navi_info':
        return NaviEventType.naviInfo;
      case 'route_calc_success':
        return NaviEventType.routeCalcSuccess;
      case 'route_calc_failure':
        return NaviEventType.routeCalcFailure;
      case 'start_navi':
        return NaviEventType.startNavi;
      case 'arrived_destination':
        return NaviEventType.arrivedDestination;
      case 'navi_end':
        return NaviEventType.naviEnd;
      case 'navi_text':
        return NaviEventType.naviText;
      case 'error':
        return NaviEventType.error;
      default:
        return NaviEventType.unknown;
    }
  }
}

/// 导航实时信息（对应 Android 端 NaviInfo）。
class NaviInfo {
  /// 转向图标类型（高德 IconType 枚举值）。
  final int iconType;

  /// 当前路段剩余距离（米）。
  final int curStepRetainDistance;

  /// 路线剩余距离（米）。
  final int pathRetainDistance;

  /// 路线剩余时间（秒）。
  final int pathRetainTime;

  /// 下一条路名。
  final String nextRoadName;

  /// 当前路名。
  final String currentRoadName;

  /// 当前速度（km/h）。
  final int currentSpeed;

  /// 路段总数。
  final int stepNum;

  /// 当前路段索引。
  final int curStep;

  const NaviInfo({
    this.iconType = 0,
    this.curStepRetainDistance = 0,
    this.pathRetainDistance = 0,
    this.pathRetainTime = 0,
    this.nextRoadName = '',
    this.currentRoadName = '',
    this.currentSpeed = 0,
    this.stepNum = 0,
    this.curStep = 0,
  });

  factory NaviInfo.fromMap(Map<String, dynamic> map) {
    return NaviInfo(
      iconType: (map['iconType'] as num?)?.toInt() ?? 0,
      curStepRetainDistance: (map['curStepRetainDistance'] as num?)?.toInt() ?? 0,
      pathRetainDistance: (map['pathRetainDistance'] as num?)?.toInt() ?? 0,
      pathRetainTime: (map['pathRetainTime'] as num?)?.toInt() ?? 0,
      nextRoadName: map['nextRoadName'] as String? ?? '',
      currentRoadName: map['currentRoadName'] as String? ?? '',
      currentSpeed: (map['currentSpeed'] as num?)?.toInt() ?? 0,
      stepNum: (map['stepNum'] as num?)?.toInt() ?? 0,
      curStep: (map['curStep'] as num?)?.toInt() ?? 0,
    );
  }

  /// 格式化剩余距离（米 → 公里/米）。
  String get formattedRetainDistance {
    if (pathRetainDistance >= 1000) {
      return '${(pathRetainDistance / 1000).toStringAsFixed(1)}公里';
    }
    return '$pathRetainDistance米';
  }

  /// 格式化当前路段剩余距离。
  String get formattedCurStepDistance {
    if (curStepRetainDistance >= 1000) {
      return '${(curStepRetainDistance / 1000).toStringAsFixed(1)}公里';
    }
    return '$curStepRetainDistance米';
  }

  /// 格式化剩余时间（秒 → 小时/分钟）。
  String get formattedRetainTime {
    if (pathRetainTime >= 3600) {
      final hours = pathRetainTime ~/ 3600;
      final minutes = (pathRetainTime % 3600) ~/ 60;
      return '${hours}小时${minutes}分钟';
    } else if (pathRetainTime >= 60) {
      return '${pathRetainTime ~/ 60}分钟';
    }
    return '$pathRetainTime秒';
  }

  /// 转向描述（根据 iconType 返回文字描述）。
  String get turnDescription {
    // 高德 IconType 常见值：
    // 0=直行, 1=左转, 2=右转, 3=左前方, 4=右前方, 5=左后方, 6=右后方
    // 7=掉头, 8=到达途经点, 9=进入环岛, 10=驶出环岛, 11=到达目的地
    switch (iconType) {
      case 0:
        return '直行';
      case 1:
        return '左转';
      case 2:
        return '右转';
      case 3:
        return '左前方行驶';
      case 4:
        return '右前方行驶';
      case 5:
        return '左后方行驶';
      case 6:
        return '右后方行驶';
      case 7:
        return '掉头';
      case 8:
        return '到达途经点';
      case 9:
        return '进入环岛';
      case 10:
        return '驶出环岛';
      case 11:
        return '到达目的地';
      default:
        return '继续行驶';
    }
  }
}
