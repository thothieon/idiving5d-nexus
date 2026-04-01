import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AdminTokenService } from '../../Service/auth/admin-token.service';
import { AdminApiService } from '../../Service/api/admin-api.service';

@Component({
  standalone: true,
  selector: 'app-admin-login',
  imports: [CommonModule, FormsModule],
  templateUrl: './admin-login.component.html',
  styleUrl: './admin-login.component.scss',
})
export class AdminLoginComponent {
  username = '';
  password = '';
  loading  = false;
  errorMsg = '';

  constructor(
    private tokenSvc: AdminTokenService,
    private api: AdminApiService,
    private router: Router,
  ) {}

  login() {
    this.errorMsg = '';
    const u = this.username.trim();
    const p = this.password.trim();
    if (!u || !p) { this.errorMsg = '帳號與密碼不可空白'; return; }

    this.loading = true;
    this.api.login(u, p).subscribe({
      next: (res) => {
        this.loading = false;
        this.tokenSvc.set(res.token, res.role, res.name);
        this.router.navigateByUrl('/admin/turn');
      },
      error: (err) => {
        this.loading = false;
        this.errorMsg = err?.error?.detail ?? '帳號或密碼錯誤';
      },
    });
  }

  onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') this.login();
  }
}
