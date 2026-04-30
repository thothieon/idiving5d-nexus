import { Routes } from '@angular/router';

import { TurnWorkbenchComponent } from './Component/turn-workbench/turn-workbench.component';
import { TicketDetailComponent } from './Component/ticket-detail/ticket-detail.component';
import { AdminLoginComponent } from './Component/admin-login/admin-login.component';
import { QuickReplyComponent } from './Component/quick-reply/quick-reply.component';
import { LiffPaymentComponent } from './Component/liff-payment/liff-payment.component';
import { StaffManagementComponent } from './Component/staff-management/staff-management.component';
import { QuestionsStatsComponent } from './Component/questions-stats/questions-stats.component';
import { CourseScheduleComponent } from './Component/course-schedule/course-schedule.component';
import { RegistrationComponent } from './Component/registration/registration.component';
import { PageStatsComponent } from './Component/page-stats/page-stats.component';
import { LineStatsComponent } from './Component/line-stats/line-stats.component';
import { adminRoleGuard } from './Service/auth/admin-role.guard';
import { permissionGuard } from './Service/auth/permission.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'admin/turn' },

  { path: 'admin', pathMatch: 'full', redirectTo: 'admin/turn' },
  { path: 'admin/login', component: AdminLoginComponent },
  { path: 'admin/turn', component: TurnWorkbenchComponent },
  { path: 'admin/tickets/:id', component: TicketDetailComponent },
  { path: 'admin/quickreply',   component: QuickReplyComponent,      canActivate: [permissionGuard('can_quickreply')] },
  { path: 'admin/staff',        component: StaffManagementComponent,  canActivate: [adminRoleGuard] },
  { path: 'admin/questions',    component: QuestionsStatsComponent,   canActivate: [permissionGuard('can_questions')] },
  { path: 'admin/courses',      component: CourseScheduleComponent,   canActivate: [permissionGuard('can_courses')] },
  { path: 'admin/registration', component: RegistrationComponent,     canActivate: [permissionGuard('can_registration')] },
  { path: 'admin/pagestats',    component: PageStatsComponent,        canActivate: [permissionGuard('can_pagestats')] },
  { path: 'admin/linestats',    component: LineStatsComponent,        canActivate: [permissionGuard('can_linestats')] },

  // LIFF（不需要 admin 登入）
  { path: 'liff/payment', component: LiffPaymentComponent },

  // fallback
  { path: '**', redirectTo: 'admin/turn' },
];
