# RBAC Endpoint Matrix

- Total API endpoints: **165**
- Unsecured API endpoints (unexpected): **0**

| Method | Endpoint | Status | Role Access | Auth Required | Rate Limited |
|---|---|---|---|---|---|
| `GET` | `/api/v1/academic-years` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/academic-years` | Active | Permissions: academic_year:manage | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/academic-years/{old_year_id}/rollover` | Deprecated | Permissions: academic_year:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/academic-years/{year_id}` | Active | Permissions: academic_year:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/academic-years/{year_id}/activate` | Active | Permissions: academic_year:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/announcements` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/announcements` | Active | Permissions: announcement:create | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/announcements/{announcement_id}` | Active | Permissions: announcement:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/assignments` | Active | Permissions: assignment:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/assignments` | Active | Permissions: assignment:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/assignments/{assignment_id}` | Active | Permissions: assignment:read | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/assignments/{assignment_id}` | Active | Permissions: assignment:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/attendance` | Active | Permissions: attendance:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/attendance` | Active | Permissions: attendance:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/attendance/analytics/below-threshold` | Active | Permissions: attendance:analytics | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/attendance/analytics/class/{standard_id}` | Active | Permissions: attendance:analytics | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/attendance/analytics/student/{student_id}` | Active | Permissions: attendance:analytics | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/auth/forgot-password` | Active | Public | No | Yes (strict 5/min) |
| `POST` | `/api/v1/auth/login` | Active | Public | No | Yes (strict 5/min) |
| `POST` | `/api/v1/auth/logout` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/auth/me` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/auth/refresh` | Active | Public | No | Yes (strict 15/min) |
| `POST` | `/api/v1/auth/reset-password` | Active | Public | No | Yes (strict 5/min) |
| `POST` | `/api/v1/auth/verify-otp` | Active | Public | No | Yes (strict 8/min) |
| `GET` | `/api/v1/behaviour` | Active | Permissions: behaviour_log:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/behaviour` | Active | Permissions: behaviour_log:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/chat/conversations` | Active | Permissions: chat:message | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/chat/conversations` | Active | Permissions: chat:message | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/chat/conversations/{conversation_id}/files` | Active | Permissions: chat:message | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/chat/conversations/{conversation_id}/messages` | Active | Permissions: chat:message | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/chat/conversations/{conversation_id}/read` | Active | Permissions: chat:message | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/chat/users` | Active | Permissions: chat:message | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/complaints` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/complaints` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/complaints/feedback` | Active | Permissions: complaint:create | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/complaints/{complaint_id}/status` | Active | Permissions: complaint:read | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/diary` | Active | Permissions: diary:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/diary` | Active | Permissions: diary:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/documents` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/documents/request` | Active | Permissions: document:generate | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/documents/requirements` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PUT` | `/api/v1/documents/requirements` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/documents/requirements/status` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/documents/upload` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/documents/{document_id}/download` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/documents/{document_id}/verify` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/exam-schedule` | Active | Permissions: exam_schedule:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/exam-schedule` | Active | Permissions: exam_schedule:create | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/exam-schedule/entries/{entry_id}/cancel` | Active | Permissions: exam_schedule:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/exam-schedule/series` | Active | Permissions: exam_schedule:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/exam-schedule/{series_id}/entries` | Active | Permissions: exam_schedule:create | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/exam-schedule/{series_id}/publish` | Active | Permissions: exam_schedule:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/fees` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/fees/analytics` | Active | Roles: PRINCIPAL, SUPERADMIN, TRUSTEE | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/fees/ledger/generate` | Active | Permissions: fee:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/fees/payments` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/fees/payments` | Active | Permissions: fee:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/fees/payments/{payment_id}/receipt` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/fees/structures` | Active | Permissions: fee:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/fees/structures/batch` | Active | Permissions: fee:create | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/fees/structures/{structure_id}` | Active | Permissions: fee:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/files/{bucket}/{file_key:path}` | Deprecated | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/gallery/albums` | Active | Permissions: gallery:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/gallery/albums` | Active | Permissions: gallery:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/gallery/albums/{album_id}/photos` | Active | Permissions: gallery:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/gallery/albums/{album_id}/photos` | Active | Permissions: gallery:create | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/gallery/photos/{photo_id}/comments` | Active | Permissions: gallery:read | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/gallery/photos/{photo_id}/feature` | Active | Permissions: gallery:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/gallery/photos/{photo_id}/interactions` | Active | Permissions: gallery:read | Yes | Yes (general 60/min) |
| `DELETE` | `/api/v1/gallery/photos/{photo_id}/reaction` | Active | Permissions: gallery:read | Yes | Yes (general 60/min) |
| `PUT` | `/api/v1/gallery/photos/{photo_id}/reaction` | Active | Permissions: gallery:read | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/homework` | Active | Permissions: homework:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/homework` | Active | Permissions: homework:create | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/homework/responses` | Active | Permissions: submission:create | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/homework/responses/{submission_id}/review` | Active | Permissions: submission:grade | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/homework/{homework_id}/responses` | Active | Permissions: homework:read | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/leave` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/leave/apply` | Active | Permissions: leave:apply | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/leave/balance` | Active | Permissions: leave:apply | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/leave/balance/teacher/{teacher_id}` | Active | Permissions: leave:approve | Yes | Yes (general 60/min) |
| `PUT` | `/api/v1/leave/balance/teacher/{teacher_id}` | Active | Permissions: leave:approve | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/leave/{leave_id}/decision` | Active | Permissions: leave:approve | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/masters/grades` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/masters/grades` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/masters/grades/lookup` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `DELETE` | `/api/v1/masters/grades/{grade_id}` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/masters/grades/{grade_id}` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/masters/standards` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/masters/standards` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `DELETE` | `/api/v1/masters/standards/{standard_id}` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/masters/standards/{standard_id}` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/masters/subjects` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/masters/subjects` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `DELETE` | `/api/v1/masters/subjects/{subject_id}` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/masters/subjects/{subject_id}` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/notifications` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `DELETE` | `/api/v1/notifications/clear-read` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/notifications/mark-all-read` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/notifications/mark-read` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/notifications/unread-count` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/parents` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/parents` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/parents/me/children` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/parents/me/children/link` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/parents/{parent_id}` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/parents/{parent_id}` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/parents/{parent_id}/children` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/parents/{parent_id}/children` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/principal-reports/details` | Active | Roles: PRINCIPAL, SUPERADMIN, TRUSTEE | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/principal-reports/overview` | Active | Roles: PRINCIPAL, SUPERADMIN, TRUSTEE | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/results` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/results/entries` | Active | Permissions: result:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/results/exams` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/results/exams` | Active | Permissions: result:create | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/results/exams/bulk` | Active | Permissions: result:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/results/exams/{exam_id}/distribution` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/results/exams/{exam_id}/publish` | Active | Permissions: result:publish | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/results/report-card/upload` | Active | Permissions: result:create | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/results/report-card/{student_id}` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/results/sections` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/schools` | Active | Permissions: school:manage | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/schools` | Active | Permissions: school:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/schools/{school_id}` | Active | Permissions: school:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/schools/{school_id}` | Active | Permissions: school:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/schools/{school_id}/deactivate` | Active | Permissions: school:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/settings` | Active | Permissions: settings:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/settings` | Active | Permissions: settings:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/students` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/students` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/students/me` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/students/promotion-status/bulk` | Active | Permissions: student:promote | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/students/promotion-status/section` | Active | Permissions: student:promote | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/students/sections` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/students/sections` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/students/{student_id}` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/students/{student_id}` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/students/{student_id}/promotion-status` | Active | Permissions: student:promote | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/submissions` | Active | Permissions: assignment:read | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/submissions` | Active | Permissions: submission:create | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/submissions/{submission_id}/grade` | Active | Permissions: submission:grade | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/submissions/{submission_id}/review` | Active | Permissions: submission:grade | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/teacher-assignments` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/teacher-assignments` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/teacher-assignments/mine` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `DELETE` | `/api/v1/teacher-assignments/{assignment_id}` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/teacher-assignments/{assignment_id}` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/teacher-class-subjects` | Deprecated | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/teacher-class-subjects/mine` | Deprecated | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/teachers` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/teachers` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/teachers/me/assignments` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/teachers/{teacher_id}` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/teachers/{teacher_id}` | Active | Permissions: user:manage | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/timetable` | Active | Roles: PRINCIPAL, TEACHER | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/timetable/sections` | Active | Roles: PRINCIPAL, TEACHER | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/timetable/{standard_id}` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/timetable/{standard_id}/sections` | Active | Roles: PRINCIPAL, TEACHER | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/users` | Deprecated | Permissions: user:manage | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/users` | Deprecated | Permissions: user:manage | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/users/me` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/users/me` | Active | Authenticated users | Yes | Yes (general 60/min) |
| `GET` | `/api/v1/users/{user_id}` | Deprecated | Permissions: user:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/users/{user_id}` | Deprecated | Permissions: user:manage | Yes | Yes (general 60/min) |
| `PATCH` | `/api/v1/users/{user_id}/deactivate` | Deprecated | Permissions: user:manage | Yes | Yes (general 60/min) |
| `POST` | `/api/v1/users/{user_id}/photo` | Active | Authenticated users | Yes | Yes (general 60/min) |
