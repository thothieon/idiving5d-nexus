import { Component, computed, signal, inject } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { NgIf } from '@angular/common';
import { Router, NavigationEnd } from '@angular/router';
import { AdminTokenService } from './Service/auth/admin-token.service';
import { filter } from 'rxjs/operators';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, NgIf],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App {
  protected readonly title = signal('idiving5d-nexus');

  private tokenSvc = inject(AdminTokenService);
  private router   = inject(Router);

  hasToken  = computed(() => this.tokenSvc.has());
  isAdmin   = computed(() => this.tokenSvc.isAdmin());
  staffName = computed(() => this.tokenSvc.name());
  isLiff    = signal(false);

  constructor() {
    this.router.events.pipe(filter(e => e instanceof NavigationEnd)).subscribe((e: any) => {
      this.isLiff.set((e.urlAfterRedirects ?? e.url ?? '').startsWith('/liff'));
    });
  }

  clearToken() {
    this.tokenSvc.clear();
    this.router.navigateByUrl('/admin/login');
  }
}
