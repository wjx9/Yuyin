import 'package:flutter/foundation.dart';
import 'package:android_intent_plus/android_intent.dart';
import 'package:url_launcher/url_launcher.dart';

import '../data/models.dart';

class CalendarService {
  Future<bool> open() async {
    final Uri uri;
    if (defaultTargetPlatform == TargetPlatform.android) {
      try {
        await AndroidIntent(
          action: 'android.intent.action.MAIN',
          category: 'android.intent.category.APP_CALENDAR',
        ).launch();
        return true;
      } catch (_) {
        return false;
      }
    } else if (defaultTargetPlatform == TargetPlatform.iOS) {
      uri = Uri.parse('calshow://');
    } else {
      uri = Uri.parse('https://calendar.google.com/calendar/u/0/r');
    }
    return launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  Future<bool> create(CalendarEvent event) async {
    if (defaultTargetPlatform == TargetPlatform.android) {
      try {
        await AndroidIntent(
          action: 'android.intent.action.INSERT',
          data: 'content://com.android.calendar/events',
          category: 'android.intent.category.DEFAULT',
          arguments: {
            'title': event.title,
            'beginTime': event.start.millisecondsSinceEpoch,
            'endTime': event.end.millisecondsSinceEpoch,
            'eventLocation': event.location,
            'description': event.description,
          },
        ).launch();
        return true;
      } catch (_) {
        return false;
      }
    }
    return open();
  }
}
