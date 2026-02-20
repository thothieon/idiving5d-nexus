import { Routes } from '@angular/router';

import { TurnWorkbenchComponent } from './Component/turn-workbench/turn-workbench.component';
import { TicketDetailComponent } from './Component/ticket-detail/ticket-detail.component';
import { AdminLoginComponent } from './Component/admin-login/admin-login.component';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'admin/turn' },

  { path: 'admin', pathMatch: 'full', redirectTo: 'admin/turn' },
  { path: 'admin/login', component: AdminLoginComponent },
  { path: 'admin/turn', component: TurnWorkbenchComponent },
  { path: 'admin/tickets/:id', component: TicketDetailComponent },

  // fallback
  { path: '**', redirectTo: 'admin/turn' },
];
