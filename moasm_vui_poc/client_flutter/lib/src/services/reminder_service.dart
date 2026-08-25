import 'package:flutter/foundation.dart';
import 'package:android_intent_plus/android_intent.dart';

import '../data/models.dart';

class ReminderService {
  Future<bool> create(ScheduleAction action) async {
    if (defaultTargetPlatform != TargetPlatform.android) return false;

    try {
      if (action.action == 'alarm') {
        final time = action.triggerTime;
        if (time == null) return false;
        await AndroidIntent(
          action: 'android.intent.action.SET_ALARM',
          arguments: {
            'android.intent.extra.alarm.HOUR': time.hour,
            'android.intent.extra.alarm.MINUTES': time.minute,
            'android.intent.extra.alarm.MESSAGE': action.title,
            'android.intent.extra.alarm.SKIP_UI': false,
          },
        ).launch();
        return true;
      }

      if (action.action == 'timer') {
        final seconds = action.durationSeconds;
        if (seconds == null || seconds <= 0) return false;
        await AndroidIntent(
          action: 'android.intent.action.SET_TIMER',
          arguments: {
            'android.intent.extra.alarm.LENGTH': seconds,
            'android.intent.extra.alarm.MESSAGE': action.title,
            'android.intent.extra.alarm.SKIP_UI': false,
          },
        ).launch();
        return true;
      }

      if (action.action == 'reminder') {
        final start = action.triggerTime;
        if (start == null) return false;
        final end = action.endTime ?? start.add(const Duration(minutes: 5));
        await AndroidIntent(
          action: 'android.intent.action.INSERT',
          data: 'content://com.android.calendar/events',
          category: 'android.intent.category.DEFAULT',
          arguments: {
            'title': action.title,
            'beginTime': start.millisecondsSinceEpoch,
            'endTime': end.millisecondsSinceEpoch,
            'description': action.description,
          },
        ).launch();
        return true;
      }
    } catch (_) {
      return false;
    }
    return false;
  }
}
