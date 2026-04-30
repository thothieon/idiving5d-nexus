import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AdminTokenService } from './admin-token.service';
import { StaffPermissions } from '../api/models';

/** 工廠函式：產生「需要登入 + 具備特定權限」的路由守衛 */
export const permissionGuard = (key: keyof StaffPermissions): CanActivateFn => () => {
  const tokenSvc = inject(AdminTokenService);
  const router   = inject(Router);

  if (!tokenSvc.has()) return router.parseUrl('/admin/login');
  if (tokenSvc.can(key)) return true;

  return router.parseUrl('/admin/turn');
};
