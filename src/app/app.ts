import { Component, computed, signal, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { NgIf } from '@angular/common';
import { AdminTokenService } from './Service/auth/admin-token.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, NgIf],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App {
  protected readonly title = signal('idiving5d-nexus');
  
  private tokenSvc = inject(AdminTokenService);

  hasToken = computed(() => this.tokenSvc.has());

  clearToken() {
    this.tokenSvc.clear();
  }
}
