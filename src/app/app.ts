import { Component, computed, signal, inject, OnInit } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { NgIf } from '@angular/common';
import { Router, NavigationEnd } from '@angular/router';
import { AdminTokenService } from './Service/auth/admin-token.service';
import { AdminApiService } from './Service/api/admin-api.service';
import { filter } from 'rxjs/operators';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, NgIf],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App implements OnInit {
  protected readonly title = signal('idiving5d-nexus');

  private tokenSvc = inject(AdminTokenService);
  private api      = inject(AdminApiService);
  private router   = inject(Router);

  hasToken  = computed(() => this.tokenSvc.has());
  isAdmin   = computed(() => this.tokenSvc.isAdmin());
  staffName = computed(() => this.tokenSvc.name());
  isLiff    = signal(false);

  canRegistration = computed(() => this.tokenSvc.can('can_registration'));
  canCustomers    = computed(() => this.tokenSvc.can('can_customers'));
  canCourses      = computed(() => this.tokenSvc.can('can_courses'));
  canPagestats    = computed(() => this.tokenSvc.can('can_pagestats'));
  canLinestats    = computed(() => this.tokenSvc.can('can_linestats'));
  canQuestions    = computed(() => this.tokenSvc.can('can_questions'));
  canQuickreply   = computed(() => this.tokenSvc.can('can_quickreply'));

  constructor() {
    this.router.events.pipe(filter(e => e instanceof NavigationEnd)).subscribe((e: any) => {
      this.isLiff.set((e.urlAfterRedirects ?? e.url ?? '').startsWith('/liff'));
    });
  }

  ngOnInit() {
    // 每次開頁面自動從後端同步最新 permissions，讓 admin 修改後立即生效
    if (this.tokenSvc.has()) {
      this.api.me().subscribe({
        next: (res) => {
          const perms = res.staff?.permissions ?? null;
          this.tokenSvc.updatePermissions(perms);
        },
        error: () => { /* token 失效時不處理，各 component 的 guard 會處理 */ }
      });
    }
  }

  clearToken() {
    this.tokenSvc.clear();
    this.router.navigateByUrl('/admin/login');
  }
}
