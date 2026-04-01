import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AdminTokenService } from './admin-token.service';

export const adminRoleGuard: CanActivateFn = () => {
  const tokenSvc = inject(AdminTokenService);
  const router   = inject(Router);

  if (tokenSvc.isAdmin()) return true;

  return router.parseUrl('/admin/turn');
};
