import { Component, OnInit, DestroyRef, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { interval, merge, of } from 'rxjs';
import { catchError, startWith, switchMap, tap } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AdminApiService } from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';
import { Dashboard, TicketListItem, TicketStatus } from '../../Service/api/models';
import { TicketListItemComponent } from '../../shared/components/ticket-list-item/ticket-list-item.component';

type Mode = 'turn' | 'closed';

@Component({
  standalone: true,
  selector: 'app-turn-workbench',
  imports: [CommonModule, FormsModule, TicketListItemComponent],
  templateUrl: './turn-workbench.component.html',
  styleUrl: './turn-workbench.component.scss',
})
export class TurnWorkbenchComponent implements OnInit {
  mode: Mode = 'turn';

  loading = true;
  errorMsg = '';

  search = '';
  onlyOverdue = false;

  items: any[] = [];
  openItems: any[] = [];
  pendingItems: any[] = [];
  closedItems: any[] = [];

  q = '';

  dashboard: any = null;

  constructor(
    private api: AdminApiService,
    private tokenSvc: AdminTokenService,
    private router: Router,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit() {
    if (!this.tokenSvc.has()) {
      this.router.navigateByUrl('/admin/login');
      return;
    }
    this.refresh();
  }

  setMode(m: Mode) {
    this.mode = m;
  }

  logout() {
    this.tokenSvc.clear();
    this.router.navigateByUrl('/admin/login');
  }

  refresh() {
    this.loading = true;
    this.errorMsg = '';

    // 一次拉 open/pending/closed（後端 tickets 支援 status=...）
    this.api.listTickets({ status: 'open,pending,closed', limit: 200 }).subscribe({
      next: (items) => {
        this.items = items || [];
        this.openItems = this.items.filter(x => x.status === 'open');
        this.pendingItems = this.items.filter(x => x.status === 'pending');
        this.closedItems = this.items.filter(x => x.status === 'closed');

        this.dashboard = this.buildDashboard();
        this.loading = false;
        this.cdr.detectChanges();
      },
      error: (e) => {
        this.loading = false;
        this.errorMsg = '讀取失敗（可能 token 失效或 API 無法連線）';
        this.cdr.detectChanges();
        this.router.navigateByUrl('/admin/login');
      }
    });
  }

  openTicket(id: number) {
    this.router.navigateByUrl(`/admin/tickets/${id}`);
  }

  goQuickReply() {
    this.router.navigateByUrl('/admin/quickreply');
  }

  filtered(arr: any[], status: string) {
    const q = (this.search || '').trim().toLowerCase();

    return (arr || [])
      .filter(t => t.status === status)
      .filter(t => {
        if (!q) return true;
        return (
          String(t.ticket_id).includes(q) ||
          String(t.display_name || '').toLowerCase().includes(q) ||
          String(t.subject || '').toLowerCase().includes(q) ||
          String(t.last_customer_text || t.last_in_text || '').toLowerCase().includes(q)
        );
      })
      .filter(t => {
        if (!this.onlyOverdue) return true;
        return this.isOverdue60m(t);
      });
  }

  private buildDashboard() {
    const today = new Date();
    const isSameDay = (d: Date) =>
      d.getFullYear() === today.getFullYear() &&
      d.getMonth() === today.getMonth() &&
      d.getDate() === today.getDate();

    const todayNew = (this.items || []).filter(t => {
      const dt = this.parseDate(t.opened_at) || this.parseDate(t.created_at);
      return dt ? isSameDay(dt) : false;
    }).length;

    const overdue = (this.openItems || []).filter(t => this.isOverdue60m(t)).length;

    return {
      today_new: todayNew,
      open_cnt: (this.openItems || []).length,
      pending_cnt: (this.pendingItems || []).length,
      overdue_60m: overdue
    };
  }

  private isOverdue60m(t: any) {
    // 你後端欄位：last_customer_message_at / opened_at
    const base =
      this.parseDate(t.last_customer_message_at) ||
      this.parseDate(t.opened_at) ||
      this.parseDate(t.updated_at);

    if (!base) return false;

    const diffMin = (Date.now() - base.getTime()) / 60000;
    return diffMin >= 60;
  }

  private parseDate(s: any): Date | null {
    if (!s) return null;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }
}
