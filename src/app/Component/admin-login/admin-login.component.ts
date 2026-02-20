import { Component, OnInit, inject } from '@angular/core';
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
export class AdminLoginComponent implements OnInit {
  token = '';
  err = '';
  loading = false;
  errorMsg = '';

  constructor(
    private tokenSvc: AdminTokenService,
    private api: AdminApiService,
    private router: Router
  ) {}

  ngOnInit() {}

  login() {
    this.err = '';
    const t = (this.token || '').trim();
    if (!t) { this.err = 'Token 不可空白'; return; }

    this.loading = true;
    this.tokenSvc.set(t);

    this.api.me().subscribe({
      next: () => {
        this.loading = false;
        this.router.navigateByUrl('/admin/turn');
      },
      error: () => {
        this.loading = false;
        this.tokenSvc.clear();
        this.err = 'Token 無效或已撤銷';
      }
    });
  }
}
