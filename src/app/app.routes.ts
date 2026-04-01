import { Routes } from '@angular/router';

import { TurnWorkbenchComponent } from './Component/turn-workbench/turn-workbench.component';
import { TicketDetailComponent } from './Component/ticket-detail/ticket-detail.component';
import { AdminLoginComponent } from './Component/admin-login/admin-login.component';
import { QuickReplyComponent } from './Component/quick-reply/quick-reply.component';
import { LiffPaymentComponent } from './Component/liff-payment/liff-payment.component';
import { StaffManagementComponent } from './Component/staff-management/staff-management.component';
import { QuestionsStatsComponent } from './Component/questions-stats/questions-stats.component';
import { CourseScheduleComponent } from './Component/course-schedule/course-schedule.component';
import { adminRoleGuard } from './Service/auth/admin-role.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'admin/turn' },

  { path: 'admin', pathMatch: 'full', redirectTo: 'admin/turn' },
  { path: 'admin/login', component: AdminLoginComponent },
  { path: 'admin/turn', component: TurnWorkbenchComponent },
  { path: 'admin/tickets/:id', component: TicketDetailComponent },
  { path: 'admin/quickreply', component: QuickReplyComponent, canActivate: [adminRoleGuard] },
  { path: 'admin/staff', component: StaffManagementComponent, canActivate: [adminRoleGuard] },
  { path: 'admin/questions', component: QuestionsStatsComponent, canActivate: [adminRoleGuard] },
  { path: 'admin/courses',  component: CourseScheduleComponent, canActivate: [adminRoleGuard] },

  // LIFF（不需要 admin 登入）
  { path: 'liff/payment', component: LiffPaymentComponent },

  // fallback
  { path: '**', redirectTo: 'admin/turn' },
];
