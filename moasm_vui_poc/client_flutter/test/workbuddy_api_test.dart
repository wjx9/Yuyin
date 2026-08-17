import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:moasm_vui/src/workbuddy_debug/workbuddy_api.dart';

void main() {
  group('WorkBuddyTaskApi', () {
    test('uses OAuth Bearer and parses task_ticket response', () async {
      late http.Request captured;
      final api = WorkBuddyTaskApi(
        baseUrl: 'https://www.workbuddy.cn/',
        accessToken: 'oauth_test',
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({
              'task_id': 'task-1',
              'status': 'CREATING',
              'name': 'test',
              'link': 'https://acp.example.test/channel',
              'task_ticket': 'sit_test',
            }),
            201,
            headers: {'content-type': 'application/json'},
          );
        }),
      );

      final task = await api.createTask(prompt: 'hello', name: 'test');

      expect(captured.method, 'POST');
      expect(captured.headers['Authorization'], 'Bearer oauth_test');
      expect(captured.headers.containsKey('X-Api-Key'), isFalse);
      expect(jsonDecode(captured.body), {'prompt': 'hello', 'name': 'test'});
      expect(task.taskId, 'task-1');
      expect(task.canConnect, isTrue);
      api.dispose();
    });

    test(
      'optionally adds legacy API key and accepts old token field',
      () async {
        late http.Request captured;
        final api = WorkBuddyTaskApi(
          baseUrl: 'https://www.workbuddy.cn',
          accessToken: 'oauth_test',
          legacyApiKey: 'ck_test',
          client: MockClient((request) async {
            captured = request;
            return http.Response(
              jsonEncode({
                'data': {
                  'id': 'task-2',
                  'status': 'working',
                  'name': 'test',
                  'acp_link': 'https://acp.example.test/channel',
                  'token': 'sit_test',
                },
              }),
              200,
            );
          }),
        );

        final task = await api.getTask('task-2');

        expect(captured.headers['X-Api-Key'], 'ck_test');
        expect(captured.headers['Authorization'], 'Bearer oauth_test');
        expect(task.taskId, 'task-2');
        expect(task.link, 'https://acp.example.test/channel');
        expect(task.taskTicket, 'sit_test');
        api.dispose();
      },
    );

    test('parses paginated task list without task tickets', () async {
      final api = WorkBuddyTaskApi(
        baseUrl: 'https://www.workbuddy.cn',
        accessToken: 'oauth_test',
        client: MockClient((request) async {
          expect(request.url.queryParameters, {'page': '1', 'size': '20'});
          return http.Response(
            jsonEncode({
              'tasks': [
                {
                  'task_id': 'task-3',
                  'status': 'working',
                  'name': '历史任务',
                  'link': 'https://acp.example.test/channel',
                },
              ],
              'pagination': {'total': 1},
            }),
            200,
          );
        }),
      );

      final page = await api.listTasks();

      expect(page.total, 1);
      expect(page.tasks.single.taskId, 'task-3');
      expect(page.tasks.single.canConnect, isFalse);
      api.dispose();
    });

    test('surfaces nested gateway error message', () async {
      final api = WorkBuddyTaskApi(
        baseUrl: 'https://www.workbuddy.cn',
        accessToken: 'oauth_test',
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'error': {
                'code': 401,
                'message': 'missing Authorization Bearer header',
                'status': 'invalid_token',
              },
            }),
            401,
          ),
        ),
      );

      expect(
        () => api.createTask(prompt: 'hello'),
        throwsA(
          isA<WorkBuddyApiException>().having(
            (error) => error.message,
            'message',
            contains('missing Authorization Bearer header'),
          ),
        ),
      );
      api.dispose();
    });
  });
}
