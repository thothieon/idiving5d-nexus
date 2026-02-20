import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AdminTokenService } from './admin-token.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const tokenSvc = inject(AdminTokenService);
  const token = (tokenSvc.token() || '').trim();
  if (!token) return next(req);

  return next(
    req.clone({
      setHeaders: {
        'X-Admin-Token': token,
      },
    })
  );
};
