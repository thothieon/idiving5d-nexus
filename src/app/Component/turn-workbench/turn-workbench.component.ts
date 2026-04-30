import { Component, OnInit, DestroyRef, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { interval, merge, of, Subject } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AdminApiService } from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';
import { TicketListItem, Tag } from '../../Service/api/models';
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
  isAdmin = false;

  loading = true;
  errorMsg = '';

  search = '';
  onlyOverdue   = false;
  filterTagId: number | null = null;
  swapped = false;

  // ── 標籤管理 ─────────────────────────────────────────────
  allTags:       Tag[]   = [];
  tagModalOpen          = false;
  newTagName            = '';
  newTagColor           = '#38bdf8';
  tagSaving             = false;
  tagErr                = '';

  items: any[] = [];
  openItems: any[] = [];
  pendingItems: any[] = [];
  closedItems: any[] = [];

  dashboard: any = null;

  private refreshTrigger$ = new Subject<void>();
  private destroyRef = inject(DestroyRef);

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
    this.isAdmin = this.tokenSvc.isAdmin();
    this.loadTags();

    merge(of(null), interval(30000), this.refreshTrigger$)
      .pipe(
        switchMap(() =>
          this.api.listTickets({ status: 'open,pending,closed', limit: 200 }).pipe(
            catchError((err) => {
              this.loading = false;
              if (err?.status === 401) {
                this.tokenSvc.clear();
                this.router.navigateByUrl('/admin/login');
              } else {
                this.errorMsg = '讀取失敗，將自動重試…';
              }
              return of(null);
            })
          )
        ),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe((items) => {
        if (items === null) return;
        this.items = items || [];
        this.openItems = this.items.filter(x => x.status === 'open');
        this.pendingItems = this.items.filter(x => x.status === 'pending');
        this.closedItems = this.items.filter(x => x.status === 'closed');
        this.dashboard = this.buildDashboard();
        this.loading = false;
        this.cdr.detectChanges();
      });
  }

  setMode(m: Mode) {
    this.mode = m;
  }


  refresh() {
    this.loading = true;
    this.errorMsg = '';
    this.refreshTrigger$.next();
  }

  openTicket(id: number) {
    this.router.navigateByUrl(`/admin/tickets/${id}`);
  }

  goQuickReply() {
    this.router.navigateByUrl('/admin/quickreply');
  }

  goCourses() {
    this.router.navigateByUrl('/admin/courses');
  }

filtered(arr: any[], status: string) {
    const q = (this.search || '').trim().toLowerCase();

    return (arr || [])
      .filter(t => t.status === status)
      .filter(t => {
        if (!q) return true;
        return (
          String(t.ticket_id).includes(q) ||
          String(t.customer_name || '').toLowerCase().includes(q) ||
          String(t.display_name || '').toLowerCase().includes(q) ||
          String(t.subject || '').toLowerCase().includes(q) ||
          String(t.last_customer_text || t.last_in_text || '').toLowerCase().includes(q)
        );
      })
      .filter(t => {
        if (!this.onlyOverdue) return true;
        return this.isOverdue60m(t);
      })
      .filter(t => {
        if (this.filterTagId === null) return true;
        return (t.tags ?? []).some((tg: Tag) => tg.id === this.filterTagId);
      });
  }

  // ── 標籤管理 ─────────────────────────────────────────────

  loadTags() {
    this.api.listTags().subscribe({ next: tags => { this.allTags = tags; this.cdr.detectChanges(); } });
  }

  setFilterTag(id: number | null) {
    this.filterTagId = this.filterTagId === id ? null : id;
  }

  openTagModal() { this.tagModalOpen = true; this.tagErr = ''; }
  closeTagModal() { this.tagModalOpen = false; this.newTagName = ''; this.tagErr = ''; }

  createTag() {
    const name = (this.newTagName || '').trim();
    if (!name) return;
    this.tagSaving = true;
    this.tagErr    = '';
    this.api.createTag({ name, color: this.newTagColor }).subscribe({
      next: () => {
        this.tagSaving  = false;
        this.newTagName = '';
        this.loadTags();
        this.cdr.detectChanges();
      },
      error: e => {
        this.tagSaving = false;
        this.tagErr    = e?.error?.detail ?? '建立失敗';
        this.cdr.detectChanges();
      },
    });
  }

  deleteTag(tag: Tag) {
    if (!confirm(`確定刪除標籤「${tag.name}」？此標籤將從所有客戶移除。`)) return;
    this.api.deleteTag(tag.id).subscribe({
      next: () => {
        if (this.filterTagId === tag.id) this.filterTagId = null;
        this.loadTags();
        this.refreshTrigger$.next();
        this.cdr.detectChanges();
      },
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
