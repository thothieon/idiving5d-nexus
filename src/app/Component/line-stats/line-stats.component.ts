// line-stats.component.ts
import { Component, OnInit, ChangeDetectorRef, inject, DestroyRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AdminApiService }   from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';

@Component({
  standalone: true,
  selector:   'app-line-stats',
  imports:    [CommonModule, FormsModule],
  templateUrl: './line-stats.component.html',
  styleUrl:    './line-stats.component.scss',
})
export class LineStatsComponent implements OnInit {
  private destroyRef = inject(DestroyRef);

  days          = 30;
  loading       = false;
  reportSending = false;
  reportMsg     = '';
  tab: 'overview' | 'daily' | 'peak' | 'tickets' | 'intents' | 'types' | 'courses' = 'overview';

  // ── 資料 ────────────────────────────────────────────────
  overview:     any    = null;
  daily:        any[]  = [];
  peakHours:    any[]  = [];
  ticketStats:  any    = null;
  intents:      any[]  = [];
  msgTypes:     any[]  = [];
  courses:      any[]  = [];

  constructor(
    private api:      AdminApiService,
    private tokenSvc: AdminTokenService,
    private router:   Router,
    private cdr:      ChangeDetectorRef,
  ) {}

  ngOnInit() {
    if (!this.tokenSvc.has()) { this.router.navigateByUrl('/admin/login'); return; }
    this.loadAll();
  }

  loadAll() {
    this.loading = true;
    let done = 0;
    const check = () => { if (++done === 7) { this.loading = false; this.cdr.detectChanges(); } };

    this.api.lineOverview(this.days).subscribe({ next: r => { this.overview = r; check(); }, error: check });
    this.api.lineDaily(this.days).subscribe({ next: r => { this.daily = r.items ?? []; check(); }, error: check });
    this.api.linePeakHours(this.days).subscribe({ next: r => { this.peakHours = r.items ?? []; check(); }, error: check });
    this.api.lineTickets(this.days).subscribe({ next: r => { this.ticketStats = r; check(); }, error: check });
    this.api.lineIntents(this.days).subscribe({ next: r => { this.intents = r.items ?? []; check(); }, error: check });
    this.api.lineMessageTypes(this.days).subscribe({ next: r => { this.msgTypes = r.items ?? []; check(); }, error: check });
    this.api.lineCourses(this.days).subscribe({ next: r => { this.courses = r.items ?? []; check(); }, error: check });
  }

  onDaysChange() { this.loadAll(); }

  sendDailyReport() {
    if (this.reportSending) return;
    this.reportSending = true;
    this.reportMsg     = '';
    this.api.lineSendDailyReport().subscribe({
      next: () => {
        this.reportSending = false;
        this.reportMsg     = '✅ 摘要已發送至 LINE，約 10 秒後收到';
        this.cdr.detectChanges();
        setTimeout(() => { this.reportMsg = ''; this.cdr.detectChanges(); }, 5000);
      },
      error: () => {
        this.reportSending = false;
        this.reportMsg     = '❌ 發送失敗，請稍後再試';
        this.cdr.detectChanges();
        setTimeout(() => { this.reportMsg = ''; this.cdr.detectChanges(); }, 5000);
      },
    });
  }

  // ── 每日圖表輔助 ─────────────────────────────────────────
  get maxDailyMsgs(): number {
    return Math.max(1, ...this.daily.map(d => d.msgs_in + d.msgs_out));
  }

  barH(val: number, max: number): string {
    return Math.round((val / max) * 100) + '%';
  }

  // ── 尖峰時段 ─────────────────────────────────────────────
  get maxPeakCnt(): number {
    return Math.max(1, ...this.peakHours.map(h => h.cnt));
  }

  peakColor(cnt: number): string {
    const ratio = cnt / this.maxPeakCnt;
    if (ratio >= 0.75) return '#EF5350';
    if (ratio >= 0.45) return '#FFA726';
    return '#42A5F5';
  }

  // ── 工具 ─────────────────────────────────────────────────
  formatMin(min: number | null): string {
    if (min == null) return '—';
    if (min < 60)   return `${min} 分`;
    const h = Math.floor(min / 60);
    const m = min % 60;
    return m ? `${h} 時 ${m} 分` : `${h} 時`;
  }

  shortDate(iso: string): string {
    const d = new Date(iso);
    return `${d.getMonth()+1}/${d.getDate()}`;
  }
}
