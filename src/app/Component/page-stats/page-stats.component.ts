import { Component, OnInit, OnDestroy, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';

import { AdminApiService }   from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';

interface PageItem     { page_path: string; views: number; uniques: number; avg_duration: number|null; bounce_pct: number|null; }
interface DailyItem    { date: string; views: number; uniques: number; }
interface RefItem      { referrer: string; views: number; }
interface DeviceItem   { device_type: string; views: number; }
interface SessionItem  { session_id: string; page_count: number; start_at: string; duration_sec: number; journey: string; }

type Tab = 'overview' | 'pages' | 'daily' | 'referrers' | 'sessions';

@Component({
  standalone: true,
  selector: 'app-page-stats',
  imports: [CommonModule],
  templateUrl: './page-stats.component.html',
  styleUrl: './page-stats.component.scss',
})
export class PageStatsComponent implements OnInit, OnDestroy {

  // ── 全域控制 ─────────────────────────────────────────────
  tab: Tab = 'overview';
  days = 7;
  readonly dayOptions = [1, 7, 30];
  loading  = false;
  errorMsg = '';

  // ── 即時在線 ─────────────────────────────────────────────
  online      = 0;
  onlinePages: { page_path: string; cnt: number }[] = [];
  private onlineTimer: ReturnType<typeof setInterval> | null = null;

  // ── 各 tab 資料 ──────────────────────────────────────────
  totalViews   = 0;
  pages:   PageItem[]    = [];
  daily:   DailyItem[]   = [];
  refs:    RefItem[]     = [];
  devices: DeviceItem[]  = [];
  sessions: SessionItem[] = [];

  // ── 圖表尺寸常數 ─────────────────────────────────────────
  private readonly CW = 600;
  private readonly CH = 100;

  constructor(
    private api:      AdminApiService,
    private tokenSvc: AdminTokenService,
    private router:   Router,
    private cdr:      ChangeDetectorRef,
  ) {}

  ngOnInit() {
    if (!this.tokenSvc.isAdmin()) {
      this.router.navigateByUrl('/admin/turn');
      return;
    }
    this.loadAll();
    this.loadOnline();
    this.onlineTimer = setInterval(() => this.loadOnline(), 30_000);
  }

  ngOnDestroy() {
    if (this.onlineTimer) clearInterval(this.onlineTimer);
  }

  // ── 資料載入 ─────────────────────────────────────────────

  setTab(t: Tab)   { this.tab = t; }
  setDays(d: number) {
    if (this.days === d) return;
    this.days = d;
    this.loadAll();
  }

  loadAll() {
    this.loading  = true;
    this.errorMsg = '';
    let done = 0;
    const check = () => { if (++done === 5) { this.loading = false; this.cdr.detectChanges(); } };

    this.api.statsPageViews(this.days).subscribe({
      next: r => { this.totalViews = r.total ?? 0; this.pages = r.items ?? []; check(); },
      error: () => check(),
    });
    this.api.statsPageViewsDaily(this.days).subscribe({
      next: r => { this.daily = this._fillDailyGaps(r.items ?? [], this.days); check(); },
      error: () => check(),
    });
    this.api.statsPageViewsReferrers(this.days).subscribe({
      next: r => { this.refs = r.items ?? []; check(); },
      error: () => check(),
    });
    this.api.statsPageViewsDevices(this.days).subscribe({
      next: r => { this.devices = r.items ?? []; check(); },
      error: () => check(),
    });
    this.api.statsPageViewsSessions(this.days).subscribe({
      next: r => { this.sessions = r.items ?? []; check(); },
      error: () => check(),
    });
  }

  loadOnline() {
    this.api.statsPageViewsOnline().subscribe({
      next: r => {
        this.online      = r.online ?? 0;
        this.onlinePages = r.pages  ?? [];
        this.cdr.detectChanges();
      },
    });
  }

  back() { this.router.navigateByUrl('/admin/turn'); }

  // ── 補齊每日缺漏日期（無資料的日 = 0）───────────────────
  private _fillDailyGaps(items: DailyItem[], days: number): DailyItem[] {
    const map = new Map(items.map(i => [i.date, i]));
    const result: DailyItem[] = [];
    const today = new Date();
    for (let d = days - 1; d >= 0; d--) {
      const dt  = new Date(today);
      dt.setDate(today.getDate() - d);
      const key = dt.toISOString().slice(0, 10);
      result.push(map.get(key) ?? { date: key, views: 0, uniques: 0 });
    }
    return result;
  }

  // ── 折線圖 helpers ───────────────────────────────────────

  linePoints(key: 'views' | 'uniques'): string {
    const items = this.daily;
    if (items.length < 2) return '';
    const max = Math.max(...items.map(i => i[key]), 1);
    return items.map((item, idx) => {
      const x = (idx / (items.length - 1)) * this.CW;
      const y = this.CH - (item[key] / max) * (this.CH - 12) - 2;
      return `${x.toFixed(0)},${y.toFixed(0)}`;
    }).join(' ');
  }

  areaPath(key: 'views' | 'uniques'): string {
    const items = this.daily;
    if (items.length < 2) return '';
    const max = Math.max(...items.map(i => i[key]), 1);
    const pts = items.map((item, idx) => {
      const x = (idx / (items.length - 1)) * this.CW;
      const y = this.CH - (item[key] / max) * (this.CH - 12) - 2;
      return `${x.toFixed(0)},${y.toFixed(0)}`;
    });
    return `M 0,${this.CH} L ${pts.join(' L ')} L ${this.CW},${this.CH} Z`;
  }

  xLabels(): { x: number; label: string }[] {
    const items = this.daily;
    if (!items.length) return [];
    const step = Math.max(1, Math.floor(items.length / 5));
    return items
      .map((item, idx) => ({ item, idx }))
      .filter(({ idx }) => idx === 0 || idx === items.length - 1 || idx % step === 0)
      .map(({ item, idx }) => ({
        x:     (idx / Math.max(items.length - 1, 1)) * this.CW,
        label: item.date.slice(5),
      }));
  }

  maxDailyViews(): number {
    return Math.max(...this.daily.map(d => d.views), 1);
  }

  // ── 裝置圓餅 helpers ─────────────────────────────────────
  deviceTotal(): number {
    return this.devices.reduce((s, d) => s + d.views, 0) || 1;
  }

  devicePct(views: number): number {
    return Math.round((views / this.deviceTotal()) * 100);
  }

  deviceColor(type: string): string {
    return { mobile: '#38bdf8', desktop: '#818cf8', tablet: '#34d399' }[type] ?? '#64748b';
  }

  deviceLabel(type: string): string {
    return { mobile: '📱 手機', desktop: '🖥 電腦', tablet: '📟 平板' }[type] ?? type;
  }

  // ── 通用 helpers ─────────────────────────────────────────
  get maxPageViews(): number { return this.pages[0]?.views ?? 1; }
  get maxRefViews():  number { return this.refs[0]?.views  ?? 1; }

  fmtDur(sec: number | null): string {
    if (sec == null || sec < 0) return '—';
    if (sec < 60) return `${sec}s`;
    return `${Math.floor(sec / 60)}m${sec % 60}s`;
  }

  fmtDate(iso: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    return `${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
  }
}
